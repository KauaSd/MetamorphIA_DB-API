from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import secrets
import smtplib
from typing import Any

from config.settings import settings
from database import PasswordResetCode, Session, Usuario, delete, select
import dependencies
from fastapi import HTTPException, status
import jwt
from jwt.exceptions import InvalidTokenError
from schemas.schemas import (
    AlterarSenhaRequest,
    RecuperarSenhaRequest,
    RedefinirSenhaRequest,
    VerificarCodigoSenhaRequest,
)
import security
import services.users as users

_MSG_RECUPERACAO_PADRAO = (
    "Se os dados informados estiverem cadastrados, um código de verificação de 6 dígitos foi enviado."
)


def _enviar_codigo_por_email_ou_telefone(
    sessao: Session, usuario: Usuario, identificador: str, codigo: str
) -> None:
    """Envia o código de 6 dígitos por e-mail (SMTP) ou WhatsApp/SMS (Twilio) se configurado."""
    eh_email = dependencies.is_email((identificador or "").strip())
    if eh_email or (usuario.email_usuario and not usuario.telefone_usuario):
        if not usuario.email_usuario:
            return
        if not settings.MAIL_USERNAME or not settings.MAIL_PASSWORD:
            return
        msg = EmailMessage()
        msg["Subject"] = "Código de recuperação de senha - MetamorphIA"
        msg["From"] = settings.MAIL_USERNAME
        msg["To"] = str(usuario.email_usuario)
        msg.set_content(
            f"Seu código para redefinição de senha no MetamorphIA é: {codigo}. Ele expira em 10 minutos."
        )
        try:
            with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
                server.send_message(msg)
        except Exception as exc:
            print(f"[PasswordReset] Falha SMTP: {exc}")
            if settings.ENVIRONMENT == "production":
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Falha temporária ao enviar o e-mail de recuperação.",
                ) from exc
    else:
        if not usuario.telefone_usuario:
            return
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            return
        try:
            dependencies.envia_msg_wpp(
                sessao,
                usuario.id_usuario,
                f"Seu código de recuperação de senha MetamorphIA é: {codigo}",
            )
        except Exception:
            pass


def solicitar_recuperacao_senha(
    sessao: Session, dados: RecuperarSenhaRequest
) -> dict[str, Any]:
    """Gera código de 6 dígitos e envia por e-mail ou telefone sem vazar existência da conta."""
    usuario = dependencies.pegar_usuario_por_indentificador(sessao, dados.identificador)
    if not usuario:
        return {"mensagem": _MSG_RECUPERACAO_PADRAO}

    sessao.execute(
        delete(PasswordResetCode).where(PasswordResetCode.id_prof == usuario.id_usuario)
    )
    codigo = str(secrets.randbelow(900000) + 100000)
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=10)
    reg = PasswordResetCode(
        id_prof=usuario.id_usuario,
        codigo=codigo,
        expira_em=expira_em,
        tentativas=0,
        usado=False,
    )
    sessao.add(reg)
    sessao.commit()
    sessao.refresh(reg)

    _enviar_codigo_por_email_ou_telefone(sessao, usuario, dados.identificador, codigo)
    return {"mensagem": _MSG_RECUPERACAO_PADRAO}


def verificar_codigo_recuperacao(
    sessao: Session, dados: VerificarCodigoSenhaRequest
) -> dict[str, Any]:
    """Valida o código de 6 dígitos e retorna um reset_token JWT temporário."""
    usuario = dependencies.pegar_usuario_por_indentificador(sessao, dados.identificador)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código de verificação inválido ou expirado.",
        )

    reg = (
        sessao.execute(
            select(PasswordResetCode).where(
                PasswordResetCode.id_prof == usuario.id_usuario,
                PasswordResetCode.usado.is_(False),
            )
        )
        .scalars()
        .first()
    )
    if not reg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum código de recuperação ativo para este usuário.",
        )

    agora = datetime.now(timezone.utc)
    expira_em = reg.expira_em
    if expira_em.tzinfo is None:
        expira_em = expira_em.replace(tzinfo=timezone.utc)

    if reg.tentativas >= 5:
        sessao.delete(reg)
        sessao.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Muitas tentativas inválidas. Solicite um novo código.",
        )

    if expira_em <= agora:
        sessao.delete(reg)
        sessao.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código expirado. Solicite um novo código.",
        )

    if not secrets.compare_digest(str(dados.codigo).strip(), str(reg.codigo)):
        reg.tentativas += 1
        sessao.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código de verificação incorreto.",
        )

    reg.usado = True
    sessao.commit()

    reset_token = security.criar_access_token(
        data={
            "sub": str(usuario.id_usuario),
            "purpose": "password_reset",
            "tv": int(getattr(usuario, "token_version", None) or 1),
        },
        expires_delta=timedelta(minutes=10),
    )
    return {
        "mensagem": "Código verificado com sucesso.",
        "reset_token": reset_token,
        "token_type": "bearer",
    }


def redefinir_senha_com_token(
    sessao: Session, dados: RedefinirSenhaRequest
) -> dict[str, Any]:
    """Atualiza a senha do usuário usando o token temporário de redefinição e invalida sessões antigas."""
    try:
        payload = security.decodificar_jwt_padrao(dados.reset_token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de redefinição inválido ou expirado.",
        ) from exc

    if payload.get("purpose") != "password_reset" or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido para redefinição de senha.",
        )

    usuario = sessao.get(Usuario, int(payload["sub"]))
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    versao_atual = int(getattr(usuario, "token_version", None) or 1)
    if int(payload.get("tv", versao_atual)) != versao_atual:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Este token de redefinição já foi utilizado ou invalidado.",
        )

    usuario.senha_usuario = security.cria_hash_senha(dados.nova_senha)
    usuario.token_version = versao_atual + 1
    sessao.execute(
        delete(PasswordResetCode).where(PasswordResetCode.id_prof == usuario.id_usuario)
    )
    sessao.commit()
    sessao.refresh(usuario)

    return {"mensagem": "Senha redefinida com sucesso."}


def alterar_senha_autenticado(
    sessao: Session,
    professor_logado: Usuario,
    dados: AlterarSenhaRequest,
) -> dict[str, Any]:
    """Altera a senha do usuário autenticado e retorna um novo access_token atualizado."""
    usuario = sessao.get(Usuario, professor_logado.id_usuario)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Professor não encontrado.",
        )

    if usuario.senha_usuario:
        if not dados.senha_atual or not security.verifica_senha(
            dados.senha_atual, usuario.senha_usuario
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A senha atual informada está incorreta.",
            )

    usuario.senha_usuario = security.cria_hash_senha(dados.nova_senha)
    versao_atual = int(getattr(usuario, "token_version", None) or 1)
    usuario.token_version = versao_atual + 1
    sessao.commit()
    sessao.refresh(usuario)

    claims = users.obter_claims_jwt_usuario(sessao, usuario)
    novo_token = security.criar_access_token(
        data=claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {
        "mensagem": "Senha alterada com sucesso.",
        "access_token": novo_token,
        "token_type": "bearer",
    }
