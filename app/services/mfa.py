import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import security
from config.settings import settings
from database import (
    Session,
    professores,
    user2facodes,
    user2famethods,
)
from dependencies import pegar_2fa_prof, envia_msg_wpp
from fastapi import HTTPException, status
from schemas.schemas import LoginForm, Professor, Tipo2FA, Token, Validar2FARequest


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

def envia_token(sessao: Session, id_prof: int):
    mfa = sessao.query(user2famethods).filter(user2famethods.id_prof == id_prof).first()
    if not mfa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="verificação de duas etapas não ativada ou professor não existe")
    codigo = str(secrets.randbelow(900000) + 100000)
    expiracao = datetime.now(timezone.utc) + timedelta(minutes=5)
    verifica_token_bd = sessao.query(user2facodes).filter(user2facodes.id_prof == id_prof).first()
    if verifica_token_bd:
        sessao.delete(verifica_token_bd)

    token_bd = user2facodes(
        codigo = codigo,
        expira_em = expiracao,
        tentativas = 0,
        id_prof = mfa.id_prof
        )
    sessao.add(token_bd)
    sessao.commit()
    sessao.refresh(token_bd)

    if mfa.tipo == Tipo2FA.EMAIL:
        email = sessao.query(professores.email_prof).filter(professores.id_prof == id_prof).scalar()
        if not email:
            raise HTTPException( status_code=status.HTTP_404_NOT_FOUND, detail="E-mail não encontrado.")
        msg = EmailMessage()
        msg['Subject'] = "Codigo de verificação MetamorphIA"
        msg ['From'] = settings.MAIL_USERNAME

        msg ['To'] = str(email)

        msg.set_content(f'Seu codigo de verificação é: {codigo}. ele expirará em 5 minutos.')

        SMTP_SERVER = settings.MAIL_SERVER
        SMTP_PORT = settings.MAIL_PORT
        EMAIL_REM = settings.MAIL_USERNAME
        SENHA = settings.MAIL_PASSWORD

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL_REM, SENHA)
                server.send_message(msg)
                return {"email enviado"}
        except smtplib.SMTPException as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Falha ao enviar o e-mail de verificação: {e}",
            )
    elif mfa.tipo == Tipo2FA.SMS:
        msg = f"seu token é: {codigo}"
        envia_msg_wpp(sessao, id_prof, msg)


def pegar_token( sessao: Session, id_prof: int):
    return sessao.query(user2facodes).filter(user2famethods.id_prof == id_prof).first()

def verificar2fa(
    dados: dict,
    dados_pendentes: Validar2FARequest,
    sessao: Session,
) -> Token:
    id_prof = dados_pendentes["id_prof"]
    tipo_2fa = dados_pendentes["tipo_2fa"]
    mfa = pegar_2fa_prof(sessao, id_prof)

    validacao = False

    if tipo_2fa == str(Tipo2FA.TOTP) or tipo_2fa == "TOTP":
        validacao = security.verificar_totp(mfa.secret, dados.codigo)
    else:
        mfa = pegar_token(sessao, id_prof)
        if not mfa:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="nenhum token solicitado."
            )
        token = mfa.codigo
        expiracao = mfa.expira_em
        agora = datetime.now(timezone.utc)
        tentativas = mfa.tentativas

        if expiracao.tzinfo is None:
            expiracao = expiracao.replace(tzinfo = timezone.utc)

        if tentativas>=5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail= "muitas tentativas, reenvie o token"
                )
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail= "não foi pedido um token"
                )
        
        if expiracao <= agora:
            sessao.delete(mfa)
            sessao.commit(mfa)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail= "token expirado, reenvie"
                )
        
        if dados.codigo!= token:
            mfa.tentativas +=1
            sessao.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail= "token errado"
                )
        
        validacao = True
        sessao.delete(mfa)
        sessao.commit()


    if not validacao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código de verificação inválido ou expirado",
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.criar_access_token(
        data={"sub": str(id_prof), "is_verified": True},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")