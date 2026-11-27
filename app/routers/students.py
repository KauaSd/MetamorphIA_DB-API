from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, List, Literal, Optional
import uuid

from database import (
    AlunoMemoriaVetorial,
    ArquivoAnexo,
    Session,
    Turma,
    User_esc,
    VALIDADE_PEI_DIAS,
    alunos,
    conversas,
    delete,
    engine,
    mensagem_al,
    mensagens,
    pegar_bd,
    pei_esta_valido,
    professores,
    select,
)
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from schemas.schemas import Aluno, Alunoschema, EditaAlunoSchema, PesquisaAluno
from services.disciplinas import listar_status_pei_disciplinas, registrar_status_pei_disciplina
from services.planos import listar_escolas_usuario, obter_contexto_escola
from services.storage import (
    excluir_arquivos_por_conversa,
    extrair_texto_docx_bytes_storage,
    ler_bytes_registro_anexo,
    salvar_arquivo_anexo,
)
from services.students import (
    ConsultaAluno,
    DeletaAluno,
    EditaAluno,
    RecebeAluno,
)

Student_router = APIRouter(prefix="/Alunos", tags=["Alunos"])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class AtualizarDescricaoRequest(BaseModel):
    desc_aluno: Optional[str] = Field(default=None, max_length=10000)
    perfil_ia: Optional[str] = Field(default=None, max_length=15000)
    indicadores_desenvolvimento: Optional[list[dict[str, Any]]] = None
    metas_bimestre: Optional[list[dict[str, Any]]] = None
    pei_feito: Optional[bool] = None
    renovar_validade_pei_dias: Optional[int] = Field(default=None, ge=1, le=365)


class SalvarPeiArquivoRequest(BaseModel):
    pei_id: Optional[str] = Field(default=None, max_length=64)
    arquivo_nome: str = Field(..., max_length=255)
    documento_docx_base64: str
    componente_curricular: Optional[str] = Field(default=None, max_length=120)
    perfil_ia: Optional[str] = Field(default=None, max_length=15000)
    desc_aluno: Optional[str] = Field(default=None, max_length=10000)
    indicadores_desenvolvimento: Optional[list[dict[str, Any]]] = None
    metas_bimestre: Optional[list[dict[str, Any]]] = None
    validade_dias: int = Field(default=VALIDADE_PEI_DIAS, ge=1, le=365)


class RegistrarTurnoConversaRequest(BaseModel):
    conversa_id: str = Field(..., max_length=100)
    titulo: Optional[str] = Field(default=None, max_length=100)
    mensagem_usuario: str = ""
    resposta_ia: str = ""
    anexos_usuario: Optional[list[dict[str, Any]]] = None
    anexos_ia: Optional[list[dict[str, Any]]] = None


def _validar_acesso_escola_aluno(
    sessao: Session,
    professor_logado: professores,
    aluno_obj: alunos,
    exigir_pode_chat: bool = False,
) -> None:
    if exigir_pode_chat and getattr(professor_logado, "tipo_usuario", "normal") == "adm_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O administrador institucional não possui permissão pedagógica de chat/elaboração de PEI.",
        )
    turma = sessao.get(Turma, aluno_obj.fk_Turma_id_turma) if aluno_obj.fk_Turma_id_turma else None
    if professor_logado.tipo_usuario == "adm_sistema":
        return
    if turma:
        ctx = obter_contexto_escola(sessao, professor_logado.id_prof, turma.fk_Escola_id_escola)
        if exigir_pode_chat and not ctx.get("pode_chat", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Este perfil está configurado sem permissão de chat/elaboração pedagógica nesta escola.",
            )
    elif aluno_obj.id_prof != professor_logado.id_prof:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar este aluno.",
        )


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


@Student_router.put("/{id_aluno}")
def EditarPorId(
    id_aluno: int,
    form: Aluno,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return EditaAluno(EditaAlunoSchema(id=id_aluno), form, sessao, professor_logado.id_prof)


@Student_router.patch("/{id_aluno}/descricao")
def AtualizarDescricaoAluno(
    id_aluno: int,
    payload: AtualizarDescricaoRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    if payload.desc_aluno is not None:
        aluno.desc_aluno = payload.desc_aluno
    if payload.perfil_ia is not None:
        aluno.perfil_ia = payload.perfil_ia
    elif payload.desc_aluno is not None and not aluno.perfil_ia:
        aluno.perfil_ia = payload.desc_aluno
    if payload.indicadores_desenvolvimento is not None:
        aluno.indicadores_desenvolvimento_json = json.dumps(
            payload.indicadores_desenvolvimento, ensure_ascii=False
        )
    if payload.metas_bimestre is not None:
        aluno.metas_bimestre_json = json.dumps(
            payload.metas_bimestre, ensure_ascii=False
        )

    if payload.pei_feito is not None:
        aluno.pei_feito = bool(payload.pei_feito)
        if aluno.pei_feito:
            dias = payload.renovar_validade_pei_dias or VALIDADE_PEI_DIAS
            aluno.pei_valido_ate = datetime.now(timezone.utc) + timedelta(days=dias)
        else:
            aluno.pei_valido_ate = None
    elif payload.renovar_validade_pei_dias is not None and aluno.pei_feito:
        aluno.pei_valido_ate = datetime.now(timezone.utc) + timedelta(days=payload.renovar_validade_pei_dias)

    sessao.commit()
    sessao.refresh(aluno)
    return {
        "id_aluno": aluno.id_aluno,
        "desc_aluno": aluno.desc_aluno,
        "perfil_ia": aluno.perfil_ia,
        "pei_feito": bool(aluno.pei_feito),
        "pei_valido_ate": aluno.pei_valido_ate.isoformat() if aluno.pei_valido_ate else None,
        "pei_ativo": pei_esta_valido(aluno),
    }


@Student_router.post("/{id_aluno}/pei-arquivo", status_code=status.HTTP_201_CREATED)
def SalvarPeiArquivoAluno(
    id_aluno: int,
    payload: SalvarPeiArquivoRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    pei_id = (payload.pei_id or str(uuid.uuid4())).strip()
    reg_existente = sessao.get(ArquivoAnexo, pei_id)
    if not reg_existente:
        meta = salvar_arquivo_anexo(
            sessao=sessao,
            id_prof=professor_logado.id_prof,
            id_aluno=id_aluno,
            id_conversa="PEI",
            nome_arquivo=payload.arquivo_nome,
            mime_type=DOCX_MEDIA_TYPE,
            data_url_ou_b64=payload.documento_docx_base64,
            file_id_override=pei_id,
            download_url_override=f"/AI/pei/aluno/{id_aluno}/{pei_id}/docx",
        )
        if not meta:
            raise HTTPException(status_code=400, detail="Arquivo .docx do PEI inválido ou vazio.")

    if payload.desc_aluno is not None and not aluno.desc_aluno:
        aluno.desc_aluno = payload.desc_aluno
    if payload.perfil_ia:
        aluno.perfil_ia = payload.perfil_ia
    if payload.indicadores_desenvolvimento is not None:
        aluno.indicadores_desenvolvimento_json = json.dumps(
            payload.indicadores_desenvolvimento, ensure_ascii=False
        )
    if payload.metas_bimestre is not None:
        aluno.metas_bimestre_json = json.dumps(
            payload.metas_bimestre, ensure_ascii=False
        )
    if payload.componente_curricular:
        registrar_status_pei_disciplina(
            sessao=sessao,
            id_aluno=id_aluno,
            id_prof=professor_logado.id_prof,
            disciplina=payload.componente_curricular,
            status_pei="concluido",
            pei_id=pei_id,
        )
    aluno.pei_feito = True
    aluno.pei_valido_ate = datetime.now(timezone.utc) + timedelta(days=payload.validade_dias or VALIDADE_PEI_DIAS)

    sessao.commit()
    sessao.refresh(aluno)
    return {
        "pei_id": pei_id,
        "id_aluno": id_aluno,
        "arquivo_nome": payload.arquivo_nome,
        "pei_feito": True,
        "pei_valido_ate": aluno.pei_valido_ate.isoformat() if aluno.pei_valido_ate else None,
        "pei_ativo": True,
        "download_url": f"/AI/pei/aluno/{id_aluno}/{pei_id}/docx",
    }


class PeiDisciplinaStatusRequest(BaseModel):
    disciplina: str = Field(..., max_length=120)
    status: str = Field(default="em_andamento", max_length=30)
    pei_id: Optional[str] = Field(default=None, max_length=64)


@Student_router.post("/{id_aluno}/pei-disciplina")
def AtualizarPeiDisciplinaAluno(
    id_aluno: int,
    payload: PeiDisciplinaStatusRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)
    status_val = payload.status if payload.status in ("concluido", "em_andamento", "nao_iniciado") else "em_andamento"
    registrar_status_pei_disciplina(
        sessao=sessao,
        id_aluno=id_aluno,
        id_prof=professor_logado.id_prof,
        disciplina=payload.disciplina,
        status_pei=status_val,
        pei_id=payload.pei_id,
    )
    sessao.commit()
    return {"id_aluno": id_aluno, "disciplina": payload.disciplina, "status": status_val}


@Student_router.get("/{id_aluno}/pei-arquivos")
def ListarPeiArquivosAluno(
    id_aluno: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=False)

    regs = (
        sessao.execute(
            select(ArquivoAnexo)
            .where(ArquivoAnexo.id_aluno == id_aluno, ArquivoAnexo.id_conversa == "PEI")
            .order_by(ArquivoAnexo.criado_em.desc())
        )
        .scalars()
        .all()
    )
    validade_str = aluno.pei_valido_ate.strftime("%d/%m/%Y") if aluno.pei_valido_ate else "N/A"
    status_txt = f"Válido até {validade_str}" if pei_esta_valido(aluno) else "Expirado"
    return [
        {
            "pei_id": r.id_arquivo,
            "data": r.criado_em.isoformat() if r.criado_em else "",
            "resumo": f"{r.nome_arquivo} ({status_txt})",
            "arquivo_nome": r.nome_arquivo,
            "download_url": f"/AI/pei/aluno/{id_aluno}/{r.id_arquivo}/docx",
        }
        for r in regs
    ]


@Student_router.get("/{id_aluno}/pei-arquivos/{pei_id}")
def ObterDetalhePeiArquivoAluno(
    id_aluno: int,
    pei_id: str,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=False)

    reg = sessao.get(ArquivoAnexo, pei_id)
    if not reg or reg.id_aluno != id_aluno or reg.id_conversa != "PEI":
        raise HTTPException(status_code=404, detail="PEI não encontrado para este aluno.")

    docx_bytes = ler_bytes_registro_anexo(reg)
    texto_extraido = extrair_texto_docx_bytes_storage(docx_bytes)
    return {
        "pei_id": reg.id_arquivo,
        "id_aluno": id_aluno,
        "documento_gerado": texto_extraido or reg.nome_arquivo,
        "data": reg.criado_em.isoformat() if reg.criado_em else "",
    }


@Student_router.get("/{id_aluno}/pei-arquivos/{pei_id}/docx")
def BaixarPeiArquivoDocxAluno(
    id_aluno: int,
    pei_id: str,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
) -> Response:
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=False)

    reg = sessao.get(ArquivoAnexo, pei_id)
    if not reg or reg.id_aluno != id_aluno or reg.id_conversa != "PEI":
        raise HTTPException(status_code=404, detail="PEI não encontrado para este aluno.")

    docx_bytes = ler_bytes_registro_anexo(reg)
    nome_seguro = (reg.nome_arquivo or f"PEI_aluno_{id_aluno}.docx").replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=docx_bytes,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{nome_seguro}"',
            "X-Pei-Id": reg.id_arquivo,
        },
    )


@Student_router.get("/{id_aluno}/conversas-db")
def ListarConversasAlunoDB(
    id_aluno: int,
    incluir_metricas: bool = False,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=not incluir_metricas)

    pode_ver_conversas = (
        getattr(professor_logado, "tipo_usuario", "normal") != "adm_institucional"
    )
    if aluno.fk_Turma_id_turma and professor_logado.tipo_usuario != "adm_sistema":
        turma = sessao.get(Turma, aluno.fk_Turma_id_turma)
        if turma:
            ctx = obter_contexto_escola(sessao, professor_logado.id_prof, turma.fk_Escola_id_escola)
            pode_ver_conversas = pode_ver_conversas and bool(ctx.get("pode_chat", False))

    lista_convs = []
    if pode_ver_conversas:
        convs = (
            sessao.execute(
                select(conversas)
                .where(
                    conversas.id_aluno == id_aluno,
                    conversas.id_prof == professor_logado.id_prof,
                )
                .order_by(conversas.atualizado_em.desc())
            )
            .scalars()
            .all()
        )
        lista_convs = [
            {
                "conversa_id": c.id_conversa,
                "titulo": c.titulo or "",
                "data": c.atualizado_em.isoformat() if c.atualizado_em else "",
            }
            for c in convs
        ]

    if not incluir_metricas:
        return lista_convs

    msgs_ia = (
        sessao.execute(
            select(mensagens).where(
                mensagens.id_aluno == id_aluno,
                mensagens.role == "assistant",
            )
        )
        .scalars()
        .all()
    )
    adaptadas = sum(
        1
        for m in msgs_ia
        if m.anexo_mensagem
        or any(k in (m.conteudo or "").lower() for k in ("adapta", "estratégia", "recurso", "visual"))
    )
    engajamento = min(95, max(50, 60 + len(msgs_ia) * 3)) if msgs_ia else (65 if pei_esta_valido(aluno) else 50)
    return {
        "conversas": lista_convs,
        "atividades_adaptadas": adaptadas,
        "engajamento_percent": engajamento,
        "total_respostas_ia": len(msgs_ia),
    }


def _serializar_mensagens_conversa(
    sessao: Session,
    conversa_id: str,
    id_aluno: int,
    id_prof: int,
) -> list[dict[str, Any]]:
    """Busca e serializa as mensagens de uma conversa em ordem cronológica."""
    msgs = (
        sessao.execute(
            select(mensagens)
            .where(
                mensagens.id_conversa == conversa_id,
                mensagens.id_aluno == id_aluno,
                mensagens.id_prof == id_prof,
            )
            .order_by(mensagens.data_mensagem.asc())
        )
        .scalars()
        .all()
    )
    saida: list[dict[str, Any]] = []
    for m in msgs:
        anexos_parsed = None
        if m.anexo_mensagem:
            try:
                anexos_parsed = json.loads(m.anexo_mensagem)
            except Exception:
                anexos_parsed = None
        saida.append(
            {
                "role": m.role or "user",
                "conteudo": m.conteudo or "",
                "data": m.data_mensagem.isoformat() if m.data_mensagem else "",
                "anexos": anexos_parsed,
            }
        )
    return saida


@Student_router.get("/{id_aluno}/conversas-db/{conversa_id}")
def ObterMensagensConversaAlunoDB(
    id_aluno: int,
    conversa_id: str,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    conv = sessao.get(conversas, conversa_id)
    if conv and conv.id_prof != professor_logado.id_prof:
        raise HTTPException(status_code=403, detail="Esta conversa pertence a outro professor.")

    saida = _serializar_mensagens_conversa(sessao, conversa_id, id_aluno, professor_logado.id_prof)
    return {"conversa_id": conversa_id, "mensagens": saida}


@Student_router.post("/{id_aluno}/conversas-db", status_code=status.HTTP_201_CREATED)
def RegistrarTurnoConversaAlunoDB(
    id_aluno: int,
    payload: RegistrarTurnoConversaRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    conv = sessao.get(conversas, payload.conversa_id)
    if conv and conv.id_prof != professor_logado.id_prof:
        raise HTTPException(status_code=403, detail="Esta conversa pertence a outro professor.")

    if not conv:
        conv = conversas(
            id_conversa=payload.conversa_id,
            id_aluno=id_aluno,
            id_prof=professor_logado.id_prof,
            titulo=(payload.titulo or payload.mensagem_usuario[:50] or "Nova conversa")[:100],
        )
        sessao.add(conv)
        sessao.flush()
    else:
        conv.atualizado_em = datetime.now(timezone.utc)

    anexos_u_meta = []
    for ax in payload.anexos_usuario or []:
        meta = salvar_arquivo_anexo(
            sessao=sessao,
            id_prof=professor_logado.id_prof,
            id_aluno=id_aluno,
            id_conversa=payload.conversa_id,
            nome_arquivo=ax.get("name", "anexo"),
            mime_type=ax.get("type", "application/octet-stream"),
            data_url_ou_b64=ax.get("dataUrl"),
        )
        anexos_u_meta.append(meta or {"name": ax.get("name", "anexo"), "type": ax.get("type"), "size": ax.get("size", 0)})

    msg_u = mensagens(
        id_prof=professor_logado.id_prof,
        id_aluno=id_aluno,
        id_conversa=payload.conversa_id,
        conteudo=payload.mensagem_usuario,
        anexo_mensagem=json.dumps(anexos_u_meta, ensure_ascii=False) if anexos_u_meta else None,
        role="user",
    )
    sessao.add(msg_u)
    sessao.flush()
    sessao.execute(mensagem_al.insert().values(id_aluno=id_aluno, id_mensagem=msg_u.id_mensagem))

    anexos_ia_meta = []
    for ax in payload.anexos_ia or []:
        meta = salvar_arquivo_anexo(
            sessao=sessao,
            id_prof=professor_logado.id_prof,
            id_aluno=id_aluno,
            id_conversa=payload.conversa_id,
            nome_arquivo=ax.get("name", "atividade"),
            mime_type=ax.get("type", "application/octet-stream"),
            data_url_ou_b64=ax.get("dataUrl"),
        )
        anexos_ia_meta.append(meta or {"name": ax.get("name", "atividade"), "type": ax.get("type"), "size": ax.get("size", 0)})

    msg_a = mensagens(
        id_prof=professor_logado.id_prof,
        id_aluno=id_aluno,
        id_conversa=payload.conversa_id,
        conteudo=payload.resposta_ia,
        anexo_mensagem=json.dumps(anexos_ia_meta, ensure_ascii=False) if anexos_ia_meta else None,
        role="assistant",
    )
    sessao.add(msg_a)
    sessao.flush()
    sessao.execute(mensagem_al.insert().values(id_aluno=id_aluno, id_mensagem=msg_a.id_mensagem))
    sessao.commit()
    return {"conversa_id": payload.conversa_id, "persistido": True}


@Student_router.delete("/{id_aluno}/conversas-db/{conversa_id}")
def DeletarConversaAlunoDB(
    id_aluno: int,
    conversa_id: str,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    conv = sessao.get(conversas, conversa_id)
    if conv and conv.id_prof != professor_logado.id_prof:
        raise HTTPException(status_code=403, detail="Esta conversa pertence a outro professor.")

    msgs = (
        sessao.execute(
            select(mensagens).where(
                mensagens.id_conversa == conversa_id,
                mensagens.id_prof == professor_logado.id_prof,
            )
        )
        .scalars()
        .all()
    )
    msg_ids = [m.id_mensagem for m in msgs]
    if msg_ids:
        sessao.execute(delete(mensagem_al).where(mensagem_al.c.id_mensagem.in_(msg_ids)))
        sessao.execute(delete(mensagens).where(mensagens.id_mensagem.in_(msg_ids)))
    if conv:
        sessao.delete(conv)
    sessao.execute(
        delete(AlunoMemoriaVetorial).where(
            AlunoMemoriaVetorial.id_aluno == id_aluno,
            AlunoMemoriaVetorial.conversa_id == conversa_id,
        )
    )
    excluir_arquivos_por_conversa(sessao, conversa_id, professor_logado.id_prof)
    sessao.commit()
    return {"mensagem": "Conversa removida com sucesso.", "conversa_id": conversa_id, "documentos_removidos": len(msg_ids)}


_MESES_PT_BUSCA = (
    "",
    "jan janeiro",
    "fev fevereiro",
    "mar março marco",
    "abr abril",
    "mai maio",
    "jun junho",
    "jul julho",
    "ago agosto",
    "set setembro",
    "out outubro",
    "nov novembro",
    "dez dezembro",
)


def _obter_alunos_permitidos_chat(
    sessao: Session,
    professor_logado: professores,
    ids_solicitados: Optional[list[int]] = None,
) -> list[alunos]:
    """Retorna os alunos acessíveis para chat/conversas pelo usuário autenticado."""
    if getattr(professor_logado, "tipo_usuario", "normal") == "adm_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O administrador institucional não possui permissão pedagógica de chat/conversas.",
        )

    stmt_alunos = select(alunos)
    if ids_solicitados:
        stmt_alunos = stmt_alunos.where(alunos.id_aluno.in_(ids_solicitados))

    if professor_logado.tipo_usuario != "adm_sistema":
        escolas_chat = select(User_esc.fk_Escola_id_escola).where(
            User_esc.fk_Usuario_id_usuario == professor_logado.id_prof,
            User_esc.pode_chat.is_(True),
        )
        turmas_chat = select(Turma.id_turma).where(Turma.fk_Escola_id_escola.in_(escolas_chat))
        stmt_alunos = stmt_alunos.where(
            (alunos.id_prof == professor_logado.id_prof)
            | (alunos.fk_Turma_id_turma.in_(turmas_chat))
        )

    return sessao.execute(stmt_alunos).scalars().all()


def listar_conversas_em_lote_para_usuario(
    sessao: Session,
    professor_logado: professores,
    aluno_ids_raw: Optional[str] = None,
) -> dict[str, list[dict[str, str]]]:
    """Busca conversas de múltiplos alunos em lote com uma única query e validação de acesso."""
    ids_solicitados: list[int] = []
    if aluno_ids_raw:
        for parte in aluno_ids_raw.split(","):
            p = parte.strip()
            if p:
                if not p.isdigit():
                    raise HTTPException(status_code=400, detail=f"ID de aluno inválido: {p}")
                ids_solicitados.append(int(p))

    alunos_permitidos = _obter_alunos_permitidos_chat(sessao, professor_logado, ids_solicitados or None)
    ids_permitidos = [a.id_aluno for a in alunos_permitidos]

    if ids_solicitados and len(ids_permitidos) < len(set(ids_solicitados)):
        # Verifica se algum ID solicitado existe mas o usuário não tem acesso
        faltantes = set(ids_solicitados) - set(ids_permitidos)
        existentes_sem_acesso = sessao.execute(
            select(alunos.id_aluno).where(alunos.id_aluno.in_(faltantes))
        ).scalars().all()
        if existentes_sem_acesso:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para acessar conversas de um ou mais alunos solicitados.",
            )

    agrupado: dict[str, list[dict[str, str]]] = {str(aid): [] for aid in ids_permitidos}
    if not ids_permitidos:
        return agrupado

    convs = (
        sessao.execute(
            select(conversas)
            .where(
                conversas.id_aluno.in_(ids_permitidos),
                conversas.id_prof == professor_logado.id_prof,
            )
            .order_by(conversas.atualizado_em.desc())
        )
        .scalars()
        .all()
    )
    for c in convs:
        chave = str(c.id_aluno)
        if chave in agrupado:
            agrupado[chave].append(
                {
                    "conversa_id": c.id_conversa,
                    "titulo": c.titulo or "",
                    "data": c.atualizado_em.isoformat() if c.atualizado_em else "",
                }
            )
    return agrupado


def listar_conversas_recentes_para_usuario(
    sessao: Session,
    professor_logado: professores,
    limit: Optional[int] = None,
    offset: int = 0,
    busca: Optional[str] = None,
    ordenar_por: Literal["data", "aluno", "titulo"] = "data",
    ordem: Literal["desc", "asc"] = "desc",
) -> list[dict[str, Any]]:
    """Lista conversas recentes do professor em ordem global, enriquecidas com aluno e turma."""
    alunos_permitidos = _obter_alunos_permitidos_chat(sessao, professor_logado)
    if not alunos_permitidos:
        return []

    mapa_alunos = {a.id_aluno: a for a in alunos_permitidos}
    turma_ids = {a.fk_Turma_id_turma for a in alunos_permitidos if a.fk_Turma_id_turma}
    mapa_turmas: dict[int, str] = {}
    if turma_ids:
        turmas = sessao.execute(select(Turma).where(Turma.id_turma.in_(turma_ids))).scalars().all()
        mapa_turmas = {t.id_turma: t.nome_turma for t in turmas}

    convs = (
        sessao.execute(
            select(conversas)
            .where(
                conversas.id_aluno.in_(list(mapa_alunos.keys())),
                conversas.id_prof == professor_logado.id_prof,
            )
            .order_by(conversas.atualizado_em.desc())
        )
        .scalars()
        .all()
    )

    termo = (busca or "").strip().lower().replace(".", "")
    itens: list[dict[str, Any]] = []
    for c in convs:
        aluno = mapa_alunos.get(c.id_aluno)
        if not aluno:
            continue
        nome_turma = mapa_turmas.get(aluno.fk_Turma_id_turma) if aluno.fk_Turma_id_turma else None
        dt = c.atualizado_em
        data_iso = dt.isoformat() if dt else ""

        if termo:
            mes_txt = _MESES_PT_BUSCA[dt.month] if dt and 1 <= dt.month <= 12 else ""
            ano_txt = str(dt.year) if dt else ""
            campos_busca = " ".join(
                filter(
                    None,
                    [
                        c.titulo or "",
                        aluno.nome_aluno or "",
                        aluno.neuro_aluno or "",
                        nome_turma or "",
                        data_iso,
                        mes_txt,
                        ano_txt,
                    ],
                )
            ).lower()
            if not all(parte in campos_busca for parte in termo.split()):
                continue

        itens.append(
            {
                "conversa_id": c.id_conversa,
                "titulo": c.titulo or "",
                "data": data_iso,
                "id_aluno": aluno.id_aluno,
                "nome_aluno": aluno.nome_aluno or "",
                "neuro_aluno": aluno.neuro_aluno or "",
                "id_turma": aluno.fk_Turma_id_turma,
                "nome_turma": nome_turma,
            }
        )

    reverso = ordem == "desc"
    if ordenar_por == "aluno":
        itens.sort(key=lambda x: (x["nome_aluno"].lower(), x["data"]), reverse=reverso)
    elif ordenar_por == "titulo":
        itens.sort(key=lambda x: (x["titulo"].lower(), x["data"]), reverse=reverso)
    else:
        itens.sort(key=lambda x: x["data"], reverse=reverso)

    if offset > 0:
        itens = itens[offset:]
    if limit is not None:
        itens = itens[:limit]
    return itens


@Student_router.get("/conversas-lote")
def ListarConversasEmLoteDB(
    aluno_ids: Optional[str] = None,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return listar_conversas_em_lote_para_usuario(sessao, professor_logado, aluno_ids)


@Student_router.get("/conversas-recentes")
def ListarConversasRecentesDB(
    limit: Optional[int] = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    busca: Optional[str] = Query(default=None, max_length=120),
    ordenar_por: Literal["data", "aluno", "titulo"] = "data",
    ordem: Literal["desc", "asc"] = "desc",
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return listar_conversas_recentes_para_usuario(
        sessao=sessao,
        professor_logado=professor_logado,
        limit=limit,
        offset=offset,
        busca=busca,
        ordenar_por=ordenar_por,
        ordem=ordem,
    )


def obter_conversa_por_id_para_usuario(
    sessao: Session,
    professor_logado: professores,
    conversa_id: str,
) -> dict[str, Any]:
    """Retorna os metadados da conversa e suas mensagens diretamente pelo conversa_id."""
    if getattr(professor_logado, "tipo_usuario", "normal") == "adm_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O administrador institucional não possui permissão pedagógica de chat/conversas.",
        )

    conv = sessao.get(conversas, conversa_id)
    if not conv or conv.id_prof != professor_logado.id_prof:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    aluno = sessao.get(alunos, conv.id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno da conversa não encontrado.")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    nome_turma = None
    if aluno.fk_Turma_id_turma:
        turma = sessao.get(Turma, aluno.fk_Turma_id_turma)
        if turma:
            nome_turma = turma.nome_turma

    mensagens_conv = _serializar_mensagens_conversa(
        sessao=sessao,
        conversa_id=conversa_id,
        id_aluno=aluno.id_aluno,
        id_prof=professor_logado.id_prof,
    )
    return {
        "conversa_id": conv.id_conversa,
        "titulo": conv.titulo or "",
        "data": conv.atualizado_em.isoformat() if conv.atualizado_em else "",
        "id_aluno": aluno.id_aluno,
        "nome_aluno": aluno.nome_aluno or "",
        "neuro_aluno": aluno.neuro_aluno or "",
        "id_turma": aluno.fk_Turma_id_turma,
        "nome_turma": nome_turma,
        "pei_ativo": bool(aluno.pei_ativo),
        "mensagens": mensagens_conv,
    }


@Student_router.get("/conversas/{conversa_id}")
def ObterConversaPorIdDB(
    conversa_id: str,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return obter_conversa_por_id_para_usuario(
        sessao=sessao,
        professor_logado=professor_logado,
        conversa_id=conversa_id,
    )


class VetorChunkItem(BaseModel):
    texto: str = Field(..., min_length=1, max_length=6000)
    embedding: List[float] = Field(..., min_length=384, max_length=384)


class SalvarVetoresAlunoRequest(BaseModel):
    origem: Literal["pei", "relato_chat", "cadastro"] = "relato_chat"
    disciplina: Optional[str] = Field(default=None, max_length=120)
    pei_id: Optional[str] = Field(default=None, max_length=64)
    conversa_id: Optional[str] = Field(default=None, max_length=100)
    substituir_origem_disciplina: bool = False
    itens: List[VetorChunkItem] = Field(default_factory=list, max_length=100)


class BuscarVetoresAlunoRequest(BaseModel):
    embedding: List[float] = Field(..., min_length=384, max_length=384)
    top_k: int = Field(default=6, ge=1, le=30)
    disciplina: Optional[str] = Field(default=None, max_length=120)


def _similaridade_cosseno(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


@Student_router.post("/{id_aluno}/vetores", status_code=status.HTTP_201_CREATED)
def SalvarVetoresAluno(
    id_aluno: int,
    payload: SalvarVetoresAlunoRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    from services.disciplinas import normalizar_chave_disciplina

    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=True)

    disc_limpa = payload.disciplina.strip() if payload.disciplina and payload.disciplina.strip() else None
    disc_norm = normalizar_chave_disciplina(disc_limpa) if disc_limpa else None

    if payload.substituir_origem_disciplina:
        existentes_origem = (
            sessao.execute(
                select(AlunoMemoriaVetorial).where(
                    AlunoMemoriaVetorial.id_aluno == id_aluno,
                    AlunoMemoriaVetorial.origem == payload.origem,
                )
            )
            .scalars()
            .all()
        )
        for reg in existentes_origem:
            reg_disc_norm = normalizar_chave_disciplina(reg.disciplina or "") if reg.disciplina else None
            if (disc_norm is None and reg_disc_norm is None) or (disc_norm and reg_disc_norm == disc_norm):
                sessao.delete(reg)
        sessao.flush()

    hashes_existentes = set(
        sessao.execute(
            select(AlunoMemoriaVetorial.hash_chunk).where(AlunoMemoriaVetorial.id_aluno == id_aluno)
        )
        .scalars()
        .all()
    )

    usa_pgvector = engine.dialect.name == "postgresql" and not isinstance(
        AlunoMemoriaVetorial.__table__.c.embedding.type, type(AlunoMemoriaVetorial.__table__.c.texto_chunk.type)
    )

    inseridos = 0
    for item in payload.itens:
        texto_limpo = item.texto.strip()
        if not texto_limpo:
            continue
        chave_hash = hashlib.sha256(
            f"{id_aluno}::{payload.origem}::{disc_norm or ''}::{texto_limpo}".encode("utf-8")
        ).hexdigest()
        if chave_hash in hashes_existentes:
            continue
        hashes_existentes.add(chave_hash)

        vec_floats = [float(x) for x in item.embedding]
        emb_val: Any = vec_floats if usa_pgvector else json.dumps(vec_floats)
        sessao.add(
            AlunoMemoriaVetorial(
                id_aluno=id_aluno,
                id_prof=professor_logado.id_prof,
                origem=payload.origem,
                disciplina=disc_limpa,
                pei_id=payload.pei_id,
                conversa_id=payload.conversa_id,
                texto_chunk=texto_limpo,
                hash_chunk=chave_hash,
                embedding=emb_val,
            )
        )
        inseridos += 1

    sessao.commit()
    return {"id_aluno": id_aluno, "inseridos": inseridos}


@Student_router.post("/{id_aluno}/vetores/busca")
def BuscarVetoresAluno(
    id_aluno: int,
    payload: BuscarVetoresAlunoRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    from services.disciplinas import normalizar_chave_disciplina

    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=False)

    disc_filtro_norm = (
        normalizar_chave_disciplina(payload.disciplina)
        if payload.disciplina and payload.disciplina.strip()
        else None
    )

    disciplinas_pei_rows = (
        sessao.execute(
            select(AlunoMemoriaVetorial.disciplina)
            .where(
                AlunoMemoriaVetorial.id_aluno == id_aluno,
                AlunoMemoriaVetorial.origem == "pei",
                AlunoMemoriaVetorial.disciplina.is_not(None),
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    disciplinas_pei = [d for d in disciplinas_pei_rows if d]

    usa_pgvector = engine.dialect.name == "postgresql" and hasattr(
        AlunoMemoriaVetorial.embedding, "cosine_distance"
    )

    trechos: list[dict[str, Any]] = []
    if usa_pgvector:
        dist_col = AlunoMemoriaVetorial.embedding.cosine_distance(payload.embedding).label("distancia")
        stmt = select(AlunoMemoriaVetorial, dist_col).where(AlunoMemoriaVetorial.id_aluno == id_aluno)
        if disc_filtro_norm:
            stmt = stmt.where(AlunoMemoriaVetorial.disciplina.is_not(None))
        stmt = stmt.order_by(dist_col.asc()).limit(payload.top_k * 2 if disc_filtro_norm else payload.top_k)
        rows = sessao.execute(stmt).all()
        for reg, dist in rows:
            if disc_filtro_norm and normalizar_chave_disciplina(reg.disciplina or "") != disc_filtro_norm:
                continue
            sim = max(0.0, min(1.0, 1.0 - float(dist or 0.0)))
            trechos.append(
                {
                    "id_vetor": reg.id_vetor,
                    "origem": reg.origem,
                    "disciplina": reg.disciplina,
                    "pei_id": reg.pei_id,
                    "texto": reg.texto_chunk,
                    "similaridade": round(sim, 4),
                }
            )
            if len(trechos) >= payload.top_k:
                break
    else:
        regs = (
            sessao.execute(
                select(AlunoMemoriaVetorial).where(AlunoMemoriaVetorial.id_aluno == id_aluno)
            )
            .scalars()
            .all()
        )
        ranqueados: list[tuple[float, AlunoMemoriaVetorial]] = []
        for reg in regs:
            if disc_filtro_norm and normalizar_chave_disciplina(reg.disciplina or "") != disc_filtro_norm:
                continue
            try:
                vec = reg.embedding if isinstance(reg.embedding, list) else json.loads(reg.embedding)
                sim = _similaridade_cosseno(payload.embedding, [float(x) for x in vec])
            except Exception:
                sim = 0.0
            ranqueados.append((sim, reg))
        ranqueados.sort(key=lambda par: par[0], reverse=True)
        for sim, reg in ranqueados[: payload.top_k]:
            trechos.append(
                {
                    "id_vetor": reg.id_vetor,
                    "origem": reg.origem,
                    "disciplina": reg.disciplina,
                    "pei_id": reg.pei_id,
                    "texto": reg.texto_chunk,
                    "similaridade": round(float(sim), 4),
                }
            )

    return {
        "id_aluno": id_aluno,
        "trechos": trechos,
        "disciplinas_pei": disciplinas_pei,
    }


@Student_router.get("/{id_aluno}")
def ObterAlunoPorId(
    id_aluno: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    aluno = sessao.get(alunos, id_aluno)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")
    _validar_acesso_escola_aluno(sessao, professor_logado, aluno, exigir_pode_chat=False)
    indicadores = None
    if getattr(aluno, "indicadores_desenvolvimento_json", None):
        try:
            indicadores = json.loads(aluno.indicadores_desenvolvimento_json)
        except Exception:
            indicadores = None
    metas = None
    if getattr(aluno, "metas_bimestre_json", None):
        try:
            metas = json.loads(aluno.metas_bimestre_json)
        except Exception:
            metas = None
    from services.disciplinas import avaliar_conclusao_peis_professor

    status_peis = avaliar_conclusao_peis_professor(sessao, aluno, professor_logado)
    return {
        "id_aluno": aluno.id_aluno,
        "nome_aluno": aluno.nome_aluno,
        "neurodiv_aluno": aluno.neurodiv_aluno,
        "desc_aluno": aluno.desc_aluno,
        "perfil_ia": aluno.perfil_ia,
        "indicadores_desenvolvimento": indicadores,
        "metas_bimestre": metas,
        "peis_disciplinas": listar_status_pei_disciplinas(sessao, id_aluno),
        "todos_peis_concluidos": status_peis["todos_peis_concluidos"],
        "disciplinas_concluidas": status_peis["disciplinas_concluidas"],
        "disciplinas_pendentes": status_peis["disciplinas_pendentes"],
        "idade_aluno": aluno.idade_aluno,
        "id_prof": aluno.id_prof,
        "id_turma": aluno.id_turma,
        "pei_feito": bool(aluno.pei_feito),
        "pei_valido_ate": aluno.pei_valido_ate.isoformat() if aluno.pei_valido_ate else None,
        "pei_ativo": pei_esta_valido(aluno),
    }


@Student_router.get("", response_model=List[Alunoschema])
def ListarAlunos(
    id_turma: int | None = None,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    stmt = select(alunos)
    if professor_logado.tipo_usuario != "adm_sistema":
        if id_turma is not None:
            turma = sessao.get(Turma, id_turma)
            if not turma:
                raise HTTPException(status_code=404, detail="Turma não encontrada")
            obter_contexto_escola(sessao, professor_logado.id_prof, turma.fk_Escola_id_escola)
            stmt = stmt.where(alunos.id_turma == id_turma)
        else:
            escolas_ids_visiveis = [
                e["id_escola"] for e in listar_escolas_usuario(sessao, professor_logado)
            ]
            turmas_vinculadas = select(Turma.id_turma).where(
                Turma.fk_Escola_id_escola.in_(escolas_ids_visiveis)
            )
            stmt = stmt.where(
                alunos.fk_Turma_id_turma.in_(turmas_vinculadas)
                if escolas_ids_visiveis
                else (alunos.id_prof == -1)
            )
    elif id_turma is not None:
        stmt = stmt.where(alunos.id_turma == id_turma)
    return sessao.execute(stmt).scalars().all()
