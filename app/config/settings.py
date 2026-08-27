import os

from dotenv import load_dotenv
from pwdlib import PasswordHash

load_dotenv()
class Settings:
    SECRET_KEY: str = os.environ["SECRET_KEY"]
    # algoritimo do hash - declara o tipo de algoritomo que sera feito o hash
    ALGORITHM: str = "HS256"
    # tempo do token - tempo maximo que o token pode existir
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    MAIL_USERNAME: str = os.environ["MAIL_USERNAME"]
    MAIL_PASSWORD: str = os.environ["MAIL_PASSWORD"]
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587
    TWILIO_ACCOUNT_SID: str = os.environ["TWILIO_ACCOUNT_SID"]
    TWILIO_AUTH_TOKEN: str = os.environ["TWILIO_AUTH_TOKEN"]
    TWILIO_PHONE_NUMBER: str = os.environ["TWILIO_PHONE_NUMBER"]
    TWILIO_CONTENT_SID: str = os.environ["TWILIO_CONTENT_SID"]
    BD_ACCESS: str = os.environ["BD_ACCESS"]

settings = Settings()

# cria o melhor tipo de hash para senhas atualmente
password_hash = PasswordHash.recommended()
# roda mesmo sem usuario correto
DUMMY_HASH = password_hash.hash("dummypassword")