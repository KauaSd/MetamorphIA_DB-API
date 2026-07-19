from database import professores, Session, IntegrityError, OperationalError
from fastapi import HTTPException, status
from schemas import schemas
import security

def pegar_usuario_por_nome(sessao: Session, nomeProf:str):
    return sessao.query(professores).filter(professores.nome_prof == nomeProf).first()
def cria_prof(sessao: Session, dados: schemas.Professor):
    try:
        professor=professores(
                    nome_prof=dados.nomeProf,
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
def autenticar_prof(sessao: Session, dados: schemas.LoginForm):
    usuario = pegar_usuario_por_nome(sessao, dados.nomeProf)
    if not usuario:
        security.verifica_senha(dados.senhaProf, security.DUMMY_HASH)
        return False
    if not security.verifica_senha(dados.senhaProf, usuario.senha_prof):
        return False
    return usuario