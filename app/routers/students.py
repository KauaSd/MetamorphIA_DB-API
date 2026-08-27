from typing import List

from database import (
    IntegrityError,
    OperationalError,
    Session,
    alunos,
    pegar_bd,
    professores,
    select,
)
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, status
from schemas.schemas import Aluno, Alunoschema, EditaAlunoSchema, PesquisaAluno
from services.students import ConsultaAluno, RecebeAluno, DeletaAluno, EditaAluno

Student_router = APIRouter(prefix="/Alunos", tags=["Alunos"])


@Student_router.delete("/DeletaAluno/{id}")
def Deletar(
    id_aluno: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return DeletaAluno(id_aluno, sessao, professor_logado.id_prof)


@Student_router.post("/RecebeAluno", status_code=status.HTTP_201_CREATED)
def Receber(
    form: Aluno,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return RecebeAluno(form, sessao, professor_logado.id_prof)


@Student_router.post("/ConsultaAluno", response_model=List[Alunoschema])
def Consultar(
    pesquisaAluno: PesquisaAluno,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return ConsultaAluno(pesquisaAluno, sessao, professor_logado.id_prof)

@Student_router.put("/EditaAluno")
def Editar(
    alunoed: EditaAlunoSchema,
    form: Aluno,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return EditaAluno(alunoed, form, sessao, professor_logado.id_prof)