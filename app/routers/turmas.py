from database import Session, TurmaProfessor, User_esc, Usuario, pegar_bd, professores, select, turmas
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, status
from schemas.schemas import Turma, TurmaSchema, VincularProfessorTurmaRequest
from services.planos import listar_escolas_usuario, obter_contexto_escola
from services.turma import (
    AdicionarTurma,
    DeletaTurma,
    EditarTurma,
    PesquisarTurma,
    _normalizar_disciplinas_lista,
    obter_disciplinas_turma_para_usuario,
    parsear_disciplinas_turma,
)
import json

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
            "disciplinas": obter_disciplinas_turma_para_usuario(sessao, t, professor_logado.id_prof),
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
        "disciplinas": obter_disciplinas_turma_para_usuario(sessao, turma, professor_logado.id_prof),
    }


@Turma_router.get("/{id_turma}/professores")
def listar_professores_da_turma(
    id_turma: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    turma = sessao.get(turmas, id_turma)
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    if professor_logado.tipo_usuario != "adm_sistema":
        obter_contexto_escola(sessao, professor_logado.id_prof, turma.fk_Escola_id_escola)
    vinculos = sessao.execute(
        select(TurmaProfessor).where(TurmaProfessor.fk_Turma_id_turma == id_turma)
    ).scalars().all()
    resultado = []
    for v in vinculos:
        u = sessao.get(Usuario, v.fk_Usuario_id_usuario)
        if not u:
            continue
        resultado.append({
            "id_usuario": u.id_usuario,
            "nome_usuario": u.nome_usuario,
            "email_usuario": u.email_usuario,
            "disciplinas": parsear_disciplinas_turma(v.disciplinas_json),
        })
    return resultado


@Turma_router.put("/{id_turma}/professores")
def vincular_professor_turma(
    id_turma: int,
    dados: VincularProfessorTurmaRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    turma = sessao.get(turmas, id_turma)
    if not turma:
        raise HTTPException(status_code=404, detail="Turma não encontrada")
    ctx = obter_contexto_escola(sessao, professor_logado.id_prof, turma.fk_Escola_id_escola)
    if ctx["papel"] not in ("adm", "adm_sistema"):
        raise HTTPException(status_code=403, detail="Apenas o administrador da escola pode vincular professores à turma.")

    alvo = None
    if dados.id_usuario:
        alvo = sessao.get(Usuario, dados.id_usuario)
    elif dados.email:
        alvo = sessao.execute(
            select(Usuario).where(Usuario.email_usuario == dados.email.strip().lower())
        ).scalars().first()
    if not alvo:
        raise HTTPException(status_code=404, detail="Professor não encontrado.")

    discs = _normalizar_disciplinas_lista(dados.disciplinas)
    vinc = sessao.execute(
        select(TurmaProfessor).where(
            TurmaProfessor.fk_Turma_id_turma == id_turma,
            TurmaProfessor.fk_Usuario_id_usuario == alvo.id_usuario,
        )
    ).scalars().first()
    if vinc:
        vinc.disciplinas_json = json.dumps(discs, ensure_ascii=False)
    else:
        vinc = TurmaProfessor(
            fk_Turma_id_turma=id_turma,
            fk_Usuario_id_usuario=alvo.id_usuario,
            disciplinas_json=json.dumps(discs, ensure_ascii=False),
        )
        sessao.add(vinc)
    sessao.commit()
    return {
        "mensagem": "Disciplinas do professor na turma atualizadas com sucesso.",
        "id_turma": id_turma,
        "id_usuario": alvo.id_usuario,
        "disciplinas": discs,
    }
