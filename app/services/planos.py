from datetime import date, datetime, timedelta, timezone
import re
import time
from typing import Any, Optional

from config.settings import settings
from database import (
    Contrato,
    Escola,
    Grupo,
    Nota_fiscal,
    Pgto,
    Plano,
    Session,
    User_cont,
    User_esc,
    User_grupo,
    Usuario,
    garantir_planos_iniciais,
    select,
    user2famethods,
)
from fastapi import HTTPException, status
from schemas.schemas import (
    AdicionarProfessorRequest,
    AtualizarTagsRequest,
    ContratarPlanoRequest,
    CriarEscolaRequest,
    Tipo2FA,
)
import security
from services.users import (
    _normalizar_tags,
    obter_claims_jwt_usuario,
    provisionar_estrutura_inicial_usuario,
)

_CACHE_CONTEXTO_ESCOLA: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SEGUNDOS = 300.0


def invalidar_cache_permissoes() -> None:
    _CACHE_CONTEXTO_ESCOLA.clear()


def validar_documento_contrato(tipo_cont: str, documento: str) -> tuple[str, str]:
    """Valida tipo_cont ('cpf' ou 'cnpj') e a quantidade exata de dígitos do documento."""
    tipo = (tipo_cont or "").strip().lower()
    if tipo not in ("cpf", "cnpj"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O tipo de contrato deve ser 'cpf' ou 'cnpj'.",
        )
    apenas_digitos = re.sub(r"\D", "", documento or "")
    if tipo == "cpf" and len(apenas_digitos) != 11:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CPF inválido: deve conter exatamente 11 dígitos numéricos.",
        )
    if tipo == "cnpj" and len(apenas_digitos) != 14:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CNPJ inválido: deve conter exatamente 14 dígitos numéricos.",
        )
    return tipo, apenas_digitos


def obter_contexto_escola(
    sessao: Session, id_usuario: int, id_escola: int
) -> dict[str, Any]:
    """Resolve o plano ativo da escola, limites efetivos e o papel/permissões do usuário nela."""
    chave = (id_usuario, id_escola)
    agora = time.monotonic()
    if chave in _CACHE_CONTEXTO_ESCOLA:
        ts, dados_cache = _CACHE_CONTEXTO_ESCOLA[chave]
        if agora - ts < _CACHE_TTL_SEGUNDOS:
            return dados_cache

    escola = sessao.get(Escola, id_escola)
    if not escola:
        raise HTTPException(status_code=404, detail="Escola não encontrada.")

    usuario = sessao.get(Usuario, id_usuario)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    grupo = sessao.get(Grupo, escola.fk_Grupo_id_grupo)
    vinc_esc = sessao.execute(
        select(User_esc).where(
            User_esc.fk_Usuario_id_usuario == id_usuario,
            User_esc.fk_Escola_id_escola == id_escola,
        )
    ).scalars().first()
    vinc_grupo = None
    if grupo:
        vinc_grupo = sessao.execute(
            select(User_grupo).where(
                User_grupo.fk_Usuario_id_usuario == id_usuario,
                User_grupo.fk_Grupo_id_grupo == grupo.id_grupo,
            )
        ).scalars().first()

    eh_dono_grupo = bool(grupo and grupo.fk_Usuario_id_usuario == id_usuario)
    if not vinc_esc and not vinc_grupo and not eh_dono_grupo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não possui vínculo com esta escola.",
        )

    planos_map = {p.id_plano: p for p in garantir_planos_iniciais(sessao).values()}

    contrato = None
    if escola.fk_Contrato_id_cont:
        contrato = sessao.get(Contrato, escola.fk_Contrato_id_cont)
    if not contrato and grupo and grupo.fk_Contrato_id_cont:
        contrato = sessao.get(Contrato, grupo.fk_Contrato_id_cont)

    plano_obj = planos_map.get(contrato.fk_Plano_id_plano) if contrato else planos_map["basico"]
    nome_plano = plano_obj.nome_plano if plano_obj else "basico"

    papel = "professor"
    if vinc_esc:
        papel = vinc_esc.papel
    elif vinc_grupo:
        papel = vinc_grupo.papel
    elif eh_dono_grupo:
        papel = "adm"

    if usuario.tipo_usuario == "adm_institucional":
        pode_chat = False
    elif vinc_esc is not None:
        pode_chat = bool(vinc_esc.pode_chat)
    else:
        pode_chat = True

    tags_str = (
        (vinc_esc.tags_areas if vinc_esc and vinc_esc.tags_areas else None)
        or (vinc_grupo.tags_areas if vinc_grupo and vinc_grupo.tags_areas else None)
        or usuario.tags_usuario
        or ""
    )
    tags_lista = [t.strip() for t in tags_str.split(",") if t.strip()]

    max_turmas = (
        contrato.max_qtd_turmas
        if contrato and contrato.max_qtd_turmas is not None
        else (plano_obj.max_turmas_por_escola if plano_obj else 2)
    )
    max_alunos = (
        contrato.max_qtd_alunos
        if contrato and contrato.max_qtd_alunos is not None
        else (plano_obj.max_alunos_por_turma if plano_obj else 2)
    )
    max_usuarios = contrato.max_qtd_user if contrato else 1

    resultado = {
        "id_escola": escola.id_escola,
        "nome_escola": escola.nome_escola,
        "id_grupo": escola.fk_Grupo_id_grupo,
        "id_contrato": contrato.id_cont if contrato else None,
        "plano": nome_plano,
        "papel": papel,
        "pode_chat": pode_chat,
        "tags_areas": tags_lista,
        "max_turmas": max_turmas,
        "max_alunos": max_alunos,
        "max_usuarios": max_usuarios,
        "tipo_usuario": usuario.tipo_usuario,
    }
    _CACHE_CONTEXTO_ESCOLA[chave] = (agora, resultado)
    return resultado


def obter_escola_padrao_usuario(sessao: Session, usuario: Usuario) -> Escola:
    """Obtém a primeira escola vinculada ao usuário (criando a estrutura inicial se necessário)."""
    vinc = sessao.execute(
        select(User_esc).where(User_esc.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().first()
    if vinc:
        esc = sessao.get(Escola, vinc.fk_Escola_id_escola)
        if esc:
            return esc

    if usuario.tipo_usuario == "normal":
        _g, esc, _c = provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()
        return esc

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Nenhuma escola vinculada a este usuário.",
    )


def criar_escola_no_grupo(
    sessao: Session, usuario: Usuario, dados: CriarEscolaRequest
) -> dict[str, Any]:
    """Cria uma nova escola respeitando as cotas dos planos Básico (3), Pro (+10) ou Institucional."""
    if usuario.tipo_usuario == "prof_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Professores institucionais não podem criar escolas.",
        )

    planos = garantir_planos_iniciais(sessao)
    planos_por_id = {p.id_plano: p for p in planos.values()}

    if dados.id_grupo:
        grupo = sessao.get(Grupo, dados.id_grupo)
    else:
        grupo = sessao.execute(
            select(Grupo).where(Grupo.fk_Usuario_id_usuario == usuario.id_usuario)
        ).scalars().first()
        if not grupo and usuario.tipo_usuario == "normal":
            grupo, _esc, _cont = provisionar_estrutura_inicial_usuario(sessao, usuario)

    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")

    if grupo.fk_Usuario_id_usuario != usuario.id_usuario:
        vinc_g = sessao.execute(
            select(User_grupo).where(
                User_grupo.fk_Usuario_id_usuario == usuario.id_usuario,
                User_grupo.fk_Grupo_id_grupo == grupo.id_grupo,
            )
        ).scalars().first()
        if not vinc_g or vinc_g.papel != "adm":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o administrador do grupo pode criar escolas.",
            )

    escolas_grupo = sessao.execute(
        select(Escola).where(Escola.fk_Grupo_id_grupo == grupo.id_grupo)
    ).scalars().all()

    contrato_grupo = (
        sessao.get(Contrato, grupo.fk_Contrato_id_cont)
        if grupo.fk_Contrato_id_cont
        else None
    )
    plano_grupo = (
        planos_por_id.get(contrato_grupo.fk_Plano_id_plano)
        if contrato_grupo
        else planos["basico"]
    )

    if plano_grupo and plano_grupo.nome_plano == "institucional":
        limite_inst = contrato_grupo.max_qtd_escolas if contrato_grupo else None
        if limite_inst is not None and len(escolas_grupo) >= limite_inst:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {limite_inst} escolas do contrato institucional atingido.",
                    "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["institucional"],
                },
            )
        nova = Escola(
            nome_escola=dados.nome_escola,
            email_institucional=grupo.email_institucional,
            fk_Grupo_id_grupo=grupo.id_grupo,
            fk_Contrato_id_cont=contrato_grupo.id_cont,
        )
        sessao.add(nova)
        sessao.flush()
        sessao.add(
            User_esc(
                fk_Usuario_id_usuario=usuario.id_usuario,
                fk_Escola_id_escola=nova.id_escola,
                papel="adm",
                pode_chat=False,
            )
        )
        sessao.commit()
        invalidar_cache_permissoes()
        return {
            "id_escola": nova.id_escola,
            "nome_escola": nova.nome_escola,
            "id_grupo": grupo.id_grupo,
            "plano": "institucional",
        }

    contratos_user = sessao.execute(
        select(Contrato)
        .join(User_cont, User_cont.fk_Contrato_id_cont == Contrato.id_cont)
        .where(
            User_cont.fk_Usuario_id_usuario == usuario.id_usuario,
            Contrato.status_contrato == "ativo",
        )
    ).scalars().all()

    contrato_basico = next(
        (c for c in contratos_user if planos_por_id[c.fk_Plano_id_plano].nome_plano == "basico"),
        None,
    )
    contrato_pro = next(
        (c for c in contratos_user if planos_por_id[c.fk_Plano_id_plano].nome_plano == "pro"),
        None,
    )

    qtd_basico = 0
    qtd_pro = 0
    for esc in escolas_grupo:
        c_esc = sessao.get(Contrato, esc.fk_Contrato_id_cont) if esc.fk_Contrato_id_cont else None
        p_nome = planos_por_id[c_esc.fk_Plano_id_plano].nome_plano if c_esc else "basico"
        if p_nome == "basico":
            qtd_basico += 1
        elif p_nome == "pro":
            qtd_pro += 1

    preferencia = (dados.usar_plano or "").lower()
    contrato_escolhido = None
    plano_escolhido_nome = None

    if preferencia == "pro":
        if not contrato_pro:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": "Você ainda não possui o plano Pro ativo.",
                    "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["pro", "pro_plus", "institucional"],
                },
            )
        limite_pro = contrato_pro.max_qtd_escolas or planos["pro"].max_escolas or 10
        if qtd_pro >= limite_pro:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {limite_pro} escolas no plano Pro atingido.",
                    "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["pro_plus", "institucional"],
                },
            )
        contrato_escolhido = contrato_pro
        plano_escolhido_nome = "pro"
    else:
        limite_basico = planos["basico"].max_escolas or 3
        if qtd_basico < limite_basico and preferencia != "pro":
            contrato_escolhido = contrato_basico or contrato_grupo
            plano_escolhido_nome = "basico"
        elif contrato_pro:
            limite_pro = contrato_pro.max_qtd_escolas or planos["pro"].max_escolas or 10
            if qtd_pro < limite_pro:
                contrato_escolhido = contrato_pro
                plano_escolhido_nome = "pro"

    if not contrato_escolhido:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "mensagem": "Limite de escolas atingido no plano atual. Melhore seu plano para adicionar mais escolas!",
                "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                "upgrade_sugerido": True,
                "opcoes_upgrade": ["pro", "pro_plus", "institucional"],
            },
        )

    nova = Escola(
        nome_escola=dados.nome_escola,
        fk_Grupo_id_grupo=grupo.id_grupo,
        fk_Contrato_id_cont=contrato_escolhido.id_cont,
    )
    sessao.add(nova)
    sessao.flush()

    sessao.add(
        User_esc(
            fk_Usuario_id_usuario=usuario.id_usuario,
            fk_Escola_id_escola=nova.id_escola,
            papel="adm",
            tags_areas=usuario.tags_usuario,
            pode_chat=True,
        )
    )
    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "id_escola": nova.id_escola,
        "nome_escola": nova.nome_escola,
        "id_grupo": grupo.id_grupo,
        "plano": plano_escolhido_nome,
    }


def contratar_ou_trocar_plano(
    sessao: Session, usuario: Usuario, dados: ContratarPlanoRequest
) -> dict[str, Any]:
    """Contrata ou faz upgrade de plano (pro, pro_plus, institucional) com CPF ou CNPJ."""
    if usuario.tipo_usuario in ("adm_institucional", "prof_institucional"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuários institucionais (adm ou professor) não podem ter outra assinatura.",
        )

    planos = garantir_planos_iniciais(sessao)
    nome_plano = (dados.nome_plano or "").strip().lower()
    if nome_plano not in planos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plano '{nome_plano}' inválido. Opções: basico, pro, pro_plus, institucional.",
        )

    tipo_cont, doc_limpo = validar_documento_contrato(dados.tipo_cont, dados.documento_cont)
    usuario.cpf_cnpj = doc_limpo
    plano_obj = planos[nome_plano]

    grupo_principal, escola_inicial, _cont_ini = provisionar_estrutura_inicial_usuario(
        sessao, usuario
    )

    id_escola_afetada = None
    id_grupo_afetado = grupo_principal.id_grupo

    if nome_plano == "pro":
        contrato = Contrato(
            tipo_cont=tipo_cont,
            documento_cont=doc_limpo,
            max_qtd_user=1,
            max_qtd_escolas=dados.max_qtd_escolas or plano_obj.max_escolas,
            max_qtd_turmas=plano_obj.max_turmas_por_escola,
            max_qtd_alunos=plano_obj.max_alunos_por_turma,
            valor_contrato=dados.valor_contrato or 49.90,
            fk_Plano_id_plano=plano_obj.id_plano,
            status_contrato="ativo",
        )
        sessao.add(contrato)
        sessao.flush()
        sessao.add(
            User_cont(
                fk_Usuario_id_usuario=usuario.id_usuario,
                fk_Contrato_id_cont=contrato.id_cont,
                eh_pagador=True,
            )
        )

        if dados.escolas_ids:
            for esc_id in dados.escolas_ids:
                esc = sessao.get(Escola, esc_id)
                if esc and esc.fk_Grupo_id_grupo == grupo_principal.id_grupo:
                    esc.fk_Contrato_id_cont = contrato.id_cont

    elif nome_plano == "pro_plus":
        contrato = Contrato(
            tipo_cont=tipo_cont,
            documento_cont=doc_limpo,
            email_institucional=dados.email_institucional,
            max_qtd_user=dados.max_qtd_user or 5,
            max_qtd_escolas=1,
            max_qtd_turmas=dados.max_qtd_turmas or 10,
            max_qtd_alunos=dados.max_qtd_alunos or 30,
            valor_contrato=dados.valor_contrato or 199.90,
            fk_Plano_id_plano=plano_obj.id_plano,
            status_contrato="ativo",
        )
        sessao.add(contrato)
        sessao.flush()
        sessao.add(
            User_cont(
                fk_Usuario_id_usuario=usuario.id_usuario,
                fk_Contrato_id_cont=contrato.id_cont,
                eh_pagador=True,
            )
        )

        pode_chat_adm = True if dados.adm_pode_chat is None else bool(dados.adm_pode_chat)
        if dados.id_escola:
            escola_pp = sessao.get(Escola, dados.id_escola)
            if not escola_pp:
                raise HTTPException(status_code=404, detail="Escola não encontrada para o Pro+.")
            escola_pp.fk_Contrato_id_cont = contrato.id_cont
            escola_pp.email_institucional = dados.email_institucional
        else:
            escola_pp = Escola(
                nome_escola=dados.nome_escola or f"Escola Pro+ de {usuario.nome_usuario}",
                email_institucional=dados.email_institucional,
                fk_Grupo_id_grupo=grupo_principal.id_grupo,
                fk_Contrato_id_cont=contrato.id_cont,
            )
            sessao.add(escola_pp)
            sessao.flush()

        id_escola_afetada = escola_pp.id_escola
        vinc_esc = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == usuario.id_usuario,
                User_esc.fk_Escola_id_escola == escola_pp.id_escola,
            )
        ).scalars().first()
        if vinc_esc:
            vinc_esc.papel = "adm"
            vinc_esc.pode_chat = pode_chat_adm
        else:
            sessao.add(
                User_esc(
                    fk_Usuario_id_usuario=usuario.id_usuario,
                    fk_Escola_id_escola=escola_pp.id_escola,
                    papel="adm",
                    tags_areas=usuario.tags_usuario,
                    pode_chat=pode_chat_adm,
                )
            )
        if usuario.tipo_usuario == "normal":
            usuario.tipo_usuario = "adm_pro_plus"

    elif nome_plano == "institucional":
        if not dados.email_institucional:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O e-mail institucional é obrigatório para configurar o plano Institucional.",
            )
        contrato = Contrato(
            tipo_cont=tipo_cont,
            documento_cont=doc_limpo,
            email_institucional=dados.email_institucional,
            max_qtd_user=dados.max_qtd_user or 50,
            max_qtd_escolas=dados.max_qtd_escolas or 20,
            max_qtd_turmas=dados.max_qtd_turmas or 20,
            max_qtd_alunos=dados.max_qtd_alunos or 40,
            valor_contrato=dados.valor_contrato or 999.90,
            fk_Plano_id_plano=plano_obj.id_plano,
            status_contrato="ativo",
        )
        sessao.add(contrato)
        sessao.flush()
        sessao.add(
            User_cont(
                fk_Usuario_id_usuario=usuario.id_usuario,
                fk_Contrato_id_cont=contrato.id_cont,
                eh_pagador=True,
            )
        )

        grupo_principal.nome_grupo = dados.nome_grupo or grupo_principal.nome_grupo
        grupo_principal.email_institucional = dados.email_institucional
        grupo_principal.fk_Contrato_id_cont = contrato.id_cont
        usuario.tipo_usuario = "adm_institucional"

        escolas_g = sessao.execute(
            select(Escola).where(Escola.fk_Grupo_id_grupo == grupo_principal.id_grupo)
        ).scalars().all()
        for esc in escolas_g:
            esc.fk_Contrato_id_cont = contrato.id_cont
            esc.email_institucional = dados.email_institucional
            ve = sessao.execute(
                select(User_esc).where(
                    User_esc.fk_Usuario_id_usuario == usuario.id_usuario,
                    User_esc.fk_Escola_id_escola == esc.id_escola,
                )
            ).scalars().first()
            if ve:
                ve.papel = "adm"
                ve.pode_chat = False

    else:
        contrato = sessao.get(Contrato, grupo_principal.fk_Contrato_id_cont)

    if contrato and contrato.valor_contrato:
        sessao.add(
            Pgto(
                data_vencimento=date.today() + timedelta(days=30),
                status_pagamento="Pago",
                fk_Contrato_id_cont=contrato.id_cont,
            )
        )
        sessao.add(
            Nota_fiscal(
                valor_nota=contrato.valor_contrato,
                data_emissao=date.today(),
                fk_Contrato_id_cont=contrato.id_cont,
            )
        )

    sessao.commit()
    invalidar_cache_permissoes()

    claims = obter_claims_jwt_usuario(sessao, usuario)
    novo_token = security.criar_access_token(
        data=claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return {
        "mensagem": f"Plano '{nome_plano}' configurado com sucesso.",
        "plano": nome_plano,
        "id_contrato": contrato.id_cont if contrato else None,
        "id_grupo": id_grupo_afetado,
        "id_escola": id_escola_afetada or escola_inicial.id_escola,
        "access_token": novo_token,
        "token_type": "bearer",
    }


def adicionar_professor_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
    dados: AdicionarProfessorRequest,
) -> dict[str, Any]:
    """Adiciona ou cria um professor em uma escola específica (Pro+ ou Institucional), aplicando tags de áreas."""
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] != "adm":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode adicionar professores.",
        )
    if ctx["plano"] not in ("pro_plus", "institucional"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas escolas dos planos Pro+ ou Institucional permitem múltiplos professores.",
        )

    professores_atuais = sessao.execute(
        select(User_esc).where(
            User_esc.fk_Escola_id_escola == id_escola,
            User_esc.papel == "professor",
        )
    ).scalars().all()

    max_users = ctx["max_usuarios"] or 1
    if len(professores_atuais) >= max_users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Limite de {max_users} professores atingido para esta escola.",
        )

    tags_str = _normalizar_tags(dados.tags_areas)
    prof = sessao.execute(
        select(Usuario).where(Usuario.email_usuario == dados.email)
    ).scalars().first()

    if not prof:
        tipo_novo = "prof_institucional" if ctx["plano"] == "institucional" else "normal"
        prof = Usuario(
            nome_usuario=dados.nome or dados.email.split("@")[0],
            email_usuario=dados.email,
            telefone_usuario=dados.telefone,
            senha_usuario=security.cria_hash_senha(dados.senha or "SenhaPadrao@123"),
            tipo_usuario=tipo_novo,
            tags_usuario=tags_str,
        )
        sessao.add(prof)
        sessao.flush()
        sessao.add(
            user2famethods(
                tipo=Tipo2FA.NONE,
                secret=None,
                usa_verificacao=False,
                data_criacao=datetime.now(timezone.utc),
                id_prof=prof.id_usuario,
            )
        )
        if tipo_novo == "normal":
            provisionar_estrutura_inicial_usuario(sessao, prof)

    vinc = sessao.execute(
        select(User_esc).where(
            User_esc.fk_Usuario_id_usuario == prof.id_usuario,
            User_esc.fk_Escola_id_escola == id_escola,
        )
    ).scalars().first()
    if vinc:
        vinc.tags_areas = tags_str
    else:
        vinc = User_esc(
            fk_Usuario_id_usuario=prof.id_usuario,
            fk_Escola_id_escola=id_escola,
            papel="professor",
            tags_areas=tags_str,
            pode_chat=True,
        )
        sessao.add(vinc)

    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "mensagem": "Professor vinculado à escola com sucesso.",
        "id_usuario": prof.id_usuario,
        "id_escola": id_escola,
        "plano_escola": ctx["plano"],
        "tags_areas": [t for t in (tags_str or "").split(",") if t],
    }


def adicionar_professor_grupo_institucional(
    sessao: Session,
    adm_logado: Usuario,
    id_grupo: int,
    dados: AdicionarProfessorRequest,
) -> dict[str, Any]:
    """Cria/vincula um professor institucional no grupo e em múltiplas escolas da rede."""
    grupo = sessao.get(Grupo, id_grupo)
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")
    if grupo.fk_Usuario_id_usuario != adm_logado.id_usuario and adm_logado.tipo_usuario != "adm_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador institucional do grupo pode gerenciar professores da rede.",
        )

    contrato = sessao.get(Contrato, grupo.fk_Contrato_id_cont) if grupo.fk_Contrato_id_cont else None
    planos_map = {p.id_plano: p.nome_plano for p in garantir_planos_iniciais(sessao).values()}
    if not contrato or planos_map.get(contrato.fk_Plano_id_plano) != "institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este grupo não possui um plano Institucional ativo.",
        )

    profs_grupo = sessao.execute(
        select(User_grupo).where(
            User_grupo.fk_Grupo_id_grupo == id_grupo,
            User_grupo.papel == "professor",
        )
    ).scalars().all()
    if contrato.max_qtd_user and len(profs_grupo) >= contrato.max_qtd_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Limite de {contrato.max_qtd_user} professores do contrato institucional atingido.",
        )

    tags_str = _normalizar_tags(dados.tags_areas)
    prof = sessao.execute(
        select(Usuario).where(Usuario.email_usuario == dados.email)
    ).scalars().first()

    if not prof:
        prof = Usuario(
            nome_usuario=dados.nome or dados.email.split("@")[0],
            email_usuario=dados.email,
            telefone_usuario=dados.telefone,
            senha_usuario=security.cria_hash_senha(dados.senha or "SenhaPadrao@123"),
            tipo_usuario="prof_institucional",
            tags_usuario=tags_str,
        )
        sessao.add(prof)
        sessao.flush()
        sessao.add(
            user2famethods(
                tipo=Tipo2FA.NONE,
                secret=None,
                usa_verificacao=False,
                data_criacao=datetime.now(timezone.utc),
                id_prof=prof.id_usuario,
            )
        )
    else:
        prof.tipo_usuario = "prof_institucional"
        if tags_str:
            prof.tags_usuario = tags_str

    vg = sessao.execute(
        select(User_grupo).where(
            User_grupo.fk_Usuario_id_usuario == prof.id_usuario,
            User_grupo.fk_Grupo_id_grupo == id_grupo,
        )
    ).scalars().first()
    if not vg:
        sessao.add(
            User_grupo(
                fk_Usuario_id_usuario=prof.id_usuario,
                fk_Grupo_id_grupo=id_grupo,
                papel="professor",
                tags_areas=tags_str,
            )
        )

    escolas_grupo = sessao.execute(
        select(Escola).where(Escola.fk_Grupo_id_grupo == id_grupo)
    ).scalars().all()
    ids_validos = {e.id_escola for e in escolas_grupo}
    escolas_alvo = (
        [eid for eid in dados.escolas_ids if eid in ids_validos]
        if dados.escolas_ids
        else list(ids_validos)
    )

    for eid in escolas_alvo:
        ve = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == prof.id_usuario,
                User_esc.fk_Escola_id_escola == eid,
            )
        ).scalars().first()
        if ve:
            ve.tags_areas = tags_str
        else:
            sessao.add(
                User_esc(
                    fk_Usuario_id_usuario=prof.id_usuario,
                    fk_Escola_id_escola=eid,
                    papel="professor",
                    tags_areas=tags_str,
                    pode_chat=True,
                )
            )

    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "mensagem": "Professor institucional adicionado com sucesso.",
        "id_usuario": prof.id_usuario,
        "tipo_usuario": prof.tipo_usuario,
        "id_grupo": id_grupo,
        "escolas_vinculadas": escolas_alvo,
        "tags_areas": [t for t in (tags_str or "").split(",") if t],
    }


def atualizar_tags_professor(
    sessao: Session,
    usuario_logado: Usuario,
    id_professor: int,
    dados: AtualizarTagsRequest,
) -> dict[str, Any]:
    """Atualiza as tags de áreas de atuação de um professor."""
    prof = sessao.get(Usuario, id_professor)
    if not prof:
        raise HTTPException(status_code=404, detail="Professor não encontrado.")

    tags_str = _normalizar_tags(dados.tags_areas)
    if dados.id_escola:
        ctx = obter_contexto_escola(sessao, usuario_logado.id_usuario, dados.id_escola)
        if ctx["papel"] != "adm" and usuario_logado.id_usuario != id_professor:
            raise HTTPException(status_code=403, detail="Sem permissão para alterar tags nesta escola.")
        ve = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == id_professor,
                User_esc.fk_Escola_id_escola == dados.id_escola,
            )
        ).scalars().first()
        if not ve:
            raise HTTPException(status_code=404, detail="Professor não vinculado a esta escola.")
        ve.tags_areas = tags_str
    else:
        if usuario_logado.id_usuario != id_professor and usuario_logado.tipo_usuario not in ("adm_pro_plus", "adm_institucional"):
            raise HTTPException(status_code=403, detail="Sem permissão para alterar tags deste professor.")
        prof.tags_usuario = tags_str

    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "mensagem": "Tags de áreas atualizadas com sucesso.",
        "id_usuario": id_professor,
        "tags_areas": [t for t in (tags_str or "").split(",") if t],
    }


def listar_escolas_usuario(sessao: Session, usuario: Usuario) -> list[dict[str, Any]]:
    """Lista todas as escolas às quais o usuário tem acesso com seus respectivos planos e papéis."""
    vincs = sessao.execute(
        select(User_esc).where(User_esc.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().all()
    resultado = []
    for v in vincs:
        ctx = obter_contexto_escola(sessao, usuario.id_usuario, v.fk_Escola_id_escola)
        resultado.append(ctx)
    return resultado
