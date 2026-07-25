import dependencies
from datetime import datetime, timezone
from config.settings import settings
from datetime import timedelta
import security
from config.settings import DUMMY_HASH
import services.mfa as fnmfa
from database import (
    IntegrityError,
    OperationalError,
    Session,
    professores,
    user2famethods,
)
from fastapi import HTTPException, status
from schemas.schemas import Professor, LoginForm, Tipo2FA, Token


def cria_prof(sessao: Session, dados: Professor):
    try:
        professor = professores(
            email_prof=dados.emailprof,
            num_prof=dados.numprof,
            nome_prof=dados.nomeProf,
            senha_prof=security.cria_hash_senha(dados.senhaProf),
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
        sessao.commit()
        sessao.refresh(professor)
        return professor
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
    if not usuario:
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
    mfa = fnmfa.pegar_2fa_prof(sessao, usuario.id_prof)
    if not mfa.usa_verificacao:
        print(mfa.tipo)
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = security.criar_access_token(
            data={"sub": str(usuario.id_prof), "is_verified": True},
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
