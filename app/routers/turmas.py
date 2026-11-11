from database import Session, pegar_bd, professores, turmas
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, status
from schemas.schemas import Turma, TurmaSchema
from services.turma import AdicionarTurma, DeletaTurma, PesquisarTurma

Turma_router = APIRouter(prefix="/turma", tags=["turma"])


@Turma_router.post("/AdicionarTurma", status_code=status.HTTP_201_CREATED)
def adicionar(
    form: Turma,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return AdicionarTurma(sessao, form, professor_logado.id_prof)


@Turma_router.delete("/DeletaTurma", status_code=status.HTTP_201_CREATED)
def deletar(
    id_turma: TurmaSchema,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return DeletaTurma(sessao, id_turma.id_turma, professor_logado.id_prof)


@Turma_router.post("/PesquisarTurma", status_code=status.HTTP_201_CREATED)
def pesquisar(
    nome_turma: Turma,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return PesquisarTurma(sessao, nome_turma.nome, professor_logado.id_prof)


@Turma_router.get("/{id_turma}")
def ObterTurmaPorId(
    id_turma: int,
    sessao: Session = Depends(pegar_bd),
):
    turma = sessao.get(turmas, id_turma)
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    return {
        "id_turma": turma.id_turma,
        "nome_turma": turma.nome_turma,
        "id_prof": turma.id_prof,
        "id_escola": turma.fk_Escola_id_escola,
    }
