from database import professores, Session, IntegrityError, OperationalError, Tipo2FA, user2famethods
from fastapi import HTTPException, status
import re
from datetime import datetime, timezone
from schemas import schemas
import security

def pegar_2fa_prof(
    sessao: Session,
    id: int
    
):
    resultado = sessao.query(user2famethods).filter(user2famethods.id_prof == id).first()

    if resultado is not None:
            return resultado
    else:
        prof_existe = sessao.query(professores.id_prof).filter(professores.id_prof == id).scalar()
        if not prof_existe:
            raise HTTPException(status_code=404, detail='professor não encontado')
        mfa = user2famethods(
        id_prof=id,
        tipo=Tipo2FA.NONE,
        secret=None,
        usa_verificacao=False
    )
    sessao.add(mfa)
    sessao.commit()
    sessao.refresh(mfa)
    resultado = sessao.query(user2famethods).filter(user2famethods.id_prof == id).first()
    return resultado

def is_email(
    txt: str
    ) -> bool:
    return bool (re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", txt))

def pegar_usuario_por_id(
        sessao: Session,
        id: int
):
    return sessao.query(professores).filter(professores.id_prof == id).first()

def pegar_usuario_por_indentificador(
    sessao: Session,
    indentificador:str
    ):
    if is_email(indentificador):
        return sessao.query(professores).filter(professores.email_prof == indentificador).first()
    else:
        return sessao.query(professores).filter(professores.num_prof == indentificador).first()
def cria_prof(
    sessao: Session, 
    dados: schemas.Professor
    ):
    try:
        professor=professores(
                    email_prof=dados.emailprof,
                    num_prof = dados.numprof,
                    nome_prof = dados.nomeProf,
                    senha_prof=security.cria_hash_senha(dados.senhaProf)
        )
        sessao.add(professor)
        sessao.flush()

        mfa = user2famethods(
            tipo = Tipo2FA.NONE,
            secret = None,
            usa_verificacao = False,
            data_criacao = datetime.now(timezone.utc),
            id_prof = professor.id_prof
        )
        sessao.add(mfa)
        sessao.commit()
        sessao.refresh(professor)
        return professor
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Erro: Este professor já está cadastrado ou dados obrigatórios estão ausentes."
        )
    except OperationalError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception as e:
        sessao.rollback()
        print(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno"
        )
def autenticar_prof(
    sessao: Session,
    dados: schemas.LoginForm
    ):
    usuario = pegar_usuario_por_indentificador(sessao, dados.indentificador)
    if not usuario:
        security.verifica_senha(dados.senhaProf, security.DUMMY_HASH)
        return False
    if not security.verifica_senha(dados.senhaProf, usuario.senha_prof):
        return False
    return usuario

def troca_user2famethods(
        sessao: Session,
        id_prof: int,
        tipo: Tipo2FA,
        email: str
):
    mfa = sessao.query(user2famethods).filter(user2famethods.id_prof == id_prof).first()

    if tipo == Tipo2FA.TOTP:
        secret = security.gerar_secret_totp()
        mfa.secret = secret
        mfa.tipo = tipo
        mfa.usa_verificacao = False
        sessao.commit()
        sessao.refresh(mfa)
        qr_code = security.gerar_qrcode_totp(secret, email)

        return {"qr_code": qr_code, 'totp' : True}
    mfa.tipo = tipo
    mfa.secret = None
    mfa.usa_verificacao = False if tipo == Tipo2FA.NONE else True
    sessao.commit()
    sessao.refresh(mfa)
    return {"message": "Ativação completa", 'totp' : False}

def fn_confirma_totp(
        sessao: Session,
        id_prof: int
):
    mfa = sessao.query(user2famethods).filter(user2famethods.id_prof == id_prof).first()
    if mfa:
        mfa.usa_verificacao = True
        sessao.commit()
        sessao.refresh(mfa)
    return mfa