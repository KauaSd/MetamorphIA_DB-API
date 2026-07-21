from database import professores, Session, IntegrityError, OperationalError
from fastapi import HTTPException, status
import re
from schemas import schemas
import security

def is_email(txt: str) -> bool:
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