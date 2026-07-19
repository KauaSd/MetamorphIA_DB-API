from typing import Annotated
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session
import security
import crud.users as users
from database import pegar_bd

security_scheme = HTTPBearer()

async def pegar_professor_logado(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    sessao: Annotated[Session, Depends(pegar_bd)],
    ):
    token= credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        nome_prof = payload.get("sub")
        if nome_prof is None:
                raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception
    professor = users.pegar_usuario_por_nome(sessao, nome_prof)
    if professor is None:
        raise credentials_exception
    return professor