from datetime import date, datetime, timedelta, timezone
import re
import secrets
import time
from typing import Any, Optional

from config.settings import settings
from database import (
    Aluno,
    Contrato,
    ConviteEscola,
    Escola,
    Grupo,
    Nota_fiscal,
    Pgto,
    Plano,
    Session,
    Turma,
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
    AceitarConviteEscolaRequest,
    AdicionarProfessorRequest,
    AtualizarTagsRequest,
    ContratarPlanoRequest,
    ConvidarProfessorRequest,
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

    eh_adm_sistema = usuario.tipo_usuario == "adm_sistema"
    eh_dono_grupo = bool(grupo and grupo.fk_Usuario_id_usuario == id_usuario)
    if not vinc_esc and not vinc_grupo and not eh_dono_grupo and not eh_adm_sistema:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não possui vínculo com esta escola.",
        )

    planos_por_nome = garantir_planos_iniciais(sessao)
    planos_map = {p.id_plano: p for p in planos_por_nome.values()}

    contrato = None
    if escola.fk_Contrato_id_cont:
        cand = sessao.get(Contrato, escola.fk_Contrato_id_cont)
        if cand and cand.status_contrato == "ativo":
            contrato = cand
    if not contrato and grupo and grupo.fk_Contrato_id_cont:
        cand = sessao.get(Contrato, grupo.fk_Contrato_id_cont)
        if cand and cand.status_contrato == "ativo":
            contrato = cand

    plano_obj = planos_map.get(contrato.fk_Plano_id_plano) if contrato else planos_por_nome["normal"]
    nome_plano = plano_obj.nome_plano if plano_obj else "normal"

    # No plano institucional (escola específica), o papel de adm só vale na escola em que há vínculo explícito.
    # Saindo dessa escola específica (ou sem vínculo adm nela), o usuário atua como professor.
    papel = "professor"
    if eh_adm_sistema:
        papel = "adm_sistema"
    elif usuario.tipo_usuario == "prof_institucional":
        papel = "professor"
    elif vinc_esc:
        papel = vinc_esc.papel
    elif nome_plano == "institucional_plus":
        if vinc_grupo:
            papel = vinc_grupo.papel
        elif eh_dono_grupo:
            papel = "adm"

    modo_usuario = getattr(usuario, "modo_ativo", "adm") or "adm"
    if (
        usuario.tipo_usuario in ("adm_escola", "adm_pro_plus")
        and modo_usuario == "professor"
        and nome_plano in ("institucional", "institucional_plus")
    ):
        papel = "professor"

    if usuario.tipo_usuario == "adm_institucional":
        pode_chat = False
    elif usuario.tipo_usuario in ("adm_escola", "adm_pro_plus") and modo_usuario == "professor":
        pode_chat = True
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

    if nome_plano == "pro":
        max_turmas = plano_obj.max_turmas_por_escola if plano_obj else None
        max_alunos = plano_obj.max_alunos_por_turma if plano_obj else 30
    else:
        max_turmas = (
            contrato.max_qtd_turmas
            if contrato and contrato.max_qtd_turmas is not None
            else (plano_obj.max_turmas_por_escola if plano_obj else 2)
        )
        max_alunos = (
            contrato.max_qtd_alunos
            if contrato and contrato.max_qtd_alunos is not None
            else (plano_obj.max_alunos_por_turma if plano_obj else 5)
        )
    max_usuarios = contrato.max_qtd_user if contrato else 1

    institucional_flag = nome_plano in ("institucional", "institucional_plus")
    codigo_conv = getattr(escola, "codigo_convite", None)
    if institucional_flag and not codigo_conv:
        codigo_conv = f"ESC-{secrets.token_hex(3).upper()}"
        escola.codigo_convite = codigo_conv
        sessao.commit()

    resultado = {
        "id_escola": escola.id_escola,
        "nome_escola": escola.nome_escola,
        "id_grupo": escola.fk_Grupo_id_grupo,
        "id_contrato": contrato.id_cont if contrato else None,
        "plano": nome_plano,
        "institucional": institucional_flag,
        "codigo_convite": codigo_conv if papel in ("adm", "adm_sistema") and institucional_flag else None,
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
        else planos["normal"]
    )

    if plano_grupo and plano_grupo.nome_plano == "institucional_plus":
        limite_inst = contrato_grupo.max_qtd_escolas if contrato_grupo else None
        if limite_inst is not None and len(escolas_grupo) >= limite_inst:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {limite_inst} escolas do contrato Institucional+ atingido.",
                    "codigo_erro": "LIMITE_ESCOLAS_ATINGIDO",
                    "tipo_limite": "escola",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["institucional_plus"],
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
            "plano": "institucional_plus",
        }

    contratos_user = sessao.execute(
        select(Contrato)
        .join(User_cont, User_cont.fk_Contrato_id_cont == Contrato.id_cont)
        .where(
            User_cont.fk_Usuario_id_usuario == usuario.id_usuario,
            Contrato.status_contrato == "ativo",
        )
    ).scalars().all()

    contrato_normal = next(
        (c for c in contratos_user if planos_por_id[c.fk_Plano_id_plano].nome_plano == "normal"),
        None,
    )
    contrato_pro = next(
        (c for c in contratos_user if planos_por_id[c.fk_Plano_id_plano].nome_plano == "pro"),
        None,
    )

    qtd_normal = 0
    qtd_pro = 0
    for esc in escolas_grupo:
        c_esc = sessao.get(Contrato, esc.fk_Contrato_id_cont) if esc.fk_Contrato_id_cont else None
        p_nome = planos_por_id[c_esc.fk_Plano_id_plano].nome_plano if c_esc else "normal"
        if p_nome == "normal":
            qtd_normal += 1
        elif p_nome == "pro":
            qtd_pro += 1

    preferencia = normalizar_nome_plano(dados.usar_plano or "")
    contrato_escolhido = None
    plano_escolhido_nome = None

    if preferencia == "pro":
        if not contrato_pro:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": "Você ainda não possui o plano Pro ativo.",
                    "codigo_erro": "PLANO_PRO_NAO_CONTRATADO",
                    "tipo_limite": "escola",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["pro", "institucional", "institucional_plus"],
                },
            )
        limite_pro = contrato_pro.max_qtd_escolas or planos["pro"].max_escolas or 10
        if qtd_pro >= limite_pro:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {limite_pro} escolas no plano Pro atingido.",
                    "codigo_erro": "LIMITE_ESCOLAS_ATINGIDO",
                    "tipo_limite": "escola",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["institucional", "institucional_plus"],
                },
            )
        contrato_escolhido = contrato_pro
        plano_escolhido_nome = "pro"
    else:
        limite_normal = planos["normal"].max_escolas or 3
        if qtd_normal < limite_normal and preferencia != "pro":
            contrato_escolhido = contrato_normal or contrato_grupo
            plano_escolhido_nome = "normal"
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
                "codigo_erro": "LIMITE_ESCOLAS_ATINGIDO",
                "tipo_limite": "escola",
                "upgrade_sugerido": True,
                "opcoes_upgrade": ["pro", "institucional", "institucional_plus"],
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


PLANOS_PAGOS_PRECOS: dict[str, float] = {
    "pro": 49.90,
    "institucional": 199.90,
    "institucional_plus": 999.90,
}


def normalizar_nome_plano(nome: str) -> str:
    """Normaliza variações de nome do plano para: normal, pro, institucional, institucional_plus."""
    bruto = (nome or "").strip().lower().replace("-", "_").replace(" ", "_")
    if bruto in ("normal", "free", "basico", "básico"):
        return "normal"
    if bruto in ("institucional", "pro+", "pro_+", "pro_plus", "institucional_escola", "institucional_normal"):
        return "institucional"
    if bruto in ("institucional+", "institucional_+", "institucional_plus", "institucional_rede", "rede"):
        return "institucional_plus"
    return bruto


def ativar_contrato_e_permissoes(
    sessao: Session,
    usuario: Usuario,
    contrato: Contrato,
    nome_plano: str,
    dados_ativacao: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ativa um contrato pago e aplica todas as permissões/vínculos do plano ao usuário."""
    cfg = dados_ativacao or {}
    grupo_principal, escola_inicial, _cont_ini = provisionar_estrutura_inicial_usuario(
        sessao, usuario
    )
    contrato.status_contrato = "ativo"
    contrato.data_inicio = date.today()
    contrato.data_fim = date.today() + timedelta(days=30)

    id_escola_afetada = None
    id_grupo_afetado = grupo_principal.id_grupo

    if nome_plano == "pro":
        escolas_ids = cfg.get("escolas_ids") or []
        for esc_id in escolas_ids:
            esc = sessao.get(Escola, esc_id)
            if esc and esc.fk_Grupo_id_grupo == grupo_principal.id_grupo:
                esc.fk_Contrato_id_cont = contrato.id_cont

    elif nome_plano == "institucional":
        pode_chat_adm = True if cfg.get("adm_pode_chat") is None else bool(cfg.get("adm_pode_chat"))
        email_inst = cfg.get("email_institucional")
        id_escola_cfg = cfg.get("id_escola")

        if id_escola_cfg:
            escola_inst = sessao.get(Escola, id_escola_cfg)
            if not escola_inst:
                raise HTTPException(status_code=404, detail="Escola não encontrada para o plano Institucional.")
            vinc_existente = sessao.execute(
                select(User_esc).where(
                    User_esc.fk_Usuario_id_usuario == usuario.id_usuario,
                    User_esc.fk_Escola_id_escola == escola_inst.id_escola,
                    User_esc.papel == "adm",
                )
            ).scalars().first()
            if escola_inst.fk_Grupo_id_grupo != grupo_principal.id_grupo and not vinc_existente:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Você não possui permissão de administrador sobre a escola informada.",
                )
            escola_inst.fk_Contrato_id_cont = contrato.id_cont
            escola_inst.email_institucional = email_inst
        else:
            escola_inst = Escola(
                nome_escola=cfg.get("nome_escola") or f"Escola Institucional de {usuario.nome_usuario}",
                email_institucional=email_inst,
                fk_Grupo_id_grupo=grupo_principal.id_grupo,
                fk_Contrato_id_cont=contrato.id_cont,
            )
            sessao.add(escola_inst)
            sessao.flush()

        id_escola_afetada = escola_inst.id_escola
        vinc_esc = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == usuario.id_usuario,
                User_esc.fk_Escola_id_escola == escola_inst.id_escola,
            )
        ).scalars().first()
        if vinc_esc:
            vinc_esc.papel = "adm"
            vinc_esc.pode_chat = pode_chat_adm
        else:
            sessao.add(
                User_esc(
                    fk_Usuario_id_usuario=usuario.id_usuario,
                    fk_Escola_id_escola=escola_inst.id_escola,
                    papel="adm",
                    tags_areas=usuario.tags_usuario,
                    pode_chat=pode_chat_adm,
                )
            )
        if usuario.tipo_usuario == "normal":
            usuario.tipo_usuario = "adm_escola"

    elif nome_plano == "institucional_plus":
        email_inst = cfg.get("email_institucional") or contrato.email_institucional
        grupo_principal.nome_grupo = cfg.get("nome_grupo") or grupo_principal.nome_grupo
        grupo_principal.email_institucional = email_inst
        grupo_principal.fk_Contrato_id_cont = contrato.id_cont
        usuario.tipo_usuario = "adm_institucional"

        escolas_g = sessao.execute(
            select(Escola).where(Escola.fk_Grupo_id_grupo == grupo_principal.id_grupo)
        ).scalars().all()
        for esc in escolas_g:
            esc.fk_Contrato_id_cont = contrato.id_cont
            esc.email_institucional = email_inst
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
                sessao.add(
                    User_esc(
                        fk_Usuario_id_usuario=usuario.id_usuario,
                        fk_Escola_id_escola=esc.id_escola,
                        papel="adm",
                        pode_chat=False,
                    )
                )

    return {
        "id_grupo": id_grupo_afetado,
        "id_escola": id_escola_afetada or escola_inicial.id_escola,
    }


def contratar_ou_trocar_plano(
    sessao: Session, usuario: Usuario, dados: ContratarPlanoRequest
) -> dict[str, Any]:
    """Configura plano gratuito ('normal') ou exige checkout Mercado Pago para planos pagos."""
    if usuario.tipo_usuario in ("adm_institucional", "prof_institucional"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuários institucionais (adm ou professor) não podem ter outra assinatura.",
        )

    planos = garantir_planos_iniciais(sessao)
    nome_plano = normalizar_nome_plano(dados.nome_plano)
    if nome_plano not in planos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plano '{nome_plano}' inválido. Opções: normal, pro, institucional, institucional_plus.",
        )

    if nome_plano in PLANOS_PAGOS_PRECOS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"O plano '{nome_plano}' requer pagamento via Mercado Pago. "
                "Utilize POST /pagamentos/checkout para gerar o link de pagamento."
            ),
        )

    tipo_cont, doc_limpo = validar_documento_contrato(dados.tipo_cont, dados.documento_cont)
    usuario.cpf_cnpj = doc_limpo

    grupo_principal, escola_inicial, _cont_ini = provisionar_estrutura_inicial_usuario(
        sessao, usuario
    )
    contrato = sessao.get(Contrato, grupo_principal.fk_Contrato_id_cont)
    if contrato:
        contrato.tipo_cont = tipo_cont
        contrato.documento_cont = doc_limpo

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
        "id_grupo": grupo_principal.id_grupo,
        "id_escola": escola_inicial.id_escola,
        "access_token": novo_token,
        "token_type": "bearer",
    }


def exportar_peis_zip_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
    id_turma: Optional[int] = None,
    id_aluno: Optional[int] = None,
) -> tuple[bytes, str]:
    """Gera um pacote .zip com os PEIs (.docx) da escola, de uma turma específica ou de um aluno."""
    import io
    import zipfile
    from database import ArquivoAnexo
    from services.storage import ler_bytes_registro_anexo

    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola (no modo ADM) pode baixar PEIs em lote.",
        )

    stmt_turmas = select(Turma).where(Turma.fk_Escola_id_escola == id_escola)
    if id_turma is not None:
        stmt_turmas = stmt_turmas.where(Turma.id_turma == id_turma)
    turmas_esc = sessao.execute(stmt_turmas).scalars().all()
    if id_turma is not None and not turmas_esc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turma não encontrada nesta escola.",
        )

    mapa_turmas = {t.id_turma: t.nome_turma for t in turmas_esc}
    turma_ids = list(mapa_turmas.keys())
    if not turma_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma turma encontrada para exportar PEIs.",
        )

    stmt_alunos = select(Aluno).where(Aluno.fk_Turma_id_turma.in_(turma_ids))
    if id_aluno is not None:
        stmt_alunos = stmt_alunos.where(Aluno.id_aluno == id_aluno)
    alunos_esc = sessao.execute(stmt_alunos).scalars().all()
    if id_aluno is not None and not alunos_esc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aluno não encontrado nesta escola.",
        )

    mapa_alunos = {a.id_aluno: a for a in alunos_esc}
    aluno_ids = list(mapa_alunos.keys())
    if not aluno_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum aluno encontrado para exportar PEIs.",
        )

    regs_pei = (
        sessao.execute(
            select(ArquivoAnexo)
            .where(
                ArquivoAnexo.id_aluno.in_(aluno_ids),
                ArquivoAnexo.id_conversa == "PEI",
            )
            .order_by(ArquivoAnexo.criado_em.desc())
        )
        .scalars()
        .all()
    )
    if not regs_pei:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum arquivo de PEI encontrado para os critérios selecionados.",
        )

    buf = io.BytesIO()
    adicionados = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, reg in enumerate(regs_pei, start=1):
            try:
                conteudo = ler_bytes_registro_anexo(reg)
            except HTTPException:
                continue
            al = mapa_alunos.get(reg.id_aluno)
            nome_turma = (mapa_turmas.get(al.fk_Turma_id_turma) if al else "Turma") or "Turma"
            nome_turma_seg = re.sub(r"[^A-Za-z0-9_-]", "_", nome_turma)
            nome_arq_seg = re.sub(r"[^A-Za-z0-9._-]", "_", reg.nome_arquivo or f"PEI_{reg.id_arquivo[:8]}.docx")
            caminho_zip = f"{nome_turma_seg}/{idx:02d}_{nome_arq_seg}"
            zf.writestr(caminho_zip, conteudo)
            adicionados += 1

    if adicionados == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Os arquivos de PEI não foram encontrados no armazenamento.",
        )

    if id_aluno is not None:
        nome_zip = f"PEIs_escola_{id_escola}_aluno_{id_aluno}.zip"
    elif id_turma is not None:
        nome_zip = f"PEIs_escola_{id_escola}_turma_{id_turma}.zip"
    else:
        nome_zip = f"PEIs_escola_{id_escola}.zip"
    return buf.getvalue(), nome_zip


def adicionar_professor_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
    dados: AdicionarProfessorRequest,
) -> dict[str, Any]:
    """Adiciona ou cria um professor em uma escola específica (Institucional ou Institucional+), aplicando tags de áreas."""
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode adicionar professores.",
        )
    if ctx["plano"] != "institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "A adição direta por e-mail na escola é exclusiva do plano Institucional (escola única). "
                "No plano Institucional+ (rede), adicione professores pelo grupo."
            ),
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

    senha_gerada = False
    if not prof:
        senha_inicial = dados.senha
        if not senha_inicial:
            senha_inicial = secrets.token_urlsafe(16)
            senha_gerada = True
        tipo_novo = "prof_institucional"
        prof = Usuario(
            nome_usuario=dados.nome or dados.email.split("@")[0],
            email_usuario=dados.email,
            telefone_usuario=dados.telefone,
            senha_usuario=security.cria_hash_senha(senha_inicial),
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
        "papel": "professor",
        "senha_temporaria_gerada": senha_gerada,
        "tags_areas": [t for t in (tags_str or "").split(",") if t],
    }


def _garantir_codigo_convite_escola(sessao: Session, escola: Escola) -> str:
    codigo = getattr(escola, "codigo_convite", None)
    if codigo:
        return codigo
    codigo = f"ESC-{secrets.token_hex(3).upper()}"
    escola.codigo_convite = codigo
    sessao.commit()
    invalidar_cache_permissoes()
    return codigo


def obter_codigo_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
    regenerar: bool = False,
) -> dict[str, Any]:
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode gerenciar o código de convite.",
        )
    if ctx["plano"] not in ("institucional", "institucional_plus"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O código de convite da escola é exclusivo de escolas com plano Institucional.",
        )
    escola = sessao.get(Escola, id_escola)
    if not escola:
        raise HTTPException(status_code=404, detail="Escola não encontrada.")
    if regenerar:
        escola.codigo_convite = f"ESC-{secrets.token_hex(3).upper()}"
        sessao.commit()
        invalidar_cache_permissoes()
    codigo = _garantir_codigo_convite_escola(sessao, escola)
    return {"id_escola": id_escola, "nome_escola": escola.nome_escola, "codigo_convite": codigo}


def convidar_professor_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
    dados: ConvidarProfessorRequest,
) -> dict[str, Any]:
    """Cria um convite pendente (notificação) para o e-mail informado usando o código da escola."""
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode convidar professores.",
        )
    if ctx["plano"] not in ("institucional", "institucional_plus"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Convites por código são exclusivos de escolas com plano Institucional.",
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

    escola = sessao.get(Escola, id_escola)
    if not escola:
        raise HTTPException(status_code=404, detail="Escola não encontrada.")
    codigo = _garantir_codigo_convite_escola(sessao, escola)

    email_norm = dados.email.strip().lower()
    prof = sessao.execute(
        select(Usuario).where(Usuario.email_usuario == email_norm)
    ).scalars().first()
    if prof:
        ja_vinculado = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == prof.id_usuario,
                User_esc.fk_Escola_id_escola == id_escola,
            )
        ).scalars().first()
        if ja_vinculado:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este usuário já está vinculado a esta escola.",
            )

    tags_str = _normalizar_tags(dados.tags_areas)
    existente = sessao.execute(
        select(ConviteEscola).where(
            ConviteEscola.fk_Escola_id_escola == id_escola,
            ConviteEscola.email_convidado == email_norm,
            ConviteEscola.status == "pendente",
        )
    ).scalars().first()
    if existente:
        existente.codigo_convite = codigo
        existente.tags_areas = tags_str
        existente.fk_Usuario_convidado_id = prof.id_usuario if prof else None
        convite = existente
    else:
        convite = ConviteEscola(
            fk_Escola_id_escola=id_escola,
            fk_Usuario_convidado_id=prof.id_usuario if prof else None,
            email_convidado=email_norm,
            codigo_convite=codigo,
            tags_areas=tags_str,
            status="pendente",
            criado_por_id=adm_logado.id_usuario,
        )
        sessao.add(convite)

    sessao.commit()
    sessao.refresh(convite)

    import os
    from email.message import EmailMessage
    import smtplib

    base_front = (
        (dados.link_base or "").strip()
        or os.getenv("FRONTEND_URL", "http://localhost:3000").strip()
    ).rstrip("/")
    link_convite = f"{base_front}/vincular-instituicao?convite={convite.id_convite}&escola={id_escola}"

    email_enviado = False
    if settings.MAIL_USERNAME and settings.MAIL_PASSWORD:
        msg = EmailMessage()
        msg["Subject"] = f"Convite para participar de {escola.nome_escola} - MetamorphIA"
        msg["From"] = settings.MAIL_USERNAME
        msg["To"] = email_norm
        msg.set_content(
            f"Olá!\n\n"
            f"A instituição {escola.nome_escola} convidou você (por {adm_logado.nome_usuario}) "
            f"para participar do plano Institucional na MetamorphIA.\n\n"
            f"Acesse o link abaixo para abrir o modal de vinculação e inserir o código fornecido pela escola:\n"
            f"{link_convite}\n"
        )
        try:
            with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
                server.send_message(msg)
            email_enviado = True
        except Exception as exc:
            print(f"[ConviteEscola] Falha ao enviar e-mail SMTP: {exc}")

    return {
        "mensagem": "Convite enviado com sucesso. O professor receberá o link por e-mail e a notificação para informar o código da escola.",
        "id_convite": convite.id_convite,
        "id_escola": id_escola,
        "nome_escola": escola.nome_escola,
        "email_convidado": email_norm,
        "codigo_convite": codigo,
        "link_convite": link_convite,
        "email_enviado": email_enviado,
        "status": convite.status,
    }


def obter_detalhe_convite_usuario(
    sessao: Session, usuario: Usuario, id_convite: int
) -> dict[str, Any]:
    """Retorna os dados de um convite específico para preencher o modal 'Vincular à instituição'."""
    email_u = (usuario.email_usuario or "").strip().lower()
    convite = sessao.get(ConviteEscola, id_convite)
    if not convite or (
        convite.fk_Usuario_convidado_id != usuario.id_usuario
        and convite.email_convidado != email_u
    ):
        raise HTTPException(status_code=404, detail="Convite não encontrado para o seu usuário.")
    esc = sessao.get(Escola, convite.fk_Escola_id_escola)
    adm = sessao.get(Usuario, convite.criado_por_id)
    return {
        "id_convite": convite.id_convite,
        "id_escola": convite.fk_Escola_id_escola,
        "nome_escola": esc.nome_escola if esc else f"Escola {convite.fk_Escola_id_escola}",
        "convidado_por": adm.nome_usuario if adm else "Administrador",
        "tags_areas": [t for t in (convite.tags_areas or "").split(",") if t],
        "status": convite.status,
        "criado_em": convite.criado_em.isoformat() if convite.criado_em else None,
    }


def listar_convites_escola(
    sessao: Session, adm_logado: Usuario, id_escola: int
) -> list[dict[str, Any]]:
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode listar os convites.",
        )
    convites = (
        sessao.execute(
            select(ConviteEscola)
            .where(ConviteEscola.fk_Escola_id_escola == id_escola)
            .order_by(ConviteEscola.criado_em.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id_convite": c.id_convite,
            "id_escola": c.fk_Escola_id_escola,
            "email_convidado": c.email_convidado,
            "tags_areas": [t for t in (c.tags_areas or "").split(",") if t],
            "status": c.status,
            "criado_em": c.criado_em.isoformat() if c.criado_em else None,
        }
        for c in convites
    ]


def listar_convites_pendentes_usuario(
    sessao: Session, usuario: Usuario
) -> list[dict[str, Any]]:
    """Lista notificações de convites pendentes para o usuário autenticado (sem expor o código)."""
    email_u = (usuario.email_usuario or "").strip().lower()
    convites = (
        sessao.execute(
            select(ConviteEscola)
            .where(
                ConviteEscola.status == "pendente",
                (ConviteEscola.fk_Usuario_convidado_id == usuario.id_usuario)
                | (ConviteEscola.email_convidado == email_u if email_u else False),
            )
            .order_by(ConviteEscola.criado_em.desc())
        )
        .scalars()
        .all()
    )
    saida: list[dict[str, Any]] = []
    for c in convites:
        esc = sessao.get(Escola, c.fk_Escola_id_escola)
        adm = sessao.get(Usuario, c.criado_por_id)
        saida.append(
            {
                "id_convite": c.id_convite,
                "id_escola": c.fk_Escola_id_escola,
                "nome_escola": esc.nome_escola if esc else f"Escola {c.fk_Escola_id_escola}",
                "convidado_por": adm.nome_usuario if adm else "Administrador",
                "tags_areas": [t for t in (c.tags_areas or "").split(",") if t],
                "status": c.status,
                "criado_em": c.criado_em.isoformat() if c.criado_em else None,
            }
        )
    return saida


def aceitar_convite_escola(
    sessao: Session,
    usuario: Usuario,
    dados: AceitarConviteEscolaRequest,
) -> dict[str, Any]:
    """Valida o código da escola informado pelo professor e efetiva o vínculo."""
    codigo_informado = dados.codigo_convite.strip().upper()
    email_u = (usuario.email_usuario or "").strip().lower()

    stmt = select(ConviteEscola).where(
        ConviteEscola.status == "pendente",
        (ConviteEscola.fk_Usuario_convidado_id == usuario.id_usuario)
        | (ConviteEscola.email_convidado == email_u if email_u else False),
    )
    if dados.id_convite:
        stmt = stmt.where(ConviteEscola.id_convite == dados.id_convite)
    pendentes = sessao.execute(stmt).scalars().all()
    if not pendentes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum convite pendente encontrado para o seu usuário.",
        )

    convite_match = None
    for c in pendentes:
        esc = sessao.get(Escola, c.fk_Escola_id_escola)
        codigo_real = ((esc.codigo_convite if esc else None) or c.codigo_convite or "").strip().upper()
        if codigo_real and codigo_real == codigo_informado:
            convite_match = c
            break

    if not convite_match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código da escola inválido para este convite.",
        )

    esc = sessao.get(Escola, convite_match.fk_Escola_id_escola)
    vinc = sessao.execute(
        select(User_esc).where(
            User_esc.fk_Usuario_id_usuario == usuario.id_usuario,
            User_esc.fk_Escola_id_escola == convite_match.fk_Escola_id_escola,
        )
    ).scalars().first()
    if vinc:
        if convite_match.tags_areas:
            vinc.tags_areas = convite_match.tags_areas
    else:
        sessao.add(
            User_esc(
                fk_Usuario_id_usuario=usuario.id_usuario,
                fk_Escola_id_escola=convite_match.fk_Escola_id_escola,
                papel="professor",
                tags_areas=convite_match.tags_areas or usuario.tags_usuario,
                pode_chat=True,
            )
        )

    convite_match.status = "aceito"
    convite_match.fk_Usuario_convidado_id = usuario.id_usuario
    convite_match.respondido_em = datetime.now(timezone.utc)
    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "mensagem": "Convite aceito! Você agora está vinculado à escola.",
        "id_escola": convite_match.fk_Escola_id_escola,
        "nome_escola": esc.nome_escola if esc else "",
        "papel": "professor",
    }


def recusar_convite_escola(
    sessao: Session, usuario: Usuario, id_convite: int
) -> dict[str, Any]:
    email_u = (usuario.email_usuario or "").strip().lower()
    convite = sessao.get(ConviteEscola, id_convite)
    if not convite or convite.status != "pendente" or (
        convite.fk_Usuario_convidado_id != usuario.id_usuario
        and convite.email_convidado != email_u
    ):
        raise HTTPException(status_code=404, detail="Convite pendente não encontrado.")
    convite.status = "recusado"
    convite.respondido_em = datetime.now(timezone.utc)
    sessao.commit()
    return {"mensagem": "Convite recusado.", "id_convite": id_convite, "status": "recusado"}


def adicionar_professor_grupo_institucional(
    sessao: Session,
    adm_logado: Usuario,
    id_grupo: int,
    dados: AdicionarProfessorRequest,
) -> dict[str, Any]:
    """Cria/vincula um professor institucional no grupo e em múltiplas escolas da rede (Institucional+)."""
    grupo = sessao.get(Grupo, id_grupo)
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")
    eh_adm_grupo = grupo.fk_Usuario_id_usuario == adm_logado.id_usuario
    if not eh_adm_grupo and adm_logado.tipo_usuario not in ("adm_institucional", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador institucional do grupo pode gerenciar professores da rede.",
        )

    contrato = sessao.get(Contrato, grupo.fk_Contrato_id_cont) if grupo.fk_Contrato_id_cont else None
    planos_map = {p.id_plano: p.nome_plano for p in garantir_planos_iniciais(sessao).values()}
    if not contrato or planos_map.get(contrato.fk_Plano_id_plano) != "institucional_plus":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O gerenciamento de professores em rede é exclusivo do plano Institucional+. No plano Institucional, adicione professores diretamente na escola.",
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
            detail=f"Limite de {contrato.max_qtd_user} professores do contrato Institucional+ atingido.",
        )

    tags_str = _normalizar_tags(dados.tags_areas)
    prof = sessao.execute(
        select(Usuario).where(Usuario.email_usuario == dados.email)
    ).scalars().first()

    senha_gerada = False
    if not prof:
        senha_inicial = dados.senha
        if not senha_inicial:
            senha_inicial = secrets.token_urlsafe(16)
            senha_gerada = True
        prof = Usuario(
            nome_usuario=dados.nome or dados.email.split("@")[0],
            email_usuario=dados.email,
            telefone_usuario=dados.telefone,
            senha_usuario=security.cria_hash_senha(senha_inicial),
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
        if prof.tipo_usuario == "normal":
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
        "senha_temporaria_gerada": senha_gerada,
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
        if ctx["papel"] not in ("adm", "adm_sistema") and usuario_logado.id_usuario != id_professor:
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
        if usuario_logado.id_usuario != id_professor and usuario_logado.tipo_usuario not in ("adm_escola", "adm_pro_plus", "adm_institucional", "adm_sistema"):
            raise HTTPException(status_code=403, detail="Sem permissão para alterar tags deste professor.")
        prof.tags_usuario = tags_str

    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "mensagem": "Tags de áreas atualizadas com sucesso.",
        "id_usuario": id_professor,
        "tags_areas": [t for t in (tags_str or "").split(",") if t],
    }


def listar_professores_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
) -> list[dict[str, Any]]:
    """Lista todos os professores vinculados a uma escola (exclusivo para ADM da escola ou ADM do sistema)."""
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode listar os professores.",
        )

    from database import PeiDisciplina
    from services.disciplinas import normalizar_chave_disciplina

    vincs = sessao.execute(
        select(User_esc).where(
            User_esc.fk_Escola_id_escola == id_escola,
            User_esc.papel == "professor",
        )
    ).scalars().all()

    turma_ids = [
        t.id_turma
        for t in sessao.execute(select(Turma).where(Turma.fk_Escola_id_escola == id_escola)).scalars().all()
    ]
    alunos_esc = (
        sessao.execute(select(Aluno).where(Aluno.fk_Turma_id_turma.in_(turma_ids))).scalars().all()
        if turma_ids
        else []
    )
    aluno_ids = [a.id_aluno for a in alunos_esc]
    multiplicador_alunos = max(1, len(aluno_ids))

    pei_discs = (
        sessao.execute(
            select(PeiDisciplina).where(
                PeiDisciplina.id_aluno.in_(aluno_ids),
                PeiDisciplina.status == "concluido",
            )
        )
        .scalars()
        .all()
        if aluno_ids
        else []
    )

    resultado = []
    for v in vincs:
        u = sessao.get(Usuario, v.fk_Usuario_id_usuario)
        if not u:
            continue
        tags_str = v.tags_areas or u.tags_usuario or ""
        tags_lista = [t.strip() for t in tags_str.split(",") if t.strip()]
        chaves_tags = {normalizar_chave_disciplina(t) for t in tags_lista}

        concluidos_set: set[tuple[int, str]] = set()
        datas_prof: list[datetime] = []
        for pd in pei_discs:
            chave_pd = normalizar_chave_disciplina(pd.disciplina)
            if (not chaves_tags or chave_pd in chaves_tags) and (
                pd.id_prof == u.id_usuario or chave_pd in chaves_tags
            ):
                concluidos_set.add((pd.id_aluno, chave_pd))
                if pd.atualizado_em:
                    datas_prof.append(pd.atualizado_em)

        peis_total = len(tags_lista) * multiplicador_alunos
        peis_concluidos = len(concluidos_set)
        percentual = round((peis_concluidos / peis_total) * 100) if peis_total > 0 else 0

        ultimo_envio = max(datas_prof).strftime("%d/%m/%y") if datas_prof else None
        proximo_periodo = None
        validades = [a.pei_valido_ate for a in alunos_esc if a.pei_valido_ate]
        if validades:
            dt_prox = max(validades)
            proximo_periodo = f"{dt_prox.strftime('%d/%m')} até {(dt_prox + timedelta(days=11)).strftime('%d/%m/%y')}"

        resultado.append({
            "id_usuario": u.id_usuario,
            "nome_usuario": u.nome_usuario,
            "email_usuario": u.email_usuario,
            "telefone_usuario": u.telefone_usuario,
            "tipo_usuario": u.tipo_usuario,
            "papel": v.papel,
            "pode_chat": bool(v.pode_chat),
            "tags_areas": tags_lista,
            "peis_concluidos": peis_concluidos,
            "peis_total": peis_total,
            "percentual": percentual,
            "ultimo_envio": ultimo_envio,
            "proximo_periodo": proximo_periodo,
        })
    return resultado


def obter_resumo_peis_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
) -> dict[str, Any]:
    """Retorna o consolidado de PEIs da escola (concluídos/total, datas e detalhe por professor)."""
    profs = listar_professores_escola(sessao, adm_logado, id_escola)
    turma_ids = [
        t.id_turma
        for t in sessao.execute(select(Turma).where(Turma.fk_Escola_id_escola == id_escola)).scalars().all()
    ]
    alunos_esc = (
        sessao.execute(select(Aluno).where(Aluno.fk_Turma_id_turma.in_(turma_ids))).scalars().all()
        if turma_ids
        else []
    )
    total = sum(p["peis_total"] for p in profs)
    concluidos = sum(p["peis_concluidos"] for p in profs)
    percentual = round((concluidos / total) * 100) if total > 0 else 0

    datas_ult = [p["ultimo_envio"] for p in profs if p.get("ultimo_envio")]
    ultimo_envio = datas_ult[0] if datas_ult else None
    proximo_periodo = next((p["proximo_periodo"] for p in profs if p.get("proximo_periodo")), None)
    if not proximo_periodo:
        validades = [a.pei_valido_ate for a in alunos_esc if a.pei_valido_ate]
        if validades:
            dt_prox = max(validades)
            proximo_periodo = f"{dt_prox.strftime('%d/%m')} até {(dt_prox + timedelta(days=11)).strftime('%d/%m/%y')}"

    return {
        "id_escola": id_escola,
        "concluidos": concluidos,
        "total": total,
        "percentual": percentual,
        "ultimo_envio": ultimo_envio,
        "proximo_periodo": proximo_periodo,
        "professores": profs,
    }


def remover_professor_escola(
    sessao: Session,
    adm_logado: Usuario,
    id_escola: int,
    id_professor: int,
) -> dict[str, Any]:
    """Remove o vínculo de um professor com uma escola específica."""
    ctx = obter_contexto_escola(sessao, adm_logado.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode remover professores.",
        )
    vinc = sessao.execute(
        select(User_esc).where(
            User_esc.fk_Usuario_id_usuario == id_professor,
            User_esc.fk_Escola_id_escola == id_escola,
            User_esc.papel == "professor",
        )
    ).scalars().first()
    if not vinc:
        raise HTTPException(status_code=404, detail="Professor não encontrado nesta escola.")

    sessao.delete(vinc)
    sessao.commit()
    invalidar_cache_permissoes()
    return {"mensagem": "Professor removido da escola com sucesso.", "id_usuario": id_professor, "id_escola": id_escola}


def listar_professores_grupo(
    sessao: Session,
    adm_logado: Usuario,
    id_grupo: int,
) -> list[dict[str, Any]]:
    """Lista os professores vinculados a um grupo Institucional+."""
    grupo = sessao.get(Grupo, id_grupo)
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")
    if grupo.fk_Usuario_id_usuario != adm_logado.id_usuario and adm_logado.tipo_usuario not in ("adm_institucional", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador institucional do grupo pode listar professores da rede.",
        )

    vincs = sessao.execute(
        select(User_grupo).where(
            User_grupo.fk_Grupo_id_grupo == id_grupo,
            User_grupo.papel == "professor",
        )
    ).scalars().all()
    resultado = []
    for vg in vincs:
        u = sessao.get(Usuario, vg.fk_Usuario_id_usuario)
        if not u:
            continue
        escolas_vinc = sessao.execute(
            select(User_esc.fk_Escola_id_escola)
            .join(Escola, Escola.id_escola == User_esc.fk_Escola_id_escola)
            .where(
                User_esc.fk_Usuario_id_usuario == u.id_usuario,
                Escola.fk_Grupo_id_grupo == id_grupo,
            )
        ).scalars().all()
        resultado.append({
            "id_usuario": u.id_usuario,
            "nome_usuario": u.nome_usuario,
            "email_usuario": u.email_usuario,
            "tipo_usuario": u.tipo_usuario,
            "papel": vg.papel,
            "escolas_ids": list(escolas_vinc),
            "tags_areas": [t for t in (vg.tags_areas or "").split(",") if t],
        })
    return resultado


def remover_professor_grupo(
    sessao: Session,
    adm_logado: Usuario,
    id_grupo: int,
    id_professor: int,
) -> dict[str, Any]:
    """Remove um professor do grupo Institucional+ e de todas as escolas do grupo."""
    grupo = sessao.get(Grupo, id_grupo)
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")
    if grupo.fk_Usuario_id_usuario != adm_logado.id_usuario and adm_logado.tipo_usuario not in ("adm_institucional", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador institucional do grupo pode remover professores da rede.",
        )

    vg = sessao.execute(
        select(User_grupo).where(
            User_grupo.fk_Usuario_id_usuario == id_professor,
            User_grupo.fk_Grupo_id_grupo == id_grupo,
            User_grupo.papel == "professor",
        )
    ).scalars().first()
    if not vg:
        raise HTTPException(status_code=404, detail="Professor não encontrado neste grupo.")

    escolas_grupo_ids = sessao.execute(
        select(Escola.id_escola).where(Escola.fk_Grupo_id_grupo == id_grupo)
    ).scalars().all()
    if escolas_grupo_ids:
        vincs_esc = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == id_professor,
                User_esc.fk_Escola_id_escola.in_(escolas_grupo_ids),
                User_esc.papel == "professor",
            )
        ).scalars().all()
        for ve in vincs_esc:
            sessao.delete(ve)

    sessao.delete(vg)
    sessao.commit()
    invalidar_cache_permissoes()
    return {"mensagem": "Professor removido da rede com sucesso.", "id_usuario": id_professor, "id_grupo": id_grupo}


def obter_painel_institucional(sessao: Session, usuario: Usuario) -> dict[str, Any]:
    """Retorna os dados completos da tela administrativa (Institucional ou Institucional+) para o ADM."""
    if usuario.tipo_usuario not in ("adm_institucional", "adm_escola", "adm_pro_plus", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem acessar o painel administrativo institucional.",
        )

    escolas_adm = [e for e in listar_escolas_usuario(sessao, usuario) if e.get("papel") in ("adm", "adm_sistema")]
    escolas_detalhadas = []
    for e_ctx in escolas_adm:
        id_esc = e_ctx["id_escola"]
        turmas_esc = sessao.execute(
            select(Turma).where(Turma.fk_Escola_id_escola == id_esc)
        ).scalars().all()
        turma_ids = [t.id_turma for t in turmas_esc]
        qtd_alunos = 0
        if turma_ids:
            qtd_alunos = len(
                sessao.execute(select(Aluno).where(Aluno.fk_Turma_id_turma.in_(turma_ids))).scalars().all()
            )
        resumo_peis = obter_resumo_peis_escola(sessao, usuario, id_esc)
        profs_esc = resumo_peis["professores"]
        escolas_detalhadas.append({
            **e_ctx,
            "qtd_turmas": len(turmas_esc),
            "qtd_alunos": qtd_alunos,
            "qtd_professores": len(profs_esc),
            "professores": profs_esc,
            "peis_resumo": {
                "concluidos": resumo_peis["concluidos"],
                "total": resumo_peis["total"],
                "percentual": resumo_peis["percentual"],
                "ultimo_envio": resumo_peis["ultimo_envio"],
                "proximo_periodo": resumo_peis["proximo_periodo"],
            },
        })

    grupo = sessao.execute(
        select(Grupo).where(Grupo.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().first()

    tela = "painel_adm_institucional" if usuario.tipo_usuario == "adm_institucional" else "painel_adm_escola"
    if usuario.tipo_usuario == "adm_sistema":
        tela = "painel_adm_sistema"

    return {
        "tela": tela,
        "tipo_usuario": usuario.tipo_usuario,
        "id_grupo": grupo.id_grupo if grupo else None,
        "nome_grupo": grupo.nome_grupo if grupo else None,
        "escolas": escolas_detalhadas,
    }


def listar_escolas_usuario(sessao: Session, usuario: Usuario) -> list[dict[str, Any]]:
    """Lista as escolas às quais o usuário tem acesso (no modo ADM de escola paga, oculta escolas de plano normal)."""
    vincs = sessao.execute(
        select(User_esc).where(User_esc.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().all()
    modo_ativo = getattr(usuario, "modo_ativo", "adm") or "adm"
    apenas_pagas_adm = (
        usuario.tipo_usuario in ("adm_escola", "adm_pro_plus")
        and modo_ativo != "professor"
    )
    resultado = []
    for v in vincs:
        ctx = obter_contexto_escola(sessao, usuario.id_usuario, v.fk_Escola_id_escola)
        if apenas_pagas_adm and ctx.get("plano") == "normal":
            continue
        resultado.append(ctx)
    return resultado


def editar_escola_usuario(
    sessao: Session,
    usuario: Usuario,
    id_escola: int,
    nome_escola: str,
) -> dict[str, Any]:
    """Atualiza o nome de uma escola caso o usuário seja administrador dela."""
    ctx = obter_contexto_escola(sessao, usuario.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode editá-la.",
        )
    escola = sessao.get(Escola, id_escola)
    if not escola:
        raise HTTPException(status_code=404, detail="Escola não encontrada.")
    escola.nome_escola = nome_escola.strip()
    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "id_escola": escola.id_escola,
        "nome_escola": escola.nome_escola,
        "id_grupo": escola.fk_Grupo_id_grupo,
        "plano": ctx["plano"],
    }


def deletar_escola_usuario(
    sessao: Session,
    usuario: Usuario,
    id_escola: int,
) -> dict[str, Any]:
    """Remove uma escola e suas turmas, alunos, conversas e vínculos em cascata."""
    from database import conversas, delete, mensagem_al, mensagens

    ctx = obter_contexto_escola(sessao, usuario.id_usuario, id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode excluí-la.",
        )
    escola = sessao.get(Escola, id_escola)
    if not escola:
        raise HTTPException(status_code=404, detail="Escola não encontrada.")

    turmas_esc = sessao.execute(
        select(Turma).where(Turma.fk_Escola_id_escola == id_escola)
    ).scalars().all()
    turma_ids = [t.id_turma for t in turmas_esc]
    if turma_ids:
        alunos_esc = sessao.execute(
            select(Aluno).where(Aluno.fk_Turma_id_turma.in_(turma_ids))
        ).scalars().all()
        aluno_ids = [a.id_aluno for a in alunos_esc]
        if aluno_ids:
            sessao.execute(delete(mensagem_al).where(mensagem_al.c.id_aluno.in_(aluno_ids)))
            sessao.execute(delete(mensagens).where(mensagens.fk_Aluno_id_aluno.in_(aluno_ids)))
            sessao.execute(delete(conversas).where(conversas.fk_Aluno_id_aluno.in_(aluno_ids)))
            sessao.execute(delete(Aluno).where(Aluno.id_aluno.in_(aluno_ids)))
        sessao.execute(delete(Turma).where(Turma.id_turma.in_(turma_ids)))

    sessao.execute(delete(User_esc).where(User_esc.fk_Escola_id_escola == id_escola))
    sessao.delete(escola)
    sessao.commit()
    invalidar_cache_permissoes()
    return {"mensagem": "Escola removida com sucesso.", "id_escola": id_escola}


LIMITES_USO_IA_POR_PLANO: dict[str, dict[str, Optional[int]]] = {
    "normal": {"adaptacao_mes": 10, "pei": None},
    "pro": {"adaptacao_mes": 120, "pei": 120},
    "institucional": {"adaptacao_mes": None, "pei": None},
    "institucional_plus": {"adaptacao_mes": None, "pei": None},
}


def validar_e_registrar_cota_ia(
    sessao: Session,
    usuario: Usuario,
    tipo: str,
) -> None:
    """Valida limites de adaptações com IA/mês e PEIs do plano do usuário e registra o uso."""
    from datetime import datetime, timezone
    from sqlalchemy import func
    from database import UsoIA
    from services.users import obter_claims_jwt_usuario

    claims = obter_claims_jwt_usuario(sessao, usuario)
    plano = claims.get("plano") or "normal"
    cfg = LIMITES_USO_IA_POR_PLANO.get(plano, LIMITES_USO_IA_POR_PLANO["normal"])

    if tipo == "adaptacao":
        limite = cfg["adaptacao_mes"]
        if limite is not None:
            inicio_mes = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            qtd = sessao.execute(
                select(func.count(UsoIA.id)).where(
                    UsoIA.id_prof == usuario.id_usuario,
                    UsoIA.tipo == "adaptacao",
                    UsoIA.criado_em >= inicio_mes,
                )
            ).scalar_one()
            if qtd >= limite:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "mensagem": f"Limite mensal de {limite} adaptações com IA atingido no plano '{plano}'.",
                        "codigo_erro": "LIMITE_ADAPTACOES_ATINGIDO",
                        "tipo_limite": "adaptacao",
                        "upgrade_sugerido": True,
                        "opcoes_upgrade": (
                            ["pro", "institucional", "institucional_plus"]
                            if plano == "normal"
                            else ["institucional", "institucional_plus"]
                        ),
                    },
                )
    elif tipo == "pei":
        limite = cfg["pei"]
        if limite is not None:
            qtd = sessao.execute(
                select(func.count(UsoIA.id)).where(
                    UsoIA.id_prof == usuario.id_usuario,
                    UsoIA.tipo == "pei",
                )
            ).scalar_one()
            if qtd >= limite:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "mensagem": f"Limite de {limite} PEIs atingido no plano '{plano}'.",
                        "codigo_erro": "LIMITE_PEIS_ATINGIDO",
                        "tipo_limite": "pei",
                        "upgrade_sugerido": True,
                        "opcoes_upgrade": ["institucional", "institucional_plus"],
                    },
                )
    else:
        return

    sessao.add(UsoIA(id_prof=usuario.id_usuario, tipo=tipo))
    sessao.commit()
