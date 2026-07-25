import re
from typing import Annotated

import jwt
import security
from config.settings import settings
from database import pegar_bd, professores, user2famethods
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from schemas.schemas import Tipo2FA
from sqlalchemy.orm import Session
from twilio.rest import Client

security_scheme = HTTPBearer()

def pegar_2fa_prof(sessao: Session, id: int):
    resultado = (
        sessao.query(user2famethods).filter(user2famethods.id_prof == id).first()
    )

    if resultado is not None:
        return resultado
    else:
        prof_existe = (
            sessao.query(professores.id_prof).filter(professores.id_prof == id).scalar()
        )
        if not prof_existe:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="professor não encontrado")
        mfa = user2famethods(
            id_prof=id, tipo=Tipo2FA.NONE, secret=None, usa_verificacao=False
        )
    sessao.add(mfa)
    sessao.commit()
    sessao.refresh(mfa)
    resultado = (
        sessao.query(user2famethods).filter(user2famethods.id_prof == id).first()
    )
    return resultado

def is_email(txt: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", txt))


def pegar_usuario_por_id(sessao: Session, id: int):
    return sessao.query(professores).filter(professores.id_prof == id).first()


def pegar_usuario_por_indentificador(sessao: Session, indentificador: str):
    if is_email(indentificador):
        return (
            sessao.query(professores)
            .filter(professores.email_prof == indentificador)
            .first()
        )
    else:
        return (
            sessao.query(professores)
            .filter(professores.num_prof == indentificador)
            .first()
        )

def pegar_professor_logado(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    sessao: Annotated[Session, Depends(pegar_bd)],
):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        id_prof = payload.get("sub")
        is_verified = payload.get("is_verified")
        if id_prof is None or not is_verified:
            raise credentials_exception
    except InvalidTokenError as e:
        print(e)
        raise credentials_exception
    professor = pegar_usuario_por_id(sessao, id_prof)
    if professor is None:
        print(professor)
        raise credentials_exception
    return professor


def pegar_usuario_pendente_2fa(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
) -> dict:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        id_prof = payload.get("sub")
        tipo_mfa = payload.get("2fa")

        if id_prof is None or tipo_mfa is None:
            raise credentials_exception
        return {"id_prof": int(id_prof), "tipo_2fa": tipo_mfa}
    except InvalidTokenError:
        raise credentials_exception

def envia_msg_wpp(
    sessao: Session,
    id_prof : int,
    msg: str
):
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    client = Client(account_sid, auth_token)
    numprof = str(sessao.query(professores.num_prof).where(professores.id_prof == id_prof).scalar())
    if not numprof:
        raise ValueError("professor não possui número cadastrado.")
    numero = "whatsapp:+55" + numprof

    try:
        client.messages.create(
            from_=settings.TWILIO_PHONE_NUMBER,
            body=msg,
            to = numero
            )
        return {"mensagem enviada"}
    except Exception as e:
        print(f"erro ao enviar mensagem: {e}")
        return False