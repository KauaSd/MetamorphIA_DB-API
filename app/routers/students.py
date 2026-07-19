from fastapi import APIRouter, HTTPException, status, Depends
from database import alunos, select, Session, IntegrityError, OperationalError,pegar_bd, professores
from typing import List
from schemas.schemas import Aluno, Alunoschema
from dependencies import pegar_professor_logado
Student_router = APIRouter(prefix="/Alunos", tags=["Alunos"])

@Student_router.delete("/DeletaAluno/{id}")
async def DeletaAluno(id: int, sessao:Session = Depends(pegar_bd), professor_logado: professores = Depends(pegar_professor_logado)):
    try:
        aluno = sessao.get(alunos, id)
        if not aluno:
            raise HTTPException(status_code=404, detail="aluno não encontrado")
        if aluno.id_prof != professor_logado.id_prof:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail= "Você não tem permissão para apagar este aluno")
        sessao.delete(aluno)
        sessao.commit()
        return {"mensagem" : "Aluno apagado com sucesso"}
    except HTTPException:
        raise
    except OperationalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno")

@Student_router.post("/RecebeAluno", status_code=status.HTTP_201_CREATED)
async def RecebeAluno(form: Aluno, sessao:Session = Depends(pegar_bd), professor_logado: professores = Depends(pegar_professor_logado)):
    try:
        new = alunos(
                id_prof = professor_logado.id_prof,
                nome_aluno=form.nome,
                neurodiv_aluno=form.neurodivergencia,
                serie_aluno = form.serie,
                diag_aluno = form.diagnosticado,
                desc_aluno = form.descricao,
                idade_aluno = form.idade
            )
        sessao.add(new)
        sessao.commit()
        sessao.refresh(new)
        return {"mensagem": "Aluno cadastrado com sucesso"}
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Erro: aluno já cadastrado ou dados obrigatórios ausentes"
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
@Student_router.get("/consultaaluno", response_model=List[Alunoschema])
async def consultaaluno(sessao:Session = Depends(pegar_bd), professor_logado: professores = Depends(pegar_professor_logado)):
    try:
            query= select(alunos).where(alunos.id_prof==professor_logado.id_prof)
            result = sessao.execute(query).scalars().all()
            return result
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno"
        )