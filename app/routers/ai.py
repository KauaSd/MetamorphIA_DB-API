from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Annotated, Any, Literal, Optional
from urllib.parse import quote
import uuid

from database import (
    ArquivoAnexo,
    Session,
    Turma,
    VALIDADE_PEI_DIAS,
    alunos,
    conversas,
    delete,
    mensagem_al,
    mensagens,
    pegar_bd,
    pei_esta_valido,
    select,
)
from dependencies import pegar_professor_logado, security_scheme
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials
import httpx
from config.settings import settings
from pydantic import BaseModel, Field
from services.disciplinas import registrar_status_pei_disciplina
from services.planos import obter_contexto_escola, validar_e_registrar_cota_ia
from services.storage import (
    excluir_arquivos_por_conversa,
    extrair_texto_docx_bytes_storage,
    ler_bytes_registro_anexo,
    obter_arquivo_anexo,
    salvar_arquivo_anexo,
)

AI_router = APIRouter(prefix="/AI", tags=["AI"])
Conversas_router = APIRouter(tags=["Conversas"])

# URL base da API de Inteligência Artificial (Ia_metamorphia)
IA_API_URL = os.getenv("IA_API_URL", os.getenv("URL", "http://localhost:8001")).rstrip("/")


class TextoIA(BaseModel):
    txt: str


class AnexoChatItem(BaseModel):
    name: str
    type: Optional[str] = "application/octet-stream"
    size: Optional[int] = 0
    dataUrl: Optional[str] = None


class ChatAlunoRequest(BaseModel):
    mensagem: str = ""
    conversa_id: Optional[str] = Field(
        None,
        description="Opcional. Deixe vazio ou null na 1ª mensagem para criar uma nova conversa. Nas mensagens seguintes, repasse o conversa_id retornado.",
        json_schema_extra={"example": None},
    )
    anexos: Optional[list[AnexoChatItem]] = None
    gerar_arquivo_atividade: Optional[bool] = None
    modo_adaptacao: Optional[str] = Field(
        None,
        description="Opcional: 'fiel' (mantém questões do PDF enviado) ou 'template' (usa template pedagógico por perfil).",
    )
    template_id: Optional[str] = Field(
        None,
        description="Opcional: ID do template pedagógico escolhido pelo professor.",
    )
    formato_saida: Optional[str] = Field(
        "docx",
        description="Formato do arquivo de atividade gerado ('docx' ou 'pdf').",
    )
    instrucoes_ia: Optional[str] = None


class PeiRespostaItem(BaseModel):
    pergunta: str
    resposta: str
    numero_pergunta_geral: Optional[int] = None


class PeiInicialRequest(BaseModel):
    descricao_aluno: Optional[str] = None
    componente_curricular: Optional[str] = "Língua Portuguesa"
    ano_escolar: Optional[str] = "Ensino Fundamental"
    periodo_bimestre: Optional[int] = 1
    indice_subpergunta: Optional[int] = None


class PeiCriarRequest(BaseModel):
    respostas: list[PeiRespostaItem] = Field(default_factory=list)
    nome_professor_regente: Optional[str] = None
    nome_professor_especializado: Optional[str] = None
    componente_curricular: Optional[str] = "Língua Portuguesa"
    ano_escolar: Optional[str] = "Ensino Fundamental"
    periodo_bimestre: Optional[int] = 1
    descricao_aluno: Optional[str] = None


class PeiImportarRequest(BaseModel):
    arquivo_nome: str
    arquivo_base64: str
    componente_curricular: Optional[str] = "Língua Portuguesa"
    periodo_bimestre: Optional[int] = 1


class AdaptarAtividadeRequest(BaseModel):
    atividade: str = Field(default="", description="Descrição da atividade original")
    neurodivergencia: str = Field(..., description="Condição do estudante (TEA, TDAH, Dislexia, etc.)")
    ano_escolar: Optional[str] = None
    objetivo_pedagogico: Optional[str] = None
    nome_aluno: Optional[str] = None
    arquivo_nome: Optional[str] = None
    arquivo_base64: Optional[str] = None
    anexos: Optional[list[AnexoChatItem]] = None
    modo_adaptacao: Optional[str] = None
    template_id: Optional[str] = None
    formato_saida: Optional[str] = "docx"
    instrucoes_ia: Optional[str] = None


class PerguntaGeralRequest(BaseModel):
    pergunta: str
    instrucoes_ia: Optional[str] = None


class SimularIA(BaseModel):
    neurodivergencias: list[str] | str = Field(
        default=["TEA (Nível 1)", "TDAH e Dislexia"],
        description="Lista de neurodivergências (cada posição representa um aluno diferente, pareado diretamente com a pergunta de mesma posição em 'perguntas').",
        json_schema_extra={"example": ["TEA (Nível 1)", "TDAH e Dislexia"]},
    )
    perguntas: Optional[list[str] | str] = Field(
        default=None,
        description="Lista de perguntas (cada pergunta[i] é feita diretamente para a neurodivergencias[i], como alunos diferentes). Se omitida, o mock simula uma pergunta específica para cada neurodivergência.",
        json_schema_extra={
            "example": [
                "Como posso adaptar uma atividade de frações em grupo para este aluno que tem sensibilidade a barulho e prefere rotina visual?",
                "Quais estratégias usar na aula de leitura quando este aluno se distrai rápido e trava em textos longos?",
            ]
        },
    )
    nome_aluno: list[str] | str = "Aluno Simulado"
    idade_aluno: Optional[int] = 10
    observacoes_aluno: Optional[str] = None


def exigir_conta_autorizada_ia(
    professor: Annotated[Any, Depends(pegar_professor_logado)],
) -> Any:
    """Se AI_ALLOWED_EMAILS estiver definido, restringe o uso da IA apenas às contas listadas."""
    permitidos_raw = (getattr(settings, "AI_ALLOWED_EMAILS", "") or "").strip()
    if not permitidos_raw:
        return professor
    permitidos = {
        e.strip().lower() for e in permitidos_raw.split(",") if e.strip()
    }
    email_user = (getattr(professor, "email_usuario", None) or "").strip().lower()
    if not email_user or email_user not in permitidos:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O acesso à IA está temporariamente restrito à conta autorizada.",
        )
    return professor


def _obter_headers(token: str) -> dict[str, str]:
    """Prepara os headers HTTP encaminhando o token JWT recebido para a API de IA."""
    headers = {"Content-Type": "application/json"}
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _obter_e_validar_aluno_ia(
    sessao: Session, professor: Any, id_aluno: int, exigir_pode_chat: bool = True
) -> Any:
    """Valida existência do aluno, vínculo com a escola do usuário e permissão pedagógica (pode_chat)."""
    tipo_user = getattr(professor, "tipo_usuario", "normal")
    if exigir_pode_chat and tipo_user == "adm_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O administrador institucional não pode acessar ou conversar no chat dos alunos.",
        )

    aluno_obj = sessao.get(alunos, id_aluno)
    if not aluno_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aluno não encontrado.",
        )

    if tipo_user == "adm_sistema":
        return aluno_obj

    if aluno_obj.fk_Turma_id_turma:
        turma_obj = sessao.get(Turma, aluno_obj.fk_Turma_id_turma)
        if not turma_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Turma do aluno não encontrada.",
            )
        ctx = obter_contexto_escola(
            sessao, professor.id_prof, turma_obj.fk_Escola_id_escola
        )
        if exigir_pode_chat and not ctx.get("pode_chat", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Este administrador está configurado sem acesso ao chat dos alunos nesta escola.",
            )
    elif aluno_obj.id_prof != professor.id_prof:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar os dados deste aluno.",
        )
    return aluno_obj


def _validar_acesso_chat_professor_aluno(
    sessao: Session, professor: Any, id_aluno: int
) -> Any:
    """Garante que o usuário tem permissão de chat para o aluno e retorna o registro do aluno."""
    return _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=True)


def _exigir_pei_valido_para_chat(aluno_obj: Any) -> None:
    """Impede o uso do chat enquanto o PEI não for concluído ou se a validade bimestral (60 dias) expirou."""
    if not pei_esta_valido(aluno_obj):
        if getattr(aluno_obj, "pei_feito", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A validade bimestral (60 dias) do PEI deste aluno expirou. Renove o PEI antes de conversar no chat.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="É obrigatório concluir o PEI deste aluno antes de conversar com a IA.",
        )


def _validar_segmento_id_seguro(valor: str, nome: str = "identificador") -> str:
    limpo = (valor or "").strip()
    if not limpo or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", limpo):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato inválido para {nome}.",
        )
    return quote(limpo, safe="")


async def _encaminhar_requisicao_ia(
    metodo: str,
    endpoint: str,
    token: str,
    json_data: Any = None,
    params: Any = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Helper genérico para enviar requisições autenticadas para a API de IA e tratar respostas."""
    url = f"{IA_API_URL}{endpoint}"
    headers = _obter_headers(token)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resposta = await client.request(
                method=metodo,
                url=url,
                headers=headers,
                json=json_data,
                params=params,
            )
            resposta.raise_for_status()
            return resposta.json()
        except httpx.HTTPStatusError as exc:
            detalhe = "Erro retornado pelo serviço de IA."
            try:
                err_json = exc.response.json()
                if isinstance(err_json, dict) and err_json.get("detail"):
                    detalhe = str(err_json["detail"])
            except Exception:
                pass
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=detalhe,
            ) from exc
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            print(f"[AI Gateway] Falha ao comunicar com IA ({url}): {exc}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço de Inteligência Artificial temporariamente indisponível.",
            ) from exc


@AI_router.post("/chat/aluno/{id_aluno}")
async def chat_aluno_ia(
    id_aluno: int,
    payload: ChatAlunoRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Envia uma mensagem pedagógica sobre um aluno para a IA e recebe a resposta adaptada."""
    aluno_validado = _validar_acesso_chat_professor_aluno(sessao, professor, id_aluno)
    _exigir_pei_valido_para_chat(aluno_validado)

    cid = payload.conversa_id
    if cid in ("string", "", "null", "None"):
        cid = None

    if cid:
        try:
            conversa_existente = sessao.get(conversas, cid)
            if conversa_existente and conversa_existente.id_prof != professor.id_prof:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Esta conversa pertence a outro professor.",
                )
        except HTTPException:
            raise
        except Exception:
            sessao.rollback()

    historico_conversa = []
    total_interacoes = 1
    try:
        if cid:
            stmt_hist = (
                select(mensagens)
                .where(
                    mensagens.id_conversa == cid,
                    mensagens.id_prof == professor.id_prof,
                )
                .order_by(mensagens.data_mensagem.asc())
            )
            msgs_antigas = sessao.execute(stmt_hist).scalars().all()
            historico_conversa = [
                {
                    "role": m.role or "user",
                    "conteudo": m.conteudo or "",
                    "data": m.data_mensagem.isoformat() if m.data_mensagem else "",
                }
                for m in msgs_antigas
            ]
        stmt_total = select(mensagens).where(
            mensagens.id_aluno == id_aluno,
            mensagens.role == "user",
        )
        total_interacoes = len(sessao.execute(stmt_total).scalars().all()) + 1
    except Exception:
        sessao.rollback()

    instrucoes_prof = (
        payload.instrucoes_ia
        if payload.instrucoes_ia is not None
        else (getattr(professor, "instrucoes_ia", None) or None)
    )
    corpo = {
        "id_prof": professor.id_prof,
        "mensagem": payload.mensagem,
        "conversa_id": cid,
        "historico": historico_conversa,
        "total_interacoes": total_interacoes,
        "anexos": [a.model_dump() for a in payload.anexos] if payload.anexos else None,
        "gerar_arquivo_atividade": payload.gerar_arquivo_atividade,
        "modo_adaptacao": payload.modo_adaptacao,
        "template_id": payload.template_id,
        "formato_saida": payload.formato_saida or "docx",
        "instrucoes_ia": instrucoes_prof,
        "persistido_pelo_gateway": True,
    }
    resposta = await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/chat",
        token=credentials.credentials,
        json_data=corpo,
    )

    try:
        perfil_atualizado = resposta.get("perfil_atualizado")
        indicadores = resposta.get("indicadores_desenvolvimento")
        metas = resposta.get("metas_bimestre")
        if perfil_atualizado or indicadores is not None or metas is not None:
            aluno_obj = sessao.get(alunos, id_aluno)
            if aluno_obj:
                if perfil_atualizado:
                    aluno_obj.perfil_ia = perfil_atualizado
                if indicadores is not None:
                    aluno_obj.indicadores_desenvolvimento_json = json.dumps(indicadores, ensure_ascii=False)
                if metas is not None:
                    aluno_obj.metas_bimestre_json = json.dumps(metas, ensure_ascii=False)
        final_conversa_id = resposta.get("conversa_id") or cid
        if final_conversa_id:
            titulo_chat = (payload.mensagem or "").strip()[:50]
            if not titulo_chat and payload.anexos:
                titulo_chat = f"Atividade: {payload.anexos[0].name}"[:50]
            conversa_obj = sessao.get(conversas, final_conversa_id)
            if not conversa_obj:
                conversa_obj = conversas(
                    id_conversa=final_conversa_id,
                    id_aluno=id_aluno,
                    id_prof=professor.id_prof,
                    titulo=titulo_chat or "Nova conversa",
                )
                sessao.add(conversa_obj)
                sessao.flush()
            else:
                conversa_obj.atualizado_em = datetime.now(timezone.utc)

            anexos_user_meta: list[dict[str, Any]] = []
            for ax in payload.anexos or []:
                meta = salvar_arquivo_anexo(
                    sessao=sessao,
                    id_prof=professor.id_prof,
                    id_aluno=id_aluno,
                    id_conversa=final_conversa_id,
                    nome_arquivo=ax.name,
                    mime_type=ax.type or "application/octet-stream",
                    data_url_ou_b64=ax.dataUrl,
                )
                if meta:
                    anexos_user_meta.append(meta)
                else:
                    anexos_user_meta.append(
                        {"name": ax.name, "type": ax.type or "application/octet-stream", "size": ax.size or 0}
                    )
            anexos_user_json = (
                json.dumps(anexos_user_meta, ensure_ascii=False)
                if anexos_user_meta
                else None
            )
            msg_user = mensagens(
                id_prof=professor.id_prof,
                id_aluno=id_aluno,
                id_conversa=final_conversa_id,
                conteudo=payload.mensagem or titulo_chat,
                anexo_mensagem=anexos_user_json,
                role="user",
            )
            sessao.add(msg_user)
            sessao.flush()
            sessao.execute(
                mensagem_al.insert().values(
                    id_aluno=id_aluno, id_mensagem=msg_user.id_mensagem
                )
            )

            texto_ia = resposta.get("resposta", "")
            anexos_ia = resposta.get("anexos")
            anexos_ia_meta: list[dict[str, Any]] = []
            for ax in anexos_ia or []:
                meta = salvar_arquivo_anexo(
                    sessao=sessao,
                    id_prof=professor.id_prof,
                    id_aluno=id_aluno,
                    id_conversa=final_conversa_id,
                    nome_arquivo=ax.get("name", "atividade"),
                    mime_type=ax.get("type", "application/octet-stream"),
                    data_url_ou_b64=ax.get("dataUrl"),
                )
                if meta:
                    anexos_ia_meta.append(meta)
                    ax["file_id"] = meta["file_id"]
                    ax["download_url"] = meta["download_url"]
                else:
                    anexos_ia_meta.append(
                        {
                            "name": ax.get("name", "atividade"),
                            "type": ax.get("type", "application/octet-stream"),
                            "size": ax.get("size", 0),
                        }
                    )
            if anexos_ia_meta and anexos_ia_meta[0].get("download_url"):
                resposta["file_id"] = anexos_ia_meta[0]["file_id"]
                resposta["download_url_persistente"] = anexos_ia_meta[0]["download_url"]
            anexos_ia_json = (
                json.dumps(anexos_ia_meta, ensure_ascii=False)
                if anexos_ia_meta
                else None
            )
            msg_ia = mensagens(
                id_prof=professor.id_prof,
                id_aluno=id_aluno,
                id_conversa=final_conversa_id,
                conteudo=texto_ia,
                anexo_mensagem=anexos_ia_json,
                role="assistant",
            )
            sessao.add(msg_ia)
            sessao.flush()
            sessao.execute(
                mensagem_al.insert().values(
                    id_aluno=id_aluno, id_mensagem=msg_ia.id_mensagem
                )
            )

            sessao.commit()
    except Exception as exc:
        print(f"[Aviso] Falha ao persistir no banco relacional: {exc}")
        sessao.rollback()

    return resposta


@AI_router.post("/chat/aluno/{id_aluno}/adaptar-atividade")
async def chat_adaptar_atividade_aluno_ia(
    id_aluno: int,
    payload: ChatAlunoRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Recebe um arquivo do professor no chat do aluno e retorna a atividade adaptada + arquivo .docx na resposta."""
    validar_e_registrar_cota_ia(sessao, professor, "adaptacao")
    payload.gerar_arquivo_atividade = True
    return await chat_aluno_ia(
        id_aluno=id_aluno,
        payload=payload,
        credentials=credentials,
        professor=professor,
        sessao=sessao,
    )


@AI_router.get("/conversas")
def listar_conversas_lote_ia(
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    aluno_ids: Optional[str] = None,
    sessao: Session = Depends(pegar_bd),
):
    """Lista conversas de múltiplos alunos em lote agrupadas por id_aluno."""
    from routers.students import listar_conversas_em_lote_para_usuario

    return listar_conversas_em_lote_para_usuario(sessao, professor, aluno_ids)


@AI_router.get("/conversas/recentes")
@Conversas_router.get("/conversas/recentes")
def listar_conversas_recentes_ia(
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    limit: Optional[int] = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    busca: Optional[str] = Query(default=None, max_length=120),
    ordenar_por: Literal["data", "aluno", "titulo"] = "data",
    ordem: Literal["desc", "asc"] = "desc",
    sessao: Session = Depends(pegar_bd),
):
    """Lista conversas recentes do professor em ordem global, enriquecidas com aluno e turma."""
    from routers.students import listar_conversas_recentes_para_usuario

    return listar_conversas_recentes_para_usuario(
        sessao=sessao,
        professor_logado=professor,
        limit=limit,
        offset=offset,
        busca=busca,
        ordenar_por=ordenar_por,
        ordem=ordem,
    )


@AI_router.get("/conversas/{conversa_id}")
@Conversas_router.get("/conversas/{conversa_id}")
def obter_conversa_por_id_ia(
    conversa_id: str,
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Retorna os metadados da conversa e suas mensagens pelo conversa_id."""
    from routers.students import obter_conversa_por_id_para_usuario

    return obter_conversa_por_id_para_usuario(
        sessao=sessao,
        professor_logado=professor,
        conversa_id=conversa_id,
    )


@AI_router.get("/chat/aluno/{id_aluno}/conversas")
async def listar_conversas_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Lista as conversas registradas no banco para o aluno, isoladas individualmente por professor."""
    _validar_acesso_chat_professor_aluno(sessao, professor, id_aluno)

    stmt = (
        select(conversas)
        .where(
            conversas.id_aluno == id_aluno,
            conversas.id_prof == professor.id_prof,
        )
        .order_by(conversas.atualizado_em.desc())
    )
    convs = sessao.execute(stmt).scalars().all()
    if convs:
        return [
            {
                "conversa_id": c.id_conversa,
                "titulo": c.titulo,
                "data": c.atualizado_em.isoformat() if c.atualizado_em else "",
            }
            for c in convs
        ]

    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/conversas",
        token=credentials.credentials,
    )


@AI_router.get("/chat/aluno/{id_aluno}/conversas/{conversa_id}")
async def obter_mensagens_conversa_ia(
    id_aluno: int,
    conversa_id: str,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Recupera as mensagens de uma conversa específica do banco (apenas do próprio professor)."""
    _validar_acesso_chat_professor_aluno(sessao, professor, id_aluno)

    stmt = (
        select(mensagens)
        .where(
            mensagens.id_conversa == conversa_id,
            mensagens.id_prof == professor.id_prof,
        )
        .order_by(mensagens.data_mensagem.asc())
    )
    msgs = sessao.execute(stmt).scalars().all()
    if msgs:
        lista_msgs = []
        for m in msgs:
            anexos_parsed = None
            if m.anexo_mensagem:
                try:
                    anexos_parsed = json.loads(m.anexo_mensagem)
                except Exception:
                    anexos_parsed = None
            lista_msgs.append(
                {
                    "role": m.role or "user",
                    "conteudo": m.conteudo or "",
                    "data": m.data_mensagem.isoformat() if m.data_mensagem else "",
                    "anexos": anexos_parsed,
                }
            )
        return {
            "conversa_id": conversa_id,
            "mensagens": lista_msgs,
        }

    cid_seguro = _validar_segmento_id_seguro(conversa_id, "conversa_id")
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/conversas/{cid_seguro}",
        token=credentials.credentials,
    )


@AI_router.delete("/chat/aluno/{id_aluno}/conversas/{conversa_id}")
async def deletar_conversa_aluno_ia(
    id_aluno: int,
    conversa_id: str,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Exclui uma conversa do banco relacional e da memória vetorial da IA."""
    _validar_acesso_chat_professor_aluno(sessao, professor, id_aluno)
    try:
        msgs = sessao.execute(
            select(mensagens).where(
                mensagens.id_conversa == conversa_id,
                mensagens.id_prof == professor.id_prof,
            )
        ).scalars().all()
        msg_ids = [m.id_mensagem for m in msgs]
        if msg_ids:
            sessao.execute(delete(mensagem_al).where(mensagem_al.c.id_mensagem.in_(msg_ids)))
            sessao.execute(delete(mensagens).where(mensagens.id_mensagem.in_(msg_ids)))
        conv = sessao.get(conversas, conversa_id)
        if conv and conv.id_prof == professor.id_prof:
            sessao.delete(conv)
        excluir_arquivos_por_conversa(sessao, conversa_id, professor.id_prof)
        sessao.commit()
    except Exception:
        sessao.rollback()

    try:
        cid_seguro = _validar_segmento_id_seguro(conversa_id, "conversa_id")
        await _encaminhar_requisicao_ia(
            metodo="DELETE",
            endpoint=f"/alunos/{id_aluno}/conversas/{cid_seguro}",
            token=credentials.credentials,
        )
    except Exception:
        pass
    return {"mensagem": "Conversa excluída com sucesso.", "conversa_id": conversa_id}


@AI_router.get("/arquivos/{file_id}")
def baixar_arquivo_anexo_chat(
    file_id: str,
    professor: Annotated[Any, Depends(pegar_professor_logado)],
    sessao: Session = Depends(pegar_bd),
) -> Response:
    """Baixa um arquivo anexo (PDF/DOCX/imagem) salvo no armazenamento do chat."""
    reg, conteudo = obter_arquivo_anexo(sessao, file_id, professor)
    nome_seguro_header = (reg.nome_arquivo or "arquivo").replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=conteudo,
        media_type=reg.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{nome_seguro_header}"',
            "X-File-Id": reg.id_arquivo,
        },
    )


DOCX_PEI_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _persistir_pei_e_perfil_gateway(
    sessao: Session,
    aluno_obj: Any,
    id_prof: int,
    resposta_ia: dict[str, Any],
    descricao_enviada: Optional[str] = None,
    componente_curricular: Optional[str] = None,
) -> dict[str, Any]:
    """Salva o .docx do PEI no Supabase Storage e atualiza perfil_ia + validade de 60 dias no banco."""
    pei_id = (resposta_ia.get("pei_id") or str(uuid.uuid4())).strip()
    docx_b64 = resposta_ia.get("documento_docx_base64")
    arquivo_nome = resposta_ia.get("arquivo_nome") or f"PEI_aluno_{aluno_obj.id_aluno}_2026.docx"

    if docx_b64 and not sessao.get(ArquivoAnexo, pei_id):
        salvar_arquivo_anexo(
            sessao=sessao,
            id_prof=id_prof,
            id_aluno=aluno_obj.id_aluno,
            id_conversa="PEI",
            nome_arquivo=arquivo_nome,
            mime_type=DOCX_PEI_MIME,
            data_url_ou_b64=docx_b64,
            file_id_override=pei_id,
            download_url_override=f"/AI/pei/aluno/{aluno_obj.id_aluno}/{pei_id}/docx",
        )

    if descricao_enviada and not aluno_obj.desc_aluno:
        aluno_obj.desc_aluno = descricao_enviada
    perfil_novo = resposta_ia.get("perfil_atualizado")
    if perfil_novo:
        aluno_obj.perfil_ia = perfil_novo
    if resposta_ia.get("indicadores_desenvolvimento") is not None:
        aluno_obj.indicadores_desenvolvimento_json = json.dumps(
            resposta_ia["indicadores_desenvolvimento"], ensure_ascii=False
        )
    if resposta_ia.get("metas_bimestre") is not None:
        aluno_obj.metas_bimestre_json = json.dumps(
            resposta_ia["metas_bimestre"], ensure_ascii=False
        )
    if componente_curricular:
        registrar_status_pei_disciplina(
            sessao=sessao,
            id_aluno=aluno_obj.id_aluno,
            id_prof=id_prof,
            disciplina=componente_curricular,
            status_pei="concluido",
            pei_id=pei_id,
        )

    aluno_obj.pei_feito = True
    aluno_obj.pei_valido_ate = datetime.now(timezone.utc) + timedelta(days=VALIDADE_PEI_DIAS)
    sessao.commit()
    sessao.refresh(aluno_obj)

    resposta_ia["pei_id"] = pei_id
    resposta_ia["download_url"] = f"/AI/pei/aluno/{aluno_obj.id_aluno}/{pei_id}/docx"
    resposta_ia["pei_feito"] = True
    resposta_ia["pei_valido_ate"] = (
        aluno_obj.pei_valido_ate.isoformat() if aluno_obj.pei_valido_ate else None
    )
    return resposta_ia


@AI_router.post("/pei/aluno/{id_aluno}/inicial")
async def criar_pei_inicial_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
    payload: Optional[PeiInicialRequest] = None,
):
    """Inicia a elaboração do PEI verificando o contexto do aluno e gerando as perguntas e 4 opções de cada subpergunta."""
    _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=True)
    req = payload or PeiInicialRequest()
    if req.componente_curricular:
        try:
            registrar_status_pei_disciplina(
                sessao=sessao,
                id_aluno=id_aluno,
                id_prof=professor.id_prof,
                disciplina=req.componente_curricular,
                status_pei="em_andamento",
            )
            sessao.commit()
        except Exception:
            sessao.rollback()
    corpo = {"id_prof": professor.id_prof, **req.model_dump(exclude_none=True)}
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/pei/inicial",
        token=credentials.credentials,
        json_data=corpo,
    )


@AI_router.post("/pei/aluno/{id_aluno}")
async def criar_pei_aluno_ia(
    id_aluno: int,
    payload: PeiCriarRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Envia as respostas do questionário à API de IA para gerar um PEI completo em formato .docx e o perfil_ia."""
    aluno_obj = _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=True)
    validar_e_registrar_cota_ia(sessao, professor, "pei")
    corpo = {
        "id_prof": professor.id_prof,
        **payload.model_dump(exclude_none=True),
        "respostas": [item.model_dump() for item in payload.respostas],
        "persistido_pelo_gateway": True,
    }
    resposta = await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/pei",
        token=credentials.credentials,
        json_data=corpo,
    )
    try:
        resposta = _persistir_pei_e_perfil_gateway(
            sessao=sessao,
            aluno_obj=aluno_obj,
            id_prof=professor.id_prof,
            resposta_ia=resposta,
            descricao_enviada=payload.descricao_aluno,
            componente_curricular=payload.componente_curricular,
        )
    except Exception as exc:
        sessao.rollback()
        print(f"[AI Gateway] Falha ao salvar PEI no armazenamento: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao salvar o documento do PEI no armazenamento.",
        ) from exc
    return resposta


@AI_router.get("/pei/aluno/{id_aluno}")
def listar_peis_aluno_ia(
    id_aluno: int,
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Lista os PEIs salvos no Supabase Storage / banco para o aluno."""
    aluno_obj = _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=False)
    regs = (
        sessao.execute(
            select(ArquivoAnexo)
            .where(ArquivoAnexo.id_aluno == id_aluno, ArquivoAnexo.id_conversa == "PEI")
            .order_by(ArquivoAnexo.criado_em.desc())
        )
        .scalars()
        .all()
    )
    validade_str = aluno_obj.pei_valido_ate.strftime("%d/%m/%Y") if aluno_obj.pei_valido_ate else "N/A"
    status_txt = f"Válido até {validade_str}" if pei_esta_valido(aluno_obj) else "Expirado"
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


@AI_router.get("/pei/aluno/{id_aluno}/{pei_id}")
def obter_pei_detalhe_ia(
    id_aluno: int,
    pei_id: str,
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Obtém o texto extraído sob demanda do .docx do PEI salvo no Supabase Storage."""
    _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=False)
    reg = sessao.get(ArquivoAnexo, pei_id)
    if not reg or reg.id_aluno != id_aluno or reg.id_conversa != "PEI":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PEI não encontrado para este aluno.")
    docx_bytes = ler_bytes_registro_anexo(reg)
    texto_pei = extrair_texto_docx_bytes_storage(docx_bytes)
    return {
        "pei_id": reg.id_arquivo,
        "id_aluno": id_aluno,
        "documento_gerado": texto_pei or reg.nome_arquivo,
        "data": reg.criado_em.isoformat() if reg.criado_em else "",
    }


@AI_router.post("/pei/aluno/{id_aluno}/importar")
async def importar_pei_aluno_ia(
    id_aluno: int,
    payload: PeiImportarRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Importa um arquivo de PEI existente (.pdf, .docx, .txt), salva no Supabase Storage e gera o perfil_ia."""
    aluno_obj = _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=True)
    corpo = {
        "id_prof": professor.id_prof,
        **payload.model_dump(exclude_none=True),
        "persistido_pelo_gateway": True,
    }
    resposta = await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/pei/importar",
        token=credentials.credentials,
        json_data=corpo,
    )
    try:
        resposta = _persistir_pei_e_perfil_gateway(
            sessao=sessao,
            aluno_obj=aluno_obj,
            id_prof=professor.id_prof,
            resposta_ia=resposta,
            componente_curricular=payload.componente_curricular,
        )
    except Exception as exc:
        sessao.rollback()
        print(f"[AI Gateway] Falha ao salvar PEI importado: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao salvar o PEI importado no armazenamento.",
        ) from exc
    return resposta


@AI_router.get("/pei/aluno/{id_aluno}/{pei_id}/docx")
def baixar_pei_docx_ia(
    id_aluno: int,
    pei_id: str,
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
) -> Response:
    """Baixa o arquivo .docx do PEI diretamente do Supabase Storage validando vínculo com a escola."""
    _validar_segmento_id_seguro(pei_id, "pei_id")
    _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=False)
    reg = sessao.get(ArquivoAnexo, pei_id)
    if not reg or reg.id_aluno != id_aluno or reg.id_conversa != "PEI":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PEI não encontrado para este aluno.")
    docx_bytes = ler_bytes_registro_anexo(reg)
    nome_seguro = (reg.nome_arquivo or f"PEI_aluno_{id_aluno}.docx").replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=docx_bytes,
        media_type=DOCX_PEI_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{nome_seguro}"',
            "X-Pei-Id": reg.id_arquivo,
        },
    )


@AI_router.post("/perfil/aluno/{id_aluno}")
async def gerar_perfil_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Solicita à IA a geração de síntese do perfil pedagógico a partir do histórico no PostgreSQL."""
    aluno_obj = _obter_e_validar_aluno_ia(sessao, professor, id_aluno, exigir_pode_chat=True)
    _exigir_pei_valido_para_chat(aluno_obj)

    msgs_recentes = (
        sessao.execute(
            select(mensagens)
            .where(
                mensagens.id_aluno == id_aluno,
                mensagens.id_prof == professor.id_prof,
            )
            .order_by(mensagens.data_mensagem.asc())
        )
        .scalars()
        .all()
    )
    linhas_hist = []
    for m in msgs_recentes[-20:]:
        papel = "Professor" if (m.role or "user") == "user" else "Assistente"
        txt = (m.conteudo or "").strip()
        if papel == "Assistente" and len(txt) > 300:
            txt = txt[:300] + "..."
        if txt:
            linhas_hist.append(f"{papel}: {txt}")

    resposta = await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/perfil",
        token=credentials.credentials,
        json_data={"historico_conversas": "\n".join(linhas_hist), "persistido_pelo_gateway": True},
    )
    try:
        perfil_texto = resposta.get("perfil") or resposta.get("perfil_gerado")
        indicadores = resposta.get("indicadores_desenvolvimento")
        metas = resposta.get("metas_bimestre")
        if perfil_texto or indicadores is not None or metas is not None:
            if perfil_texto:
                aluno_obj.perfil_ia = perfil_texto
            if indicadores is not None:
                aluno_obj.indicadores_desenvolvimento_json = json.dumps(indicadores, ensure_ascii=False)
            if metas is not None:
                aluno_obj.metas_bimestre_json = json.dumps(metas, ensure_ascii=False)
            sessao.commit()
    except Exception as exc:
        print(f"[Aviso] Falha ao atualizar perfil_ia: {exc}")
        sessao.rollback()

    return resposta


@AI_router.get("/aluno/{id_aluno}/descricao-breve")
async def descricao_breve_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Retorna uma descrição breve do aluno para o card Perfil do Aluno."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/descricao-breve",
        token=credentials.credentials,
    )


@AI_router.get("/dashboard/aluno/{id_aluno}")
async def dashboard_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Consulta o dashboard consolidado do aluno junto à API de IA."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/dashboard",
        token=credentials.credentials,
    )


@AI_router.get("/dashboard/turma/{id_turma}")
async def dashboard_turma_ia(
    id_turma: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Consulta o dashboard consolidado da turma junto à API de IA."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/turmas/{id_turma}/dashboard",
        token=credentials.credentials,
    )


@AI_router.post("/adaptar-atividade")
async def adaptar_atividade_ia(
    payload: AdaptarAtividadeRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Envia uma atividade para a IA gerar adaptações curriculares fundamentadas no DUA."""
    validar_e_registrar_cota_ia(sessao, professor, "adaptacao")
    dados = payload.model_dump(exclude_none=True)
    if "instrucoes_ia" not in dados and getattr(professor, "instrucoes_ia", None):
        dados["instrucoes_ia"] = professor.instrucoes_ia
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/adaptar-atividade",
        token=credentials.credentials,
        json_data=dados,
    )


@AI_router.post("/adaptar-atividade/arquivo")
async def adaptar_atividade_arquivo_ia(
    payload: AdaptarAtividadeRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Envia um arquivo de atividade para a IA gerar a atividade adaptada e devolver o arquivo .docx ou .pdf."""
    validar_e_registrar_cota_ia(sessao, professor, "adaptacao")
    dados = payload.model_dump(exclude_none=True)
    if "instrucoes_ia" not in dados and getattr(professor, "instrucoes_ia", None):
        dados["instrucoes_ia"] = professor.instrucoes_ia
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/adaptar-atividade/arquivo",
        token=credentials.credentials,
        json_data=dados,
    )


@AI_router.get("/atividades/aluno/{id_aluno}/{atividade_id}/{formato}")
async def baixar_atividade_adaptada_aluno_ia(
    id_aluno: int,
    atividade_id: str,
    formato: str,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
) -> Response:
    """Baixa o arquivo .docx ou .pdf de uma atividade adaptada gerada pela IA."""
    ativ_segura = _validar_segmento_id_seguro(atividade_id, "atividade_id")
    fmt = "pdf" if (formato or "").strip().lower() == "pdf" else "docx"
    url = f"{IA_API_URL}/alunos/{id_aluno}/atividades/{ativ_segura}/{fmt}"
    headers = _obter_headers(credentials.credentials)
    media_type = (
        "application/pdf"
        if fmt == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resposta = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            print(f"[AI Gateway] Falha ao baixar atividade adaptada: {exc}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço de IA temporariamente indisponível para download.",
            ) from exc
        if not resposta.is_success:
            raise HTTPException(
                status_code=resposta.status_code,
                detail="Não foi possível baixar a atividade adaptada solicitada.",
            )
        return Response(
            content=resposta.content,
            media_type=media_type,
            headers={
                "Content-Disposition": resposta.headers.get(
                    "content-disposition",
                    f'attachment; filename="Atividade_Adaptada_aluno_{id_aluno}.{fmt}"',
                )
            },
        )


@AI_router.post("/perguntar")
async def perguntar_geral_ia(
    payload: PerguntaGeralRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Envia uma consulta pedagógica direta para a API de IA com RAG e guardrails."""
    dados = payload.model_dump(exclude_none=True)
    if "instrucoes_ia" not in dados and getattr(professor, "instrucoes_ia", None):
        dados["instrucoes_ia"] = professor.instrucoes_ia
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/perguntar",
        token=credentials.credentials,
        json_data=dados,
    )


@AI_router.get("/enviatxtuser/{txt}")
async def enviatxtuser(txt: str):
    """Endpoint legado de eco/teste de texto (restrito a dev/homologação com ENABLE_MOCK_ROUTES=true)."""
    from config.settings import settings

    if settings.ENVIRONMENT == "production" or not settings.ENABLE_MOCK_ROUTES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rota de teste desabilitada neste ambiente.",
        )
    return {"mensagem": txt}


@AI_router.post("/txtIA")
async def txtIA(
    IAtxt: TextoIA,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Endpoint legado para envio de texto à IA, exigindo usuário autenticado."""
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/perguntar",
        token=credentials.credentials,
        json_data={"pergunta": IAtxt.txt},
    )


@AI_router.post("/simular")
async def simular_ia_sem_login(payload: SimularIA):
    """Endpoint de homologação/teste para simular neurodivergências e perguntas (requer ENABLE_MOCK_ROUTES=true)."""
    from config.settings import settings

    if settings.ENVIRONMENT == "production" or not settings.ENABLE_MOCK_ROUTES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rota de simulação desabilitada neste ambiente.",
        )
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/mock/simular",
        token="",
        json_data=payload.model_dump(),
        timeout=300.0,
    )
