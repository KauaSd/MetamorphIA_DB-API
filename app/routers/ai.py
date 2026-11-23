from datetime import datetime, timezone
import json
import os
from typing import Annotated, Any, Optional

from database import (
    Session,
    Turma,
    alunos,
    conversas,
    delete,
    mensagem_al,
    mensagens,
    pegar_bd,
    select,
)
from dependencies import pegar_professor_logado, security_scheme
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
import httpx
from config.settings import settings
from pydantic import BaseModel, Field
from services.planos import obter_contexto_escola
from services.storage import (
    excluir_arquivos_por_conversa,
    obter_arquivo_anexo,
    salvar_arquivo_anexo,
)

AI_router = APIRouter(prefix="/AI", tags=["AI"])

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


def _validar_acesso_chat_professor_aluno(
    sessao: Session, professor: Any, id_aluno: int
) -> None:
    """Garante que o usuário tem permissão de chat para o aluno (bloqueando adm_institucional e adm_pro_plus sem pode_chat)."""
    tipo_user = getattr(professor, "tipo_usuario", "normal")
    if tipo_user == "adm_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O administrador institucional não pode acessar ou conversar no chat dos alunos.",
        )

    try:
        aluno_obj = sessao.get(alunos, id_aluno)
    except Exception:
        sessao.rollback()
        aluno_obj = None
    if aluno_obj and aluno_obj.fk_Turma_id_turma:
        turma_obj = sessao.get(Turma, aluno_obj.fk_Turma_id_turma)
        if turma_obj and turma_obj.fk_Escola_id_escola:
            ctx = obter_contexto_escola(
                sessao, professor.id_prof, turma_obj.fk_Escola_id_escola
            )
            if not ctx["pode_chat"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Este administrador Pro+ está configurado sem acesso ao chat dos alunos nesta escola.",
                )


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
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Erro retornado pela API da IA: {exc.response.text}",
            ) from exc
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Não foi possível se comunicar com o serviço de IA em {url}. Erro: {exc}",
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
    _validar_acesso_chat_professor_aluno(sessao, professor, id_aluno)

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
    }
    resposta = await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/chat",
        token=credentials.credentials,
        json_data=corpo,
    )

    try:
        perfil_atualizado = resposta.get("perfil_atualizado")
        if perfil_atualizado:
            aluno_obj = sessao.get(alunos, id_aluno)
            if aluno_obj:
                aluno_obj.perfil_ia = perfil_atualizado
                aluno_obj.desc_aluno = perfil_atualizado
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
    payload.gerar_arquivo_atividade = True
    return await chat_aluno_ia(
        id_aluno=id_aluno,
        payload=payload,
        credentials=credentials,
        professor=professor,
        sessao=sessao,
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

    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/conversas/{conversa_id}",
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
        await _encaminhar_requisicao_ia(
            metodo="DELETE",
            endpoint=f"/alunos/{id_aluno}/conversas/{conversa_id}",
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


@AI_router.post("/pei/aluno/{id_aluno}/inicial")
async def criar_pei_inicial_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    payload: Optional[PeiInicialRequest] = None,
):
    """Inicia a elaboração do PEI verificando o contexto do aluno e gerando as perguntas e 4 opções de cada subpergunta."""
    req = payload or PeiInicialRequest()
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
):
    """Envia as respostas do questionário à API de IA para gerar um PEI completo em formato .docx."""
    corpo = {
        "id_prof": professor.id_prof,
        **payload.model_dump(exclude_none=True),
        "respostas": [item.model_dump() for item in payload.respostas],
    }
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/pei",
        token=credentials.credentials,
        json_data=corpo,
    )


@AI_router.get("/pei/aluno/{id_aluno}")
async def listar_peis_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Lista os PEIs gerados pela IA para o aluno."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/pei",
        token=credentials.credentials,
    )


@AI_router.get("/pei/aluno/{id_aluno}/{pei_id}")
async def obter_pei_detalhe_ia(
    id_aluno: int,
    pei_id: str,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Obtém o documento completo de um PEI gerado."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/pei/{pei_id}",
        token=credentials.credentials,
    )


@AI_router.post("/pei/aluno/{id_aluno}/importar")
async def importar_pei_aluno_ia(
    id_aluno: int,
    payload: PeiImportarRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
):
    """Importa um arquivo de PEI existente (.pdf, .docx, .txt) para o aluno."""
    corpo = {"id_prof": professor.id_prof, **payload.model_dump(exclude_none=True)}
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/pei/importar",
        token=credentials.credentials,
        json_data=corpo,
    )


@AI_router.get("/pei/aluno/{id_aluno}/{pei_id}/docx")
async def baixar_pei_docx_ia(
    id_aluno: int,
    pei_id: str,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
) -> Response:
    """Baixa o arquivo .docx de um PEI gerado pela IA."""
    url = f"{IA_API_URL}/alunos/{id_aluno}/pei/{pei_id}/docx"
    headers = _obter_headers(credentials.credentials)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resposta = await client.get(url, headers=headers)
        if not resposta.is_success:
            raise HTTPException(
                status_code=resposta.status_code,
                detail=f"Erro ao baixar PEI: {resposta.text}",
            )
        return Response(
            content=resposta.content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": resposta.headers.get(
                    "content-disposition",
                    f'attachment; filename="PEI_aluno_{id_aluno}.docx"',
                )
            },
        )


@AI_router.post("/perfil/aluno/{id_aluno}")
async def gerar_perfil_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(exigir_conta_autorizada_ia)],
    sessao: Session = Depends(pegar_bd),
):
    """Solicita à IA a geração de síntese do perfil pedagógico e sincronização com o banco."""
    resposta = await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint=f"/alunos/{id_aluno}/perfil",
        token=credentials.credentials,
    )
    try:
        perfil_texto = resposta.get("perfil") or resposta.get("perfil_gerado")
        if perfil_texto:
            aluno = sessao.get(alunos, id_aluno)
            if aluno:
                aluno.perfil_ia = perfil_texto
                sessao.commit()
    except Exception as exc:
        print(f"[Aviso] Falha ao atualizar perfil_ia: {exc}")
        sessao.rollback()

    return resposta


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
):
    """Envia uma atividade para a IA gerar adaptações curriculares fundamentadas no DUA."""
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
):
    """Envia um arquivo de atividade para a IA gerar a atividade adaptada e devolver o arquivo .docx ou .pdf."""
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
    fmt = "pdf" if (formato or "").strip().lower() == "pdf" else "docx"
    url = f"{IA_API_URL}/alunos/{id_aluno}/atividades/{atividade_id}/{fmt}"
    headers = _obter_headers(credentials.credentials)
    media_type = (
        "application/pdf"
        if fmt == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        resposta = await client.get(url, headers=headers)
        if not resposta.is_success:
            raise HTTPException(
                status_code=resposta.status_code,
                detail=f"Erro ao baixar atividade adaptada: {resposta.text}",
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
    """Endpoint legado de eco/teste de texto (restrito a dev/homologação)."""
    from config.settings import settings

    if settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rota de teste indisponível em produção.",
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
    """Endpoint de homologação/teste para simular neurodivergências e perguntas (desativado em produção)."""
    from config.settings import settings

    if settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rota de simulação indisponível em ambiente de produção.",
        )
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/mock/simular",
        token="",
        json_data=payload.model_dump(),
        timeout=300.0,
    )
