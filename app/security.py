import base64
from datetime import datetime, timedelta, timezone
import io

from config.settings import password_hash, settings
from fastapi import Request
import jwt
import pyotp
import qrcode
from slowapi import Limiter
from slowapi.util import get_remote_address


def verifica_senha(senha_pura: str, hash_senha: str) -> bool:
    return password_hash.verify(senha_pura, hash_senha)


def cria_hash_senha(senha: str) -> str:
    return password_hash.hash(senha)


def criar_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=15)
    )
    to_encode.setdefault("iss", settings.JWT_ISSUER)
    to_encode.setdefault("aud", settings.JWT_AUDIENCE)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decodificar_jwt_padrao(token: str) -> dict:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
    )


def obter_chave_rate_limit(request: Request) -> str:
    """Usa o ID do usuário autenticado (JWT assinado) para evitar colisão de IP entre serviços."""
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        token_raw = auth_header[7:].strip()
        if token_raw:
            try:
                payload = decodificar_jwt_padrao(token_raw)
                sub = payload.get("sub") or payload.get("id_prof")
                if sub is not None:
                    return f"user:{sub}"
            except Exception:
                pass
    return get_remote_address(request)


limiter = Limiter(
    key_func=obter_chave_rate_limit,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)


def gerar_secret_totp() -> str:
    return pyotp.random_base32()


def gerar_qrcode_totp(secret: str, email: str) -> str:
    totp = pyotp.totp.TOTP(secret).provisioning_uri(
        name=email, issuer_name="MetamorphIA"
    )
    img = qrcode.make(totp)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return (
        f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"
    )


def verificar_totp(secret: str, codigo: str) -> bool:
    if not secret or not codigo:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(codigo, valid_window=1)
