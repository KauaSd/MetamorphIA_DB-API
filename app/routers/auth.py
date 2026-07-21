from fastapi import APIRouter, HTTPException, status, Depends, Request
from database import Session, OperationalError, pegar_bd
from datetime import timedelta
from typing import Annotated
from main import limiter
from schemas.schemas import Professor, Token, LoginForm
import crud.users as users
import security

Auth_router = APIRouter(prefix="/autenticar", tags=["autenticar"])

@Auth_router.post("/cadastro")
async def cadastrarProfessor(
    dadosForm: Professor, 
    sessao: Session = Depends(pegar_bd)
    ):
    users.cria_prof(sessao, dadosForm)
    return {"mensagem": "Professor cadastrado"}

@Auth_router.post("/login")
@limiter.limit("5/minute")
async def logarProfessor( 
    request: Request,
    dados: Annotated[LoginForm, Depends()],
    sessao: Annotated[Session, Depends(pegar_bd)]) -> Token:
    try:
        usuario = users.autenticar_prof(sessao, dados)
    except OperationalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception as e:
        print(f"ERRO: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno"
        )

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorreta",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.criar_access_token(data= {"sub": str(usuario.id_prof)}, expires_delta=access_token_expires )
    return Token(access_token=access_token, token_type="bearer")