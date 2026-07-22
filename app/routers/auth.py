from fastapi import APIRouter, HTTPException, status, Depends, Request
from database import Session, OperationalError, pegar_bd, Tipo2FA, professores
from datetime import timedelta
from typing import Annotated
from main import limiter
from schemas.schemas import Professor, Token, LoginForm, Validar2FARequest
import crud.users as users
import security
from dependencies import pegar_professor_logado, pegar_usuario_pendente_2fa

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
def logarProfessor( 
    request: Request,
    dados: Annotated[LoginForm, Depends()],
    sessao: Annotated[Session, Depends(pegar_bd)]
    ) -> Token:
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
    mfa = users.pegar_2fa_prof(sessao, usuario.id_prof)
    if not mfa.usa_verificacao:
        print(mfa.tipo)
        access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = security.criar_access_token(data= {"sub": str(usuario.id_prof),"is_verified": True}, expires_delta=access_token_expires )
    else:
        access_token_expires = timedelta(minutes=5)
        access_token = security.criar_access_token(data= {"sub": str(usuario.id_prof),"is_verified": False, "2fa": str(mfa.tipo)}, expires_delta=access_token_expires )
    return Token(access_token=access_token, token_type="bearer", requires_2fa=mfa.usa_verificacao)

@Auth_router.post("/ativar2fa")
def ativar2fa(
    tipo_mfa: Tipo2FA,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado)
):
    return users.troca_user2famethods(sessao, professor_logado.id_prof, tipo_mfa, professor_logado.email_prof)

@Auth_router.post("/verificar-2fa")
@limiter.limit("5/minute")
def verificar2fa(
    request: Request,
    dados: Validar2FARequest,
    dados_pendentes: Annotated[dict, Depends(pegar_usuario_pendente_2fa)],
    sessao: Annotated[Session, Depends(pegar_bd)]
) -> Token:
    id_prof = dados_pendentes["id_prof"]
    tipo_2fa = dados_pendentes["tipo_2fa"]
    mfa = users.pegar_2fa_prof(sessao, id_prof)

    validacao=False

    if tipo_2fa == str(Tipo2FA.TOTP) or tipo_2fa == "TOTP":
        validacao = security.verificar_totp(mfa.secret, dados.codigo)
    if not validacao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código de verificação inválido ou expirado"
        )
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.criar_access_token(
        data= {
            "sub": str(id_prof),
            "is_verified": True
        },
        expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")

@Auth_router.post("/confirma_totp")
def confirma_totp(
    sessao: Annotated[Session, Depends(pegar_bd)],
    professor_logado: professores = Depends(pegar_professor_logado)
    ):
    return  users.fn_confirma_totp(sessao, professor_logado.id_prof)
