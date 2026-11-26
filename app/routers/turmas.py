from database import Session, User_esc, pegar_bd, professores, select, turmas
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, status
from schemas.schemas import Turma, TurmaSchema
from services.planos import listar_escolas_usuario, obter_contexto_escola
from services.turma import AdicionarTurma, DeletaTurma, EditarTurma, PesquisarTurma

Turma_router = APIRouter(prefix="/turma", tags=["turma"])


@Turma_router.post("/AdicionarTurma", status_code=status.HTTP_201_CREATED)
def adicionar(
    form: Turma,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return AdicionarTurma(sessao, form, professor_logado.id_prof)


@Turma_router.put("/{id_turma}")
def editar_turma(
    id_turma: int,
    form: Turma,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return EditarTurma(sessao, id_turma, form, professor_logado.id_prof)


@Turma_router.delete("/DeletaTurma", status_code=status.HTTP_201_CREATED)
def deletar(
    id_turma: TurmaSchema,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return DeletaTurma(sessao, id_turma.id_turma, professor_logado.id_prof)


@Turma_router.delete("/{id_turma}")
def deletar_por_id(
    id_turma: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return DeletaTurma(sessao, id_turma, professor_logado.id_prof)


@Turma_router.post("/PesquisarTurma", status_code=status.HTTP_201_CREATED)
def pesquisar(
    nome_turma: Turma,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    lista = PesquisarTurma(sessao, nome_turma.nome, professor_logado.id_prof)
    return [
        {
            "id_turma": t.id_turma,
            "nome_turma": t.nome_turma,
            "serie_ano": getattr(t, "serie_ano", None),
            "letra": getattr(t, "letra", None),
            "horario": getattr(t, "horario", None),
            "id_prof": t.id_prof,
            "id_escola": t.fk_Escola_id_escola,
        }
        for t in lista
    ]


@Turma_router.get("")
def ListarTurmas(
    id_escola: int | None = None,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    stmt = select(turmas)
    if professor_logado.tipo_usuario != "adm_sistema":
        if id_escola is not None:
            obter_contexto_escola(sessao, professor_logado.id_prof, id_escola)
            stmt = stmt.where(turmas.fk_Escola_id_escola == id_escola)
        else:
            escolas_ids_visiveis = [
                e["id_escola"] for e in listar_escolas_usuario(sessao, professor_logado)
            ]
            stmt = stmt.where(
                turmas.fk_Escola_id_escola.in_(escolas_ids_visiveis)
                if escolas_ids_visiveis
                else (turmas.id_prof == -1)
            )
    elif id_escola is not None:
        stmt = stmt.where(turmas.fk_Escola_id_escola == id_escola)
    lista = sessao.execute(stmt).scalars().all()
    return [
        {
            "id_turma": t.id_turma,
            "nome_turma": t.nome_turma,
            "serie_ano": getattr(t, "serie_ano", None),
            "letra": getattr(t, "letra", None),
            "horario": getattr(t, "horario", None),
            "id_prof": t.id_prof,
            "id_escola": t.fk_Escola_id_escola,
        }
        for t in lista
    ]


@Turma_router.get("/{id_turma}")
def ObterTurmaPorId(
    id_turma: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    turma = sessao.get(turmas, id_turma)
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    if professor_logado.tipo_usuario != "adm_sistema":
        obter_contexto_escola(sessao, professor_logado.id_prof, turma.fk_Escola_id_escola)
    return {
        "id_turma": turma.id_turma,
        "nome_turma": turma.nome_turma,
        "serie_ano": getattr(turma, "serie_ano", None),
        "letra": getattr(turma, "letra", None),
        "horario": getattr(turma, "horario", None),
        "id_prof": turma.id_prof,
        "id_escola": turma.fk_Escola_id_escola,
    }
