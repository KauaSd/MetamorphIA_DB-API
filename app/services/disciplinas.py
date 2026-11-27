from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Optional
import unicodedata

from database import PeiDisciplina, Session, Turma, User_esc, pei_esta_valido, select

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
    "ed_fisica": "educacao fisica",
    "educacao fisica": "educacao fisica",
}


def normalizar_chave_disciplina(nome: str) -> str:
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFKD", (nome or "").strip().lower())
        if not unicodedata.combining(c)
    )
    limpo = re.sub(r"[\s_]+", " ", sem_acento).strip()
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


def _parse_tags_disciplinas(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return []
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [p.strip() for p in txt.split(",") if p.strip()]
    return []


def obter_disciplinas_professor_para_aluno(
    sessao: Session, aluno: Any, professor: Any
) -> list[str]:
    """Resolve a lista de disciplinas atribuídas ao professor no contexto da escola do aluno."""
    tags: list[str] = []
    if getattr(aluno, "fk_Turma_id_turma", None):
        turma = sessao.get(Turma, aluno.fk_Turma_id_turma)
        if turma:
            vinc = sessao.execute(
                select(User_esc).where(
                    User_esc.fk_Usuario_id_usuario == professor.id_usuario,
                    User_esc.fk_Escola_id_escola == turma.fk_Escola_id_escola,
                )
            ).scalars().first()
            if vinc and vinc.tags_areas:
                tags = _parse_tags_disciplinas(vinc.tags_areas)
    if not tags:
        tags = _parse_tags_disciplinas(getattr(professor, "tags_usuario", None))
    # Deduplica preservando ordem
    vistas: set[str] = set()
    saida: list[str] = []
    for t in tags:
        ch = normalizar_chave_disciplina(t)
        if ch and ch not in vistas:
            vistas.add(ch)
            saida.append(t)
    return saida


def avaliar_conclusao_peis_professor(
    sessao: Session, aluno: Any, professor: Any
) -> dict[str, Any]:
    """Verifica se todas as disciplinas do professor possuem PEI concluído e válido para o aluno."""
    disciplinas_exigidas = obter_disciplinas_professor_para_aluno(sessao, aluno, professor)
    pei_valido = pei_esta_valido(aluno)

    regs = (
        sessao.execute(
            select(PeiDisciplina).where(PeiDisciplina.id_aluno == aluno.id_aluno)
        )
        .scalars()
        .all()
    )
    chaves_concluidas = {
        normalizar_chave_disciplina(r.disciplina)
        for r in regs
        if r.status == "concluido"
    }

    if not disciplinas_exigidas:
        return {
            "todos_peis_concluidos": bool(pei_valido),
            "disciplinas_exigidas": [],
            "disciplinas_concluidas": [r.disciplina for r in regs if r.status == "concluido"] if pei_valido else [],
            "disciplinas_pendentes": [],
        }

    concluidas: list[str] = []
    pendentes: list[str] = []
    for disc in disciplinas_exigidas:
        if pei_valido and normalizar_chave_disciplina(disc) in chaves_concluidas:
            concluidas.append(disc)
        else:
            pendentes.append(disc)

    return {
        "todos_peis_concluidos": len(pendentes) == 0 and bool(pei_valido),
        "disciplinas_exigidas": disciplinas_exigidas,
        "disciplinas_concluidas": concluidas,
        "disciplinas_pendentes": pendentes,
    }
