from fastapi import APIRouter, HTTPException, status
from DB_conn import engine, alunos, select, Session, IntegrityError, OperationalError
from pydantic import BaseModel

Auth_router = APIRouter(prefix="/Alunos", tags=["Alunos"])

@Auth_router.get("/DeletaAluno/{id}")
async def DeletaAluno(id: int):
    try:
        with Session(engine) as db:
            aluno = db.get(alunos, id)
            if not aluno:
                raise HTTPException(status_code = 404, detail="aluno não encontrado")
            db.delete(aluno)
            db.commit() 
        return {"mensagem" : "Aluno apagado com sucesso"}
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_CONFLICT,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno"
        )
