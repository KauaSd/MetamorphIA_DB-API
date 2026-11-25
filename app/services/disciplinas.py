from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional
import unicodedata

from database import PeiDisciplina, Session, select

CATALOGO_DISCIPLINAS: list[dict[str, str]] = [
    {"id": "mat", "nome": "Matemática"},
    {"id": "por", "nome": "L. Portuguesa"},
    {"id": "cie", "nome": "Ciências"},
    {"id": "ing", "nome": "L. Inglesa"},
    {"id": "his", "nome": "História"},
    {"id": "geo", "nome": "Geografia"},
    {"id": "art", "nome": "Arte"},
    {"id": "edf", "nome": "Educação Física"},
    {"id": "fil", "nome": "Filosofia"},
    {"id": "soc", "nome": "Sociologia"},
    {"id": "bio", "nome": "Biologia"},
    {"id": "fis", "nome": "Física"},
    {"id": "qui", "nome": "Química"},
    {"id": "ens", "nome": "Ensino Religioso"},
]

_ALIASES_DISCIPLINA: dict[str, str] = {
    "lingua portuguesa": "l. portuguesa",
    "l portuguesa": "l. portuguesa",
    "portugues": "l. portuguesa",
    "lingua inglesa": "l. inglesa",
    "l inglesa": "l. inglesa",
    "ingles": "l. inglesa",
    "artes": "arte",
    "ed fisica": "educacao fisica",
    "ed. fisica": "educacao fisica",
}


def normalizar_chave_disciplina(nome: str) -> str:
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFKD", (nome or "").strip().lower())
        if not unicodedata.combining(c)
    )
    limpo = re.sub(r"\s+", " ", sem_acento).strip()
    return _ALIASES_DISCIPLINA.get(limpo, limpo)


def registrar_status_pei_disciplina(
    sessao: Session,
    id_aluno: int,
    id_prof: int,
    disciplina: Optional[str],
    status_pei: str,
    pei_id: Optional[str] = None,
) -> None:
    if not disciplina or not disciplina.strip():
        return
    chave = normalizar_chave_disciplina(disciplina)
    if not chave:
        return

    existentes = (
        sessao.execute(
            select(PeiDisciplina).where(PeiDisciplina.id_aluno == id_aluno)
        )
        .scalars()
        .all()
    )
    alvo = next(
        (item for item in existentes if normalizar_chave_disciplina(item.disciplina) == chave),
        None,
    )
    agora = datetime.now(timezone.utc)
    if alvo:
        if status_pei == "em_andamento" and alvo.status == "concluido":
            return
        alvo.status = status_pei
        alvo.disciplina = disciplina.strip()
        alvo.id_prof = id_prof
        if pei_id:
            alvo.pei_id = pei_id
        alvo.atualizado_em = agora
    else:
        sessao.add(
            PeiDisciplina(
                id_aluno=id_aluno,
                id_prof=id_prof,
                disciplina=disciplina.strip(),
                status=status_pei,
                pei_id=pei_id,
                atualizado_em=agora,
            )
        )


def listar_status_pei_disciplinas(sessao: Session, id_aluno: int) -> list[dict[str, Any]]:
    regs = (
        sessao.execute(
            select(PeiDisciplina)
            .where(PeiDisciplina.id_aluno == id_aluno)
            .order_by(PeiDisciplina.atualizado_em.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "disciplina": r.disciplina,
            "status": r.status,
            "pei_id": r.pei_id,
            "atualizado_em": r.atualizado_em.isoformat() if r.atualizado_em else None,
        }
        for r in regs
    ]
