import os
from pathlib import Path

from dotenv import load_dotenv
from pwdlib import PasswordHash

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()


class Settings:
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
    SECRET_KEY: str = os.environ["SECRET_KEY"].strip()
    # algoritimo do hash - declara o tipo de algoritomo que sera feito o hash
    ALGORITHM: str = "HS256"
    # tempo do token - tempo maximo que o token pode existir
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
    MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD", "")
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    TWILIO_CONTENT_SID: str = os.getenv("TWILIO_CONTENT_SID", "")
    BD_ACCESS: str = os.environ["BD_ACCESS"]

    # Segurança: CORS e Rate Limiting
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        ).split(",")
        if o.strip() and o.strip() != "*"
    ]
    RATE_LIMIT_DEFAULT: str = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")
    STORAGE_DIR: str = os.getenv(
        "STORAGE_DIR",
        str(Path(__file__).resolve().parents[2] / "storage"),
    )
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    SUPABASE_BUCKET: str = (
        os.getenv("SUPABASE_BUCKET", "metamorphia-arquivos").strip()
        or "metamorphia-arquivos"
    )
    AI_ALLOWED_EMAILS: str = os.getenv("AI_ALLOWED_EMAILS", "").strip()

    # Mercado Pago
    MP_ACCESS_TOKEN: str = os.getenv("MP_ACCESS_TOKEN", "")
    MP_WEBHOOK_SECRET: str = os.getenv("MP_WEBHOOK_SECRET", "")
    MP_NOTIFICATION_URL: str = os.getenv("MP_NOTIFICATION_URL", "")
    MP_SUCCESS_URL: str = os.getenv("MP_SUCCESS_URL", "")
    MP_FAILURE_URL: str = os.getenv("MP_FAILURE_URL", "")
    MP_PENDING_URL: str = os.getenv("MP_PENDING_URL", "")


settings = Settings()

if settings.ENVIRONMENT == "production" and len(settings.SECRET_KEY.strip()) < 32:
    raise RuntimeError("SECRET_KEY deve ter ao menos 32 caracteres em ambiente de produção.")

# cria o melhor tipo de hash para senhas atualmente
password_hash = PasswordHash.recommended()
# roda mesmo sem usuario correto
DUMMY_HASH = password_hash.hash("dummypassword")
