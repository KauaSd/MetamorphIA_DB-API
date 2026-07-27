from database import (
    IntegrityError,
    OperationalError,
    Session,
    turmas,
    select
)
from fastapi import HTTPException, status
from schemas.schemas import Turma


def AdicionarTurma(sessao:Session, form: Turma, id_prof:int):
    try:
        new = turmas(
            id_prof = id_prof,
            nome_turma = form.nome
        )
        sessao.add(new)
        sessao.commit()
        sessao.refresh(new)
        return {"mensagem" : "Turma cadastrada com sucesso"}
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Erro: Turma já cadastrada ou dados obrigatórios ausentes. Erro:{e}"
        )
    except OperationalError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}"
        )
    except Exception as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro:{e}"
        )

def DeletaTurma(sessao:Session, id_turma: int, id_prof:int):
    try:
        turma = sessao.get(turmas, id_turma)
        if not turma:
            raise HTTPException(status_code=404, detail="Turma não encontrada")
        if turma.id_prof != id_prof:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail= "Você não tem permissão para apagar esta turma")
        sessao.delete(turma)
        sessao.commit()
        return {"mensagem" : "Turma apagada com sucesso"}
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro:{e}")

def PesquisarTurma(sessao:Session, pesquisa:str, id_prof:int):
    try:
        query = select(turmas).where(turmas.nome_turma.icontains(pesquisa), turmas.id_prof==id_prof)
        result = sessao.execute(query).scalars().all()
        return result
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro:{e}")