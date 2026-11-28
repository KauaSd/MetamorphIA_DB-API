from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any, Optional
import uuid

from config.settings import DUMMY_HASH, settings
from database import (
    Aluno,
    Contrato,
    Escola,
    Grupo,
    IntegrityError,
    Mensagem,
    Nota_fiscal,
    OperationalError,
    PasswordResetCode,
    Pgto,
    Plano,
    RefreshToken,
    Session,
    Turma,
    User_cont,
    User_esc,
    User_grupo,
    Usuario,
    alunos,
    chat,
    delete,
    garantir_planos_iniciais,
    mensagem_al,
    professores,
    select,
    turmas,
)
import dependencies
from fastapi import HTTPException, status
import jwt
from schemas.schemas import (
    GoogleAuthRequest,
    LoginForm,
    MicrosoftAuthRequest,
    Professor,
    Professoredita,
    Token,
)
import security


def _normalizar_tags(tags: Optional[list[str] | str]) -> Optional[str]:
    if tags is None:
        return None
    if isinstance(tags, list):
        return ",".join(t.strip() for t in tags if t and t.strip())
    return ",".join(t.strip() for t in str(tags).split(",") if t.strip())


def _limpar_documento(doc: Optional[str]) -> Optional[str]:
    if not doc:
        return None
    return re.sub(r"\D", "", doc)


def provisionar_estrutura_inicial_usuario(
    sessao: Session,
    usuario: Usuario,
    nome_escola_inicial: Optional[str] = None,
) -> tuple[Grupo, Escola, Contrato]:
    """Garante que todo usuário normal tenha desde o início 1 Grupo, 1 Contrato Normal (free) e 1 Escola Normal."""
    planos = garantir_planos_iniciais(sessao)
    plano_normal = planos["normal"]

    grupo_existente = sessao.execute(
        select(Grupo).where(Grupo.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().first()
    if grupo_existente:
        escola_existente = sessao.execute(
            select(Escola).where(Escola.fk_Grupo_id_grupo == grupo_existente.id_grupo)
        ).scalars().first()
        contrato_existente = (
            sessao.get(Contrato, grupo_existente.fk_Contrato_id_cont)
            if grupo_existente.fk_Contrato_id_cont
            else None
        )
        if escola_existente and contrato_existente:
            return grupo_existente, escola_existente, contrato_existente

    doc = _limpar_documento(usuario.cpf_cnpj)
    tipo_cont = "cnpj" if doc and len(doc) == 14 else "cpf"

    contrato = Contrato(
        tipo_cont=tipo_cont,
        documento_cont=doc,
        max_qtd_user=1,
        max_qtd_turmas=plano_normal.max_turmas_por_escola,
        max_qtd_alunos=plano_normal.max_alunos_por_turma,
        max_qtd_escolas=plano_normal.max_escolas,
        fk_Plano_id_plano=plano_normal.id_plano,
        status_contrato="ativo",
    )
    sessao.add(contrato)
    sessao.flush()

    vinculo_cont = User_cont(
        fk_Usuario_id_usuario=usuario.id_usuario,
        fk_Contrato_id_cont=contrato.id_cont,
        eh_pagador=True,
    )
    sessao.add(vinculo_cont)

    grupo = Grupo(
        nome_grupo=f"Grupo {usuario.nome_usuario}",
        fk_Usuario_id_usuario=usuario.id_usuario,
        fk_Contrato_id_cont=contrato.id_cont,
    )
    sessao.add(grupo)
    sessao.flush()

    vinculo_grupo = User_grupo(
        fk_Usuario_id_usuario=usuario.id_usuario,
        fk_Grupo_id_grupo=grupo.id_grupo,
        papel="adm",
        tags_areas=usuario.tags_usuario,
    )
    sessao.add(vinculo_grupo)

    escola = Escola(
        nome_escola=nome_escola_inicial or f"Escola Inicial - {usuario.nome_usuario}",
        fk_Grupo_id_grupo=grupo.id_grupo,
        fk_Contrato_id_cont=contrato.id_cont,
    )
    sessao.add(escola)
    sessao.flush()

    vinculo_esc = User_esc(
        fk_Usuario_id_usuario=usuario.id_usuario,
        fk_Escola_id_escola=escola.id_escola,
        papel="adm",
        tags_areas=usuario.tags_usuario,
        pode_chat=True,
    )
    sessao.add(vinculo_esc)
    sessao.flush()

    return grupo, escola, contrato


def resolver_perfil_e_tela(sessao: Session, usuario: Usuario) -> dict[str, Any]:
    """Determina o perfil de acesso (professor, admin_escola, admin_rede, admin_sistema) e a tela inicial."""
    tipo = usuario.tipo_usuario or "normal"
    modo_ativo = getattr(usuario, "modo_ativo", "adm") or "adm"
    escola_adm_id: Optional[int] = None

    if tipo == "adm_sistema":
        return {
            "perfil": "admin_sistema",
            "tela_inicial": "painel_adm_sistema",
            "escola_adm_id": None,
        }
    if tipo == "adm_institucional":
        return {
            "perfil": "admin_rede",
            "tela_inicial": "painel_adm_institucional",
            "escola_adm_id": None,
        }
    if tipo in ("adm_escola", "adm_pro_plus"):
        planos_map = {p.id_plano: p.nome_plano for p in garantir_planos_iniciais(sessao).values()}
        vinc_escs = sessao.execute(
            select(User_esc).where(
                User_esc.fk_Usuario_id_usuario == usuario.id_usuario,
                User_esc.papel == "adm",
            )
        ).scalars().all()
        for ve in vinc_escs:
            esc = sessao.get(Escola, ve.fk_Escola_id_escola)
            if esc and esc.fk_Contrato_id_cont:
                cont = sessao.get(Contrato, esc.fk_Contrato_id_cont)
                if cont and cont.status_contrato == "ativo" and planos_map.get(cont.fk_Plano_id_plano) == "institucional":
                    escola_adm_id = esc.id_escola
                    break
        if escola_adm_id is None and vinc_escs:
            escola_adm_id = vinc_escs[0].fk_Escola_id_escola
        if modo_ativo == "professor":
            return {
                "perfil": "professor",
                "tela_inicial": "painel_professor",
                "escola_adm_id": escola_adm_id,
            }
        return {
            "perfil": "admin_escola",
            "tela_inicial": "painel_adm_escola",
            "escola_adm_id": escola_adm_id,
        }

    return {
        "perfil": "professor",
        "tela_inicial": "painel_professor",
        "escola_adm_id": None,
    }


def obter_claims_jwt_usuario(sessao: Session, usuario: Usuario) -> dict[str, Any]:
    """Monta as claims padronizadas do JWT com o plano ativo, tipo_usuario, perfil, tela_inicial e grupo."""
    planos_map = {p.id_plano: p.nome_plano for p in garantir_planos_iniciais(sessao).values()}

    # Busca grupo onde o usuário é dono ou membro
    grupo = sessao.execute(
        select(Grupo).where(Grupo.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().first()
    if not grupo:
        vinc_g = sessao.execute(
            select(User_grupo).where(User_grupo.fk_Usuario_id_usuario == usuario.id_usuario)
        ).scalars().first()
        if vinc_g:
            grupo = sessao.get(Grupo, vinc_g.fk_Grupo_id_grupo)

    # Determina o maior/principal plano ativo do usuário
    contratos_usuario = sessao.execute(
        select(Contrato)
        .join(User_cont, User_cont.fk_Contrato_id_cont == Contrato.id_cont)
        .where(
            User_cont.fk_Usuario_id_usuario == usuario.id_usuario,
            Contrato.status_contrato == "ativo",
        )
    ).scalars().all()

    nomes_planos = [planos_map.get(c.fk_Plano_id_plano, "normal") for c in contratos_usuario]
    if grupo and grupo.fk_Contrato_id_cont:
        cont_grupo = sessao.get(Contrato, grupo.fk_Contrato_id_cont)
        if cont_grupo and cont_grupo.status_contrato == "ativo":
            nomes_planos.append(planos_map.get(cont_grupo.fk_Plano_id_plano, "normal"))

    vinc_escs = sessao.execute(
        select(User_esc).where(User_esc.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().all()
    for ve in vinc_escs:
        esc = sessao.get(Escola, ve.fk_Escola_id_escola)
        if esc and esc.fk_Contrato_id_cont:
            cont_esc = sessao.get(Contrato, esc.fk_Contrato_id_cont)
            if cont_esc and cont_esc.status_contrato == "ativo":
                nomes_planos.append(planos_map.get(cont_esc.fk_Plano_id_plano, "normal"))

    prioridade = {"institucional_plus": 4, "institucional": 3, "pro": 2, "normal": 1}
    plano_principal = "normal"
    for np in nomes_planos:
        if prioridade.get(np, 0) > prioridade.get(plano_principal, 0):
            plano_principal = np

    if usuario.tipo_usuario == "adm_institucional" and plano_principal == "normal":
        plano_principal = "institucional_plus"
    elif usuario.tipo_usuario in ("adm_escola", "adm_pro_plus") and plano_principal == "normal":
        plano_principal = "institucional"
    elif usuario.tipo_usuario == "prof_institucional" and plano_principal == "normal":
        plano_principal = "institucional"

    pode_chat = True
    modo_ativo = getattr(usuario, "modo_ativo", "adm") or "adm"
    if usuario.tipo_usuario == "adm_institucional":
        pode_chat = False
    elif usuario.tipo_usuario in ("adm_escola", "adm_pro_plus") and modo_ativo == "professor":
        pode_chat = True
    elif vinc_escs and all(not v.pode_chat for v in vinc_escs):
        pode_chat = False

    tags_lista = [t for t in (usuario.tags_usuario or "").split(",") if t]
    perfil_info = resolver_perfil_e_tela(sessao, usuario)

    return {
        "sub": str(usuario.id_usuario),
        "id_prof": usuario.id_usuario,
        "email": usuario.email_usuario,
        "tipo_usuario": usuario.tipo_usuario,
        "modo_ativo": modo_ativo,
        "perfil": perfil_info["perfil"],
        "tela_inicial": perfil_info["tela_inicial"],
        "escola_adm_id": perfil_info["escola_adm_id"],
        "plano": plano_principal,
        "id_grupo": grupo.id_grupo if grupo else None,
        "pode_chat": pode_chat,
        "tags": tags_lista,
        "is_verified": True,
        "purpose": "access",
        "tv": int(getattr(usuario, "token_version", None) or 1),
    }


def emitir_par_tokens(sessao: Session, usuario: Usuario) -> Token:
    """Emite access_token curto e refresh_token longo (com rotação e token_version)."""
    claims = obter_claims_jwt_usuario(sessao, usuario)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.criar_access_token(
        data=claims,
        expires_delta=access_token_expires,
    )

    jti = str(uuid.uuid4())
    refresh_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    expira_em = datetime.now(timezone.utc) + refresh_expires
    tv = int(getattr(usuario, "token_version", None) or 1)
    refresh_token = security.criar_access_token(
        data={
            "sub": str(usuario.id_usuario),
            "jti": jti,
            "tv": tv,
            "purpose": "refresh",
        },
        expires_delta=refresh_expires,
    )
    sessao.add(
        RefreshToken(
            jti=jti,
            id_prof=usuario.id_usuario,
            token_version=tv,
            expira_em=expira_em,
            revogado=False,
        )
    )
    sessao.commit()
    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=refresh_token,
    )


def renovar_tokens_por_refresh(sessao: Session, refresh_token_raw: Optional[str]) -> Token:
    """Valida o refresh_token, aplica rotação (revoga o anterior) e emite novo par de tokens."""
    if not refresh_token_raw or not refresh_token_raw.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token não fornecido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = security.decodificar_jwt_padrao(refresh_token_raw.strip())
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("purpose") != "refresh" or not payload.get("sub") or not payload.get("jti"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido para renovação.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    usuario = sessao.get(Usuario, int(payload["sub"]))
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    versao_atual = int(getattr(usuario, "token_version", None) or 1)
    if int(payload.get("tv", -1)) != versao_atual:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão revogada. Faça login novamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    reg_rt = sessao.get(RefreshToken, str(payload["jti"]))
    if not reg_rt or reg_rt.id_prof != usuario.id_usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token desconhecido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if reg_rt.revogado:
        # Detecção de reuso de refresh token rotacionado: invalida todas as sessões
        usuario.token_version = versao_atual + 1
        sessao.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token já utilizado. Todas as sessões foram revogadas por segurança.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expira_em = reg_rt.expira_em
    if expira_em.tzinfo is None:
        expira_em = expira_em.replace(tzinfo=timezone.utc)
    if expira_em <= datetime.now(timezone.utc):
        reg_rt.revogado = True
        sessao.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    reg_rt.revogado = True
    return emitir_par_tokens(sessao, usuario)


def obter_perfil_completo_usuario(sessao: Session, usuario: Usuario) -> dict[str, Any]:
    """Retorna perfil completo, tela recomendada e permissões por escola para o frontend."""
    from services.planos import listar_convites_pendentes_usuario, listar_escolas_usuario

    claims = obter_claims_jwt_usuario(sessao, usuario)
    escolas = listar_escolas_usuario(sessao, usuario)
    convites_pendentes = listar_convites_pendentes_usuario(sessao, usuario)
    eh_adm_sistema = usuario.tipo_usuario == "adm_sistema"
    eh_adm_rede = usuario.tipo_usuario == "adm_institucional"
    modo_ativo = getattr(usuario, "modo_ativo", "adm") or "adm"
    eh_adm_escola_ativo = usuario.tipo_usuario in ("adm_escola", "adm_pro_plus") and modo_ativo != "professor"
    eh_adm_alguma_escola = any(e.get("papel") == "adm" for e in escolas)
    escola_institucional = any(bool(e.get("institucional")) for e in escolas) or usuario.tipo_usuario in (
        "adm_institucional",
        "prof_institucional",
        "adm_pro_plus",
    )

    atualizado_em = getattr(usuario, "nome_real_atualizado_em", None)
    dias_restantes_nome_real = 0
    if atualizado_em is not None:
        if atualizado_em.tzinfo is None:
            atualizado_em = atualizado_em.replace(tzinfo=timezone.utc)
        decorrido = datetime.now(timezone.utc) - atualizado_em
        if decorrido < timedelta(days=30):
            dias_restantes_nome_real = max(1, 30 - decorrido.days)

    return {
        "id_usuario": usuario.id_usuario,
        "nome_usuario": usuario.nome_usuario,
        "nome_real": getattr(usuario, "nome_real", None),
        "nome_real_atualizado_em": atualizado_em.isoformat() if atualizado_em else None,
        "dias_para_trocar_nome_real": dias_restantes_nome_real,
        "email_usuario": usuario.email_usuario,
        "telefone_usuario": usuario.telefone_usuario,
        "tipo_usuario": usuario.tipo_usuario,
        "modo_ativo": modo_ativo,
        "perfil_professor_feito": bool(getattr(usuario, "identificacao_feita", False) or getattr(usuario, "perfil_professor_feito", False)),
        "identificacao_feita": bool(getattr(usuario, "identificacao_feita", False)),
        "tutorial_visto": bool(getattr(usuario, "tutorial_visto", False)),
        "tutorial_institucional_visto": bool(getattr(usuario, "tutorial_institucional_visto", False)),
        "escola_institucional": escola_institucional,
        "instrucoes_ia": getattr(usuario, "instrucoes_ia", None) or "",
        "perfil": claims["perfil"],
        "tela_inicial": claims["tela_inicial"],
        "escola_adm_id": claims["escola_adm_id"],
        "plano": claims["plano"],
        "id_grupo": claims["id_grupo"],
        "pode_chat": claims["pode_chat"],
        "tags": claims["tags"],
        "escolas": escolas,
        "convites_pendentes": convites_pendentes,
        "permissoes": {
            "eh_admin_sistema": eh_adm_sistema,
            "eh_admin_rede": eh_adm_rede,
            "pode_alternar_modo_professor": (
                usuario.tipo_usuario in ("adm_escola", "adm_pro_plus")
                and bool(claims["pode_chat"])
            ),
            "pode_acessar_painel_adm": eh_adm_sistema or eh_adm_rede or eh_adm_escola_ativo,
            "pode_gerenciar_professores": eh_adm_rede or eh_adm_escola_ativo,
            "pode_gerenciar_alunos": eh_adm_sistema or eh_adm_rede or eh_adm_alguma_escola,
            "pode_gerenciar_turmas": eh_adm_sistema or eh_adm_rede or eh_adm_alguma_escola,
            "pode_criar_escolas": eh_adm_rede or usuario.tipo_usuario in ("normal", "adm_escola"),
            "pode_chat": claims["pode_chat"],
        },
    }


def alternar_modo_usuario(
    sessao: Session,
    usuario_logado: Usuario,
    modo_desejado: Optional[str] = None,
) -> dict[str, Any]:
    """Permite ao ADM de escola institucional (não-rede) alternar entre modo 'adm' e 'professor'."""
    from services.planos import invalidar_cache_permissoes

    usuario = sessao.get(Usuario, usuario_logado.id_usuario)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if usuario.tipo_usuario not in ("adm_escola", "adm_pro_plus"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola (Institucional) pode alternar para o modo professor.",
        )

    vinc_escs = sessao.execute(
        select(User_esc).where(User_esc.fk_Usuario_id_usuario == usuario.id_usuario)
    ).scalars().all()
    if vinc_escs and all(not v.pode_chat for v in vinc_escs):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este perfil foi configurado apenas como administrador e não possui acesso ao modo Professor.",
        )

    modo_atual = getattr(usuario, "modo_ativo", "adm") or "adm"
    if modo_desejado is None or not str(modo_desejado).strip():
        novo_modo = "professor" if modo_atual != "professor" else "adm"
    else:
        novo_modo = str(modo_desejado).strip().lower()
        if novo_modo not in ("adm", "professor"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Modo inválido. Utilize 'adm' ou 'professor'.",
            )

    usuario.modo_ativo = novo_modo
    sessao.commit()
    sessao.refresh(usuario)
    invalidar_cache_permissoes()

    claims = obter_claims_jwt_usuario(sessao, usuario)
    novo_token = security.criar_access_token(
        data=claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    perfil = obter_perfil_completo_usuario(sessao, usuario)
    return {
        "mensagem": f"Modo alterado para '{novo_modo}' com sucesso.",
        "modo_ativo": novo_modo,
        "access_token": novo_token,
        "token_type": "bearer",
        "perfil": perfil,
    }


def cria_prof(sessao: Session, dados: Professor) -> dict[str, Any]:
    try:
        doc_limpo = _limpar_documento(dados.cpf_cnpj)
        tags_str = _normalizar_tags(dados.tags)

        nome_limpo = dados.nomeProf.strip()
        professor = professores(
            email_prof=dados.emailprof,
            num_prof=dados.numprof,
            nome_prof=nome_limpo,
            nome_real=nome_limpo,
            nome_real_atualizado_em=datetime.now(timezone.utc),
            perfil_professor_feito=True,
            senha_prof=security.cria_hash_senha(dados.senhaProf),
            cpf_cnpj=doc_limpo,
            tipo_usuario="normal",
            tags_usuario=tags_str,
        )
        sessao.add(professor)
        sessao.flush()

        grupo, escola, _contrato = provisionar_estrutura_inicial_usuario(
            sessao, professor, nome_escola_inicial=dados.nome_escola_inicial
        )

        sessao.commit()
        sessao.refresh(professor)
        return {
            "mensagem": "Professor cadastrado",
            "id_usuario": professor.id_usuario,
            "id_grupo": grupo.id_grupo,
            "id_escola_inicial": escola.id_escola,
            "plano": "normal",
        }
    except IntegrityError as e:
        sessao.rollback()
        print(f"[Users] IntegrityError em cria_prof: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este professor já está cadastrado ou dados obrigatórios estão ausentes.",
        )
    except OperationalError as e:
        sessao.rollback()
        print(f"[Users] OperationalError em cria_prof: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados temporariamente indisponível.",
        )
    except Exception as e:
        sessao.rollback()
        print(f"[Users] Erro interno em cria_prof: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar cadastro.",
        )


def autenticar_prof(sessao: Session, dados: LoginForm):
    usuario = dependencies.pegar_usuario_por_indentificador(sessao, dados.indentificador)
    if not usuario or not usuario.senha_prof:
        security.verifica_senha(dados.senhaProf, DUMMY_HASH)
        return False
    if not security.verifica_senha(dados.senhaProf, usuario.senha_prof):
        return False
    return usuario


def logarProfessor(
    dados: LoginForm,
    sessao: Session,
) -> Token:
    try:
        usuario = autenticar_prof(sessao, dados)
    except OperationalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro: Banco de dados indisponivel",
        )
    except Exception as e:
        print(f"ERRO: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro interno"
        )

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorreta",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if usuario.tipo_usuario == "normal":
        provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()

    return emitir_par_tokens(sessao, usuario)


def logar_com_google(dados: GoogleAuthRequest, sessao: Session) -> Token:
    """Autentica ou cadastra usuário via conta Google validando criptograficamente o id_token."""
    if not dados.id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O id_token assinado pelo Google é obrigatório para autenticação OAuth.",
        )

    google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    try:
        if google_client_id:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            info = google_id_token.verify_oauth2_token(
                dados.id_token, google_requests.Request(), google_client_id
            )
        elif settings.ENVIRONMENT in ("test", "testing", "development", "dev"):
            # Em ambiente de teste local sem GOOGLE_CLIENT_ID externo, exige assinatura com SECRET_KEY local
            info = jwt.decode(
                dados.id_token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GOOGLE_CLIENT_ID não configurado no servidor.",
            )
        email = info.get("email")
        nome = info.get("name") or info.get("given_name") or dados.nome
        google_id = info.get("sub")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token Google inválido ou não verificado.",
        ) from exc

    if not email and not google_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O id_token não contém identificadores válidos (sub/email).",
        )

    usuario = None
    if google_id:
        usuario = sessao.execute(
            select(Usuario).where(Usuario.google_id == google_id)
        ).scalars().first()
    if not usuario and email:
        usuario = sessao.execute(
            select(Usuario).where(Usuario.email_usuario == email)
        ).scalars().first()

    if not usuario:
        usuario = Usuario(
            nome_usuario=nome or (email.split("@")[0] if email else "Professor Google"),
            email_usuario=email,
            google_id=google_id,
            tipo_usuario="normal",
        )
        sessao.add(usuario)
        sessao.flush()

        provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()
        sessao.refresh(usuario)
    else:
        if google_id and not usuario.google_id:
            usuario.google_id = google_id
        if usuario.tipo_usuario == "normal":
            provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()

    return emitir_par_tokens(sessao, usuario)


def logar_com_microsoft(dados: MicrosoftAuthRequest, sessao: Session) -> Token:
    """Autentica ou cadastra usuário via conta Microsoft OAuth (id_token ou access_token)."""
    if not dados.id_token and not dados.access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O id_token ou access_token da Microsoft é obrigatório para autenticação OAuth.",
        )

    ms_client_id = (os.getenv("MICROSOFT_CLIENT_ID") or "").strip()
    try:
        if dados.access_token and (ms_client_id or settings.ENVIRONMENT == "production"):
            import httpx

            resp = httpx.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {dados.access_token}"},
                timeout=10.0,
            )
            if not resp.is_success:
                raise ValueError("Access token Microsoft rejeitado pelo Graph API.")
            graph_info = resp.json()
            email = graph_info.get("mail") or graph_info.get("userPrincipalName")
            nome = graph_info.get("displayName") or dados.nome
            microsoft_id = graph_info.get("id")
        elif ms_client_id and dados.id_token:
            jwks_client = jwt.PyJWKClient("https://login.microsoftonline.com/common/discovery/v2.0/keys")
            signing_key = jwks_client.get_signing_key_from_jwt(dados.id_token)
            info = jwt.decode(
                dados.id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=ms_client_id,
                options={"verify_iss": False},
            )
            email = info.get("email") or info.get("preferred_username") or info.get("upn")
            nome = info.get("name") or info.get("given_name") or dados.nome
            microsoft_id = info.get("oid") or info.get("sub")
        elif settings.ENVIRONMENT in ("test", "testing", "development", "dev"):
            token_raw = dados.id_token or dados.access_token or ""
            info = jwt.decode(
                token_raw,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )
            email = info.get("email") or info.get("preferred_username") or info.get("upn")
            nome = info.get("name") or info.get("given_name") or dados.nome
            microsoft_id = info.get("oid") or info.get("sub")
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MICROSOFT_CLIENT_ID não configurado no servidor.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token Microsoft inválido ou não verificado.",
        ) from exc

    if not email and not microsoft_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O token Microsoft não contém identificadores válidos (oid/sub/email).",
        )

    usuario = None
    if microsoft_id:
        usuario = sessao.execute(
            select(Usuario).where(Usuario.microsoft_id == microsoft_id)
        ).scalars().first()
    if not usuario and email:
        usuario = sessao.execute(
            select(Usuario).where(Usuario.email_usuario == email.strip().lower())
        ).scalars().first()

    if not usuario:
        usuario = Usuario(
            nome_usuario=nome or (email.split("@")[0] if email else "Professor Microsoft"),
            email_usuario=email.strip().lower() if email else None,
            microsoft_id=microsoft_id,
            tipo_usuario="normal",
        )
        sessao.add(usuario)
        sessao.flush()

        provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()
        sessao.refresh(usuario)
    else:
        if microsoft_id and not usuario.microsoft_id:
            usuario.microsoft_id = microsoft_id
        if usuario.tipo_usuario == "normal":
            provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()

    return emitir_par_tokens(sessao, usuario)


def deletaProfessor(
    sessao: Session,
    id_prof: int,
    professor_logado: int,
):
    try:
        professor = sessao.get(professores, id_prof)
        if not professor:
            raise HTTPException(status_code=404, detail="professor não encontrado")
        if professor.id_prof != professor_logado:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para apagar este professor",
            )

        alunos_ids = sessao.execute(
            select(alunos.id_aluno).where(alunos.id_prof == id_prof)
        ).scalars().all()
        msgs_ids = sessao.execute(
            select(Mensagem.id_mensagem).where(
                (Mensagem.fk_Usuario_id_usuario == id_prof)
                | (Mensagem.fk_Aluno_id_aluno.in_(alunos_ids) if alunos_ids else False)
            )
        ).scalars().all()
        if msgs_ids:
            sessao.execute(delete(mensagem_al).where(mensagem_al.c.id_mensagem.in_(msgs_ids)))
            sessao.execute(delete(Mensagem).where(Mensagem.id_mensagem.in_(msgs_ids)))
        if alunos_ids:
            sessao.execute(delete(mensagem_al).where(mensagem_al.c.id_aluno.in_(alunos_ids)))
            sessao.execute(delete(chat).where(chat.fk_Aluno_id_aluno.in_(alunos_ids)))
        sessao.execute(delete(chat).where(chat.fk_Usuario_id_usuario == id_prof))
        from services.storage import excluir_arquivos_por_professor

        excluir_arquivos_por_professor(sessao, id_prof)
        sessao.execute(delete(alunos).where(alunos.id_prof == id_prof))
        sessao.execute(delete(turmas).where(turmas.id_prof == id_prof))
        sessao.execute(delete(PasswordResetCode).where(PasswordResetCode.id_prof == id_prof))
        sessao.execute(delete(RefreshToken).where(RefreshToken.id_prof == id_prof))
        sessao.execute(delete(User_esc).where(User_esc.fk_Usuario_id_usuario == id_prof))
        sessao.execute(delete(User_grupo).where(User_grupo.fk_Usuario_id_usuario == id_prof))
        conts_ids = sessao.execute(
            select(User_cont.fk_Contrato_id_cont).where(User_cont.fk_Usuario_id_usuario == id_prof)
        ).scalars().all()
        sessao.execute(delete(User_cont).where(User_cont.fk_Usuario_id_usuario == id_prof))
        grupos_user = sessao.execute(select(Grupo).where(Grupo.fk_Usuario_id_usuario == id_prof)).scalars().all()
        for g in grupos_user:
            escs_ids = sessao.execute(
                select(Escola.id_escola).where(Escola.fk_Grupo_id_grupo == g.id_grupo)
            ).scalars().all()
            if escs_ids:
                sessao.execute(delete(User_esc).where(User_esc.fk_Escola_id_escola.in_(escs_ids)))
                sessao.execute(delete(turmas).where(turmas.fk_Escola_id_escola.in_(escs_ids)))
            sessao.execute(delete(Escola).where(Escola.fk_Grupo_id_grupo == g.id_grupo))
            sessao.delete(g)
        if conts_ids:
            sessao.execute(delete(Pgto).where(Pgto.fk_Contrato_id_cont.in_(conts_ids)))
            sessao.execute(delete(Nota_fiscal).where(Nota_fiscal.fk_Contrato_id_cont.in_(conts_ids)))
        sessao.delete(professor)
        sessao.commit()
        return {"mensagem": "Professor apagado com sucesso"}
    except HTTPException:
        raise
    except OperationalError as e:
        print(f"[Users] OperationalError em deletaProfessor: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados temporariamente indisponível.",
        )
    except Exception as e:
        print(f"[Users] Erro interno em deletaProfessor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao remover professor.",
        )


def EditaProfessor(
    sessao: Session,
    professor_logado: professores,
    dados: Professoredita,
):
    professor = sessao.get(professores, professor_logado.id_prof)
    if not professor:
        raise HTTPException(status_code=404, detail="professor não encontrado")

    try:
        if dados.emailprof is not None and dados.emailprof != professor.email_prof:
            professor.email_prof = dados.emailprof
        if dados.numprof is not None and dados.numprof != professor.num_prof:
            professor.num_prof = dados.numprof

        veio_nome_real = bool(dados.nomeReal and dados.nomeReal.strip())
        veio_nome_prof = bool(dados.nomeProf and dados.nomeProf.strip())

        if veio_nome_real:
            novo_real = dados.nomeReal.strip()
            atual_real = (getattr(professor, "nome_real", None) or "").strip()
            if novo_real != atual_real:
                atualizado_em = getattr(professor, "nome_real_atualizado_em", None)
                if atual_real and atualizado_em is not None:
                    if atualizado_em.tzinfo is None:
                        atualizado_em = atualizado_em.replace(tzinfo=timezone.utc)
                    decorrido = datetime.now(timezone.utc) - atualizado_em
                    if decorrido < timedelta(days=30):
                        dias_restantes = max(1, 30 - decorrido.days)
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"O nome completo só pode ser alterado uma vez a cada 30 dias. Próxima alteração disponível em {dias_restantes} dia(s).",
                        )
                professor.nome_real = novo_real
                professor.nome_real_atualizado_em = datetime.now(timezone.utc)
                professor.perfil_professor_feito = True

        if veio_nome_prof:
            professor.nome_prof = dados.nomeProf.strip()
            professor.identificacao_feita = True

        if dados.tags is not None:
            professor.tags_usuario = _normalizar_tags(dados.tags)
        if dados.instrucoes_ia is not None:
            professor.instrucoes_ia = dados.instrucoes_ia.strip()

        sessao.commit()
        sessao.refresh(professor)

        atualizado_em_resp = getattr(professor, "nome_real_atualizado_em", None)
        dias_rest_resp = 0
        if atualizado_em_resp is not None:
            if atualizado_em_resp.tzinfo is None:
                atualizado_em_resp = atualizado_em_resp.replace(tzinfo=timezone.utc)
            dec = datetime.now(timezone.utc) - atualizado_em_resp
            if dec < timedelta(days=30):
                dias_rest_resp = max(1, 30 - dec.days)

        return {
            "mensagem": "Professor editado com sucesso",
            "instrucoes_ia": professor.instrucoes_ia or "",
            "nome_real": getattr(professor, "nome_real", None),
            "nome_usuario": professor.nome_prof,
            "dias_para_trocar_nome_real": dias_rest_resp,
            "perfil_professor_feito": bool(getattr(professor, "perfil_professor_feito", False)),
            "identificacao_feita": bool(professor.identificacao_feita),
        }

    except HTTPException:
        raise

    except OperationalError as e:
        print(f"[Users] OperationalError em EditaProfessor: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados temporariamente indisponível.",
        )
    except Exception as e:
        print(f"[Users] Erro interno em EditaProfessor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao editar perfil.",
        )


def atualizar_tutorial_visto_usuario(
    sessao: Session,
    professor_logado: professores,
    tutorial_visto: Optional[bool] = None,
    tutorial_institucional_visto: Optional[bool] = None,
) -> dict[str, Any]:
    professor = sessao.get(professores, professor_logado.id_prof)
    if not professor:
        raise HTTPException(status_code=404, detail="professor não encontrado")
    if tutorial_visto is None and tutorial_institucional_visto is None:
        professor.tutorial_visto = True
    else:
        if tutorial_visto is not None:
            professor.tutorial_visto = bool(tutorial_visto)
        if tutorial_institucional_visto is not None:
            professor.tutorial_institucional_visto = bool(tutorial_institucional_visto)
    sessao.commit()
    return {
        "tutorial_visto": bool(professor.tutorial_visto),
        "tutorial_institucional_visto": bool(getattr(professor, "tutorial_institucional_visto", False)),
    }


def atualizar_instrucoes_ia_usuario(
    sessao: Session,
    professor_logado: professores,
    instrucoes_ia: str,
) -> dict[str, Any]:
    professor = sessao.get(professores, professor_logado.id_prof)
    if not professor:
        raise HTTPException(status_code=404, detail="professor não encontrado")
    professor.instrucoes_ia = (instrucoes_ia or "").strip()
    sessao.commit()
    sessao.refresh(professor)
    return {
        "mensagem": "Instruções personalizadas para a IA atualizadas com sucesso.",
        "instrucoes_ia": professor.instrucoes_ia or "",
    }


def desconectar_todos_dispositivos_usuario(
    sessao: Session,
    professor_logado: professores,
) -> dict[str, Any]:
    professor = sessao.get(professores, professor_logado.id_prof)
    if not professor:
        raise HTTPException(status_code=404, detail="professor não encontrado")
    versao_atual = int(getattr(professor, "token_version", None) or 1)
    professor.token_version = versao_atual + 1
    sessao.commit()
    sessao.refresh(professor)
    return {
        "mensagem": "Todos os dispositivos foram desconectados com sucesso.",
        "token_version": professor.token_version,
    }


def exportar_dados_usuario(
    sessao: Session,
    professor_logado: professores,
) -> dict[str, Any]:
    """Exporta todos os dados vinculados ao professor (LGPD), excluindo senhas."""
    perfil_completo = obter_perfil_completo_usuario(sessao, professor_logado)
    escolas_lista = perfil_completo.get("escolas", [])
    ids_escolas = [e["id_escola"] for e in escolas_lista if "id_escola" in e]

    stmt_turmas = select(Turma).where(
        (Turma.fk_Usuario_id_usuario == professor_logado.id_usuario)
        | (Turma.fk_Escola_id_escola.in_(ids_escolas) if ids_escolas else False)
    )
    turmas_objs = sessao.execute(stmt_turmas).scalars().all()
    ids_turmas = [t.id_turma for t in turmas_objs]

    stmt_alunos = select(Aluno).where(
        (Aluno.fk_Usuario_id_usuario == professor_logado.id_usuario)
        | (Aluno.fk_Turma_id_turma.in_(ids_turmas) if ids_turmas else False)
    )
    alunos_objs = sessao.execute(stmt_alunos).scalars().all()

    convs_objs = (
        sessao.execute(
            select(chat)
            .where(chat.fk_Usuario_id_usuario == professor_logado.id_usuario)
            .order_by(chat.criado_em.asc())
        )
        .scalars()
        .all()
    )
    conversas_export: list[dict[str, Any]] = []
    for c in convs_objs:
        msgs_c = (
            sessao.execute(
                select(Mensagem)
                .where(
                    Mensagem.fk_chat_id_chat == c.id_chat,
                    Mensagem.fk_Usuario_id_usuario == professor_logado.id_usuario,
                )
                .order_by(Mensagem.data_envio.asc())
            )
            .scalars()
            .all()
        )
        conversas_export.append(
            {
                "conversa_id": c.id_chat,
                "titulo": c.nome_chat,
                "id_aluno": c.fk_Aluno_id_aluno,
                "criado_em": c.criado_em.isoformat() if c.criado_em else None,
                "atualizado_em": c.atualizado_em.isoformat() if c.atualizado_em else None,
                "mensagens": [
                    {
                        "id_mensagem": m.id_mensagem,
                        "role": m.tipo_remetente,
                        "conteudo": m.texto_mensagem,
                        "data": m.data_envio.isoformat() if m.data_envio else None,
                    }
                    for m in msgs_c
                ],
            }
        )

    peis_export: list[dict[str, Any]] = []
    ia_api_url = os.getenv("IA_API_URL", os.getenv("URL", "http://localhost:8001")).rstrip("/")
    if alunos_objs and settings.ENVIRONMENT not in ("test", "testing"):
        try:
            import httpx

            claims = obter_claims_jwt_usuario(sessao, professor_logado)
            tok = security.criar_access_token(data=claims, expires_delta=timedelta(minutes=5))
            headers = {"Authorization": f"Bearer {tok}"}
            with httpx.Client(timeout=2.0) as client:
                for al in alunos_objs:
                    r = client.get(f"{ia_api_url}/alunos/{al.id_aluno}/pei", headers=headers)
                    if r.is_success:
                        peis_export.append({"id_aluno": al.id_aluno, "peis": r.json()})
        except Exception:
            pass

    return {
        "exportado_em": datetime.now(timezone.utc).isoformat(),
        "perfil": {
            "id_usuario": professor_logado.id_usuario,
            "nome_usuario": professor_logado.nome_usuario,
            "email_usuario": professor_logado.email_usuario,
            "telefone_usuario": professor_logado.telefone_usuario,
            "cpf_cnpj": professor_logado.cpf_cnpj,
            "tipo_usuario": professor_logado.tipo_usuario,
            "tags": perfil_completo.get("tags", []),
            "instrucoes_ia": getattr(professor_logado, "instrucoes_ia", None) or "",
            "plano": perfil_completo.get("plano", "normal"),
        },
        "escolas": escolas_lista,
        "turmas": [
            {
                "id_turma": t.id_turma,
                "nome_turma": t.nome_turma,
                "id_escola": t.fk_Escola_id_escola,
            }
            for t in turmas_objs
        ],
        "alunos": [
            {
                "id_aluno": a.id_aluno,
                "nome_aluno": a.nome_aluno,
                "idade_aluno": a.idade_aluno,
                "neurodivergencia": a.neuro_aluno,
                "descricao": a.desc_aluno,
                "perfil_ia": a.perfil_ia,
                "id_turma": a.fk_Turma_id_turma,
            }
            for a in alunos_objs
        ],
        "conversas": conversas_export,
        "peis": peis_export,
    }
