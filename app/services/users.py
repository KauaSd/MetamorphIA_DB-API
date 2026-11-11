from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any, Optional

from config.settings import DUMMY_HASH, settings
from database import (
    Aluno,
    Contrato,
    Escola,
    Grupo,
    IntegrityError,
    OperationalError,
    Plano,
    Session,
    Turma,
    User_cont,
    User_esc,
    User_grupo,
    Usuario,
    alunos,
    delete,
    garantir_planos_iniciais,
    professores,
    select,
    turmas,
    user2famethods,
)
import dependencies
from fastapi import HTTPException, status
import jwt
from schemas.schemas import (
    GoogleAuthRequest,
    LoginForm,
    Professor,
    Professoredita,
    Tipo2FA,
    Token,
)
import security
import services.mfa as fnmfa


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
    """Garante que todo usuário normal tenha desde o início 1 Grupo, 1 Contrato Básico e 1 Escola Básica."""
    planos = garantir_planos_iniciais(sessao)
    plano_basico = planos["basico"]

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
        max_qtd_turmas=plano_basico.max_turmas_por_escola,
        max_qtd_alunos=plano_basico.max_alunos_por_turma,
        max_qtd_escolas=plano_basico.max_escolas,
        fk_Plano_id_plano=plano_basico.id_plano,
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


def obter_claims_jwt_usuario(sessao: Session, usuario: Usuario) -> dict[str, Any]:
    """Monta as claims padronizadas do JWT com o plano ativo, tipo_usuario, grupo e permissão de chat."""
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

    nomes_planos = [planos_map.get(c.fk_Plano_id_plano, "basico") for c in contratos_usuario]
    if grupo and grupo.fk_Contrato_id_cont:
        cont_grupo = sessao.get(Contrato, grupo.fk_Contrato_id_cont)
        if cont_grupo:
            nomes_planos.append(planos_map.get(cont_grupo.fk_Plano_id_plano, "basico"))

    prioridade = {"institucional": 4, "pro_plus": 3, "pro": 2, "basico": 1}
    plano_principal = "basico"
    for np in nomes_planos:
        if prioridade.get(np, 0) > prioridade.get(plano_principal, 0):
            plano_principal = np

    if usuario.tipo_usuario in ("adm_institucional", "prof_institucional"):
        plano_principal = "institucional"

    pode_chat = True
    if usuario.tipo_usuario == "adm_institucional":
        pode_chat = False
    else:
        vinc_escs = sessao.execute(
            select(User_esc).where(User_esc.fk_Usuario_id_usuario == usuario.id_usuario)
        ).scalars().all()
        if vinc_escs and all(not v.pode_chat for v in vinc_escs):
            pode_chat = False

    tags_lista = [t for t in (usuario.tags_usuario or "").split(",") if t]

    return {
        "sub": str(usuario.id_usuario),
        "id_prof": usuario.id_usuario,
        "tipo_usuario": usuario.tipo_usuario,
        "plano": plano_principal,
        "id_grupo": grupo.id_grupo if grupo else None,
        "pode_chat": pode_chat,
        "tags": tags_lista,
        "is_verified": True,
    }


def cria_prof(sessao: Session, dados: Professor) -> dict[str, Any]:
    try:
        doc_limpo = _limpar_documento(dados.cpf_cnpj)
        tags_str = _normalizar_tags(dados.tags)

        professor = professores(
            email_prof=dados.emailprof,
            num_prof=dados.numprof,
            nome_prof=dados.nomeProf,
            senha_prof=security.cria_hash_senha(dados.senhaProf),
            cpf_cnpj=doc_limpo,
            tipo_usuario="normal",
            tags_usuario=tags_str,
        )
        sessao.add(professor)
        sessao.flush()

        mfa = user2famethods(
            tipo=Tipo2FA.NONE,
            secret=None,
            usa_verificacao=False,
            data_criacao=datetime.now(timezone.utc),
            id_prof=professor.id_prof,
        )
        sessao.add(mfa)

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
            "plano": "basico",
        }
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Erro: Este professor já está cadastrado ou dados obrigatórios estão ausentes. Erro: {e}",
        )
    except OperationalError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro: {e}",
        )
    except Exception as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro: {e}",
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

    mfa = fnmfa.pegar_2fa_prof(sessao, usuario.id_prof)
    if not mfa.usa_verificacao:
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        claims = obter_claims_jwt_usuario(sessao, usuario)
        access_token = security.criar_access_token(
            data=claims,
            expires_delta=access_token_expires,
        )
    else:
        access_token_expires = timedelta(minutes=5)
        access_token = security.criar_access_token(
            data={
                "sub": str(usuario.id_prof),
                "is_verified": False,
                "2fa": str(mfa.tipo),
            },
            expires_delta=access_token_expires,
        )
    return Token(
        access_token=access_token, token_type="bearer", requires_2fa=mfa.usa_verificacao
    )


def logar_com_google(dados: GoogleAuthRequest, sessao: Session) -> Token:
    """Autentica ou cadastra usuário via conta Google e provisiona estrutura inicial."""
    email = dados.email
    nome = dados.nome
    google_id = dados.google_id

    if dados.id_token:
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        try:
            if google_client_id:
                from google.auth.transport import requests as google_requests
                from google.oauth2 import id_token as google_id_token

                info = google_id_token.verify_oauth2_token(
                    dados.id_token, google_requests.Request(), google_client_id
                )
            else:
                info = jwt.decode(dados.id_token, options={"verify_signature": False})
            email = email or info.get("email")
            nome = nome or info.get("name") or info.get("given_name")
            google_id = google_id or info.get("sub")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token Google inválido: {exc}",
            ) from exc

    if not email and not google_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe um id_token válido ou email/google_id para login com Google.",
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

        mfa = user2famethods(
            tipo=Tipo2FA.NONE,
            secret=None,
            usa_verificacao=False,
            data_criacao=datetime.now(timezone.utc),
            id_prof=usuario.id_usuario,
        )
        sessao.add(mfa)
        provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()
        sessao.refresh(usuario)
    else:
        if google_id and not usuario.google_id:
            usuario.google_id = google_id
        if usuario.tipo_usuario == "normal":
            provisionar_estrutura_inicial_usuario(sessao, usuario)
        sessao.commit()

    claims = obter_claims_jwt_usuario(sessao, usuario)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.criar_access_token(
        data=claims,
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer", requires_2fa=False)


def troca_user2famethods(sessao: Session, id_prof: int, tipo: Tipo2FA, email: str):
    mfa = sessao.query(user2famethods).filter(user2famethods.id_prof == id_prof).first()

    if tipo == Tipo2FA.TOTP:
        secret = security.gerar_secret_totp()
        mfa.secret = secret
        mfa.tipo = tipo
        mfa.usa_verificacao = False
        sessao.commit()
        sessao.refresh(mfa)
        qr_code = security.gerar_qrcode_totp(secret, email)

        return {"qr_code": qr_code, "totp": True}
    mfa.tipo = tipo
    mfa.secret = None
    mfa.usa_verificacao = False if tipo == Tipo2FA.NONE else True
    sessao.commit()
    sessao.refresh(mfa)
    return {"message": "Ativação completa", "totp": False}


def fn_confirma_totp(sessao: Session, id_prof: int):
    mfa = sessao.query(user2famethods).filter(user2famethods.id_prof == id_prof).first()
    if mfa:
        mfa.usa_verificacao = True
        sessao.commit()
        sessao.refresh(mfa)
    return mfa


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

        sessao.execute(delete(turmas).where(turmas.id_prof == id_prof))
        sessao.execute(delete(alunos).where(alunos.id_prof == id_prof))
        sessao.delete(professor)
        sessao.commit()
        return {"mensagem": "Professor apagado com sucesso"}
    except HTTPException:
        raise
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro: {e}",
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
        if dados.emailprof != professor.email_prof:
            professor.email_prof = dados.emailprof
        if dados.numprof != professor.num_prof:
            professor.num_prof = dados.numprof
        if dados.nomeProf != professor.nome_prof:
            professor.nome_prof = dados.nomeProf
        if dados.tags is not None:
            professor.tags_usuario = _normalizar_tags(dados.tags)

        sessao.commit()
        sessao.refresh(professor)

        return {"mensagem": "Professor editado com sucesso"}

    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro: {e}",
        )
