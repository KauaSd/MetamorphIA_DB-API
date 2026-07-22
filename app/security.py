import os
from datetime import timedelta,timezone,datetime
import jwt
import io
import pyotp
import qrcode
import base64
from pwdlib import PasswordHash
from dotenv import load_dotenv
load_dotenv()
SECRET_KEY=os.environ["SECRET_KEY"]
#algoritimo do hash - declara o tipo de algoritomo que sera feito o hash
ALGORITHM="HS256"
#tempo do token - tempo maximo que o token pode existir
ACCESS_TOKEN_EXPIRE_MINUTES= 30
#cria o melhor tipo de hash para senhas atualmente
password_hash=PasswordHash.recommended()

#roda mesmo sem usuario correto
DUMMY_HASH= password_hash.hash("dummypassword")
#ve se a senha do hash e a senha pura do usuario sao iguais
def verifica_senha(senha_pura: str, hash_senha: str) -> bool:
    return password_hash.verify(senha_pura, hash_senha)
#cria o hash da senha pura
def cria_hash_senha(senha: str) ->str:
    return password_hash.hash(senha)

#criando o jwt
def criar_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    #tudo que vai dentro do token que vai ser criado
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=15))
    #adiciono o tempo de limite maximo do jwt
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def gerar_secret_totp() -> str:
    return pyotp.random_base32()

def gerar_qrcode_totp(
    secret: str, 
    email: str
    )-> str:
    totp = pyotp.totp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name='MetamorphIA'
    )
    img = qrcode.make(totp)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"

def verificar_totp(
        secret: str,
        codigo: str
) -> bool:

    if not secret or not codigo:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(codigo, valid_window=1)