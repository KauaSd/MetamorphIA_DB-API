from datetime import timedelta
from typing import Annotated
import services.mfa as fnmfa
import services.users as users
import security
from database import OperationalError, Session, Tipo2FA, pegar_bd, professores
from dependencies import pegar_professor_logado, pegar_usuario_pendente_2fa
from datetime import datetime,timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from main import limiter
from schemas.schemas import LoginForm, Professor, Token, Validar2FARequest
from config.settings import settings

Auth_router = APIRouter(prefix="/autenticar", tags=["autenticar"])


@Auth_router.post("/cadastro")
async def cadastrarProfessor(dadosForm: Professor, sessao: Session = Depends(pegar_bd)):
    users.cria_prof(sessao, dadosForm)
    return {"mensagem": "Professor cadastrado"}


@Auth_router.post("/login")
@limiter.limit("5/minute")
def logar(
    request: Request,
    dados: Annotated[LoginForm, Depends()],
    sessao: Annotated[Session, Depends(pegar_bd)],
) -> Token:
    return users.logarProfessor(
        dados, sessao
    )


@Auth_router.post("/ativar2fa")
def ativar2fa(
    tipo_mfa: Tipo2FA,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return fnmfa.troca_user2famethods(
        sessao, professor_logado.id_prof, tipo_mfa, professor_logado.email_prof
    )


@Auth_router.post("/verificar-2fa")
@limiter.limit("5/minute")
def verificar(
    request: Request,
    dados: Validar2FARequest,
    dados_pendentes: Annotated[dict, Depends(pegar_usuario_pendente_2fa)],
    sessao: Annotated[Session, Depends(pegar_bd)],
) -> Token:
    return fnmfa.verificar2fa(
        dados, dados_pendentes, sessao
    )


@Auth_router.post("/confirma_totp")
def confirma_totp(
    sessao: Annotated[Session, Depends(pegar_bd)],
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return fnmfa.fn_confirma_totp(
        sessao, professor_logado.id_prof
    )


@Auth_router.post("/envia_token")
def token(
    sessao: Annotated [Session, Depends(pegar_bd)],
    professor: Annotated [dict, Depends(pegar_usuario_pendente_2fa)]
):
    return fnmfa.envia_token(
        sessao, professor["id_prof"]
    )