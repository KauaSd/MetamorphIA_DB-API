from typing import List

from database import Session, alunos, pegar_bd, professores, select
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from schemas.schemas import Aluno, Alunoschema, EditaAlunoSchema, PesquisaAluno
from services.students import ConsultaAluno, DeletaAluno, EditaAluno, RecebeAluno

Student_router = APIRouter(prefix="/Alunos", tags=["Alunos"])


class AtualizarDescricaoRequest(BaseModel):
    desc_aluno: str


@Student_router.delete("/DeletaAluno/{id_aluno}")
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


@Student_router.patch("/{id_aluno}/descricao")
def AtualizarDescricaoAluno(
    id_aluno: int,
    payload: AtualizarDescricaoRequest,
    sessao: Session = Depends(pegar_bd),
    _professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    aluno.desc_aluno = payload.desc_aluno
    aluno.perfil_ia = payload.desc_aluno
    sessao.commit()
    sessao.refresh(aluno)
    return {
        "id_aluno": aluno.id_aluno,
        "desc_aluno": aluno.desc_aluno,
        "perfil_ia": aluno.perfil_ia,
    }


@Student_router.get("/{id_aluno}")
def ObterAlunoPorId(
    id_aluno: int,
    sessao: Session = Depends(pegar_bd),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    return {
        "id_aluno": aluno.id_aluno,
        "nome_aluno": aluno.nome_aluno,
        "neurodiv_aluno": aluno.neurodiv_aluno,
        "desc_aluno": aluno.desc_aluno,
        "perfil_ia": aluno.perfil_ia,
        "idade_aluno": aluno.idade_aluno,
        "id_prof": aluno.id_prof,
        "id_turma": aluno.id_turma,
    }


@Student_router.get("", response_model=List[Alunoschema])
def ListarAlunos(
    id_turma: int | None = None,
    sessao: Session = Depends(pegar_bd),
):
    stmt = select(alunos)
    if id_turma is not None:
        stmt = stmt.where(alunos.id_turma == id_turma)
    return sessao.execute(stmt).scalars().all()
