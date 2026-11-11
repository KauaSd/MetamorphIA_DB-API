from datetime import datetime, timezone
import os
from typing import Annotated, Any, Optional

from database import (
    Session,
    Turma,
    alunos,
    conversas,
    mensagem_al,
    mensagens,
    pegar_bd,
    select,
)
from dependencies import pegar_professor_logado, security_scheme
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import httpx
from pydantic import BaseModel, Field
from services.planos import obter_contexto_escola

AI_router = APIRouter(prefix="/AI", tags=["AI"])

# URL base da API de Inteligência Artificial (Ia_metamorphia)
IA_API_URL = os.getenv("IA_API_URL", os.getenv("URL", "http://localhost:8001")).rstrip("/")


class TextoIA(BaseModel):
    txt: str


class ChatAlunoRequest(BaseModel):
    mensagem: str
    conversa_id: Optional[str] = Field(
        None,
        description="Opcional. Deixe vazio ou null na 1ª mensagem para criar uma nova conversa. Nas mensagens seguintes, repasse o conversa_id retornado.",
        json_schema_extra={"example": None},
    )


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


class AdaptarAtividadeRequest(BaseModel):
    atividade: str = Field(..., description="Descrição da atividade original")
    neurodivergencia: str = Field(..., description="Condição do estudante (TEA, TDAH, Dislexia, etc.)")
    ano_escolar: Optional[str] = None
    objetivo_pedagogico: Optional[str] = None


class PerguntaGeralRequest(BaseModel):
    pergunta: str


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


def _obter_headers(token: str) -> dict[str, str]:
    """Prepara os headers HTTP encaminhando o token JWT recebido para a API de IA."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


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
    professor: Annotated[Any, Depends(pegar_professor_logado)],
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

    corpo = {
        "id_prof": professor.id_prof,
        "mensagem": payload.mensagem,
        "conversa_id": cid,
        "historico": historico_conversa,
        "total_interacoes": total_interacoes,
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
            conversa_obj = sessao.get(conversas, final_conversa_id)
            if not conversa_obj:
                conversa_obj = conversas(
                    id_conversa=final_conversa_id,
                    id_aluno=id_aluno,
                    id_prof=professor.id_prof,
                    titulo=payload.mensagem[:50],
                )
                sessao.add(conversa_obj)
                sessao.flush()
            else:
                conversa_obj.atualizado_em = datetime.now(timezone.utc)

            msg_user = mensagens(
                id_prof=professor.id_prof,
                id_aluno=id_aluno,
                id_conversa=final_conversa_id,
                conteudo=payload.mensagem,
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
            msg_ia = mensagens(
                id_prof=professor.id_prof,
                id_aluno=id_aluno,
                id_conversa=final_conversa_id,
                conteudo=texto_ia,
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


@AI_router.get("/chat/aluno/{id_aluno}/conversas")
async def listar_conversas_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(pegar_professor_logado)],
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
    professor: Annotated[Any, Depends(pegar_professor_logado)],
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
        return {
            "conversa_id": conversa_id,
            "mensagens": [
                {
                    "role": m.role or "user",
                    "conteudo": m.conteudo or "",
                    "data": m.data_mensagem.isoformat() if m.data_mensagem else "",
                }
                for m in msgs
            ],
        }

    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/conversas/{conversa_id}",
        token=credentials.credentials,
    )


@AI_router.post("/pei/aluno/{id_aluno}/inicial")
async def criar_pei_inicial_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    professor: Annotated[Any, Depends(pegar_professor_logado)],
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
    professor: Annotated[Any, Depends(pegar_professor_logado)],
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
    _professor: Annotated[Any, Depends(pegar_professor_logado)],
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
    _professor: Annotated[Any, Depends(pegar_professor_logado)],
):
    """Obtém o documento completo de um PEI gerado."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/pei/{pei_id}",
        token=credentials.credentials,
    )


@AI_router.post("/perfil/aluno/{id_aluno}")
async def gerar_perfil_aluno_ia(
    id_aluno: int,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(pegar_professor_logado)],
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
    _professor: Annotated[Any, Depends(pegar_professor_logado)],
):
    """Consulta o dashboard consolidado do aluno junto à API de IA."""
    return await _encaminhar_requisicao_ia(
        metodo="GET",
        endpoint=f"/alunos/{id_aluno}/dashboard",
        token=credentials.credentials,
    )


@AI_router.post("/adaptar-atividade")
async def adaptar_atividade_ia(
    payload: AdaptarAtividadeRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(pegar_professor_logado)],
):
    """Envia uma atividade para a IA gerar adaptações curriculares fundamentadas no DUA."""
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/adaptar-atividade",
        token=credentials.credentials,
        json_data=payload.model_dump(),
    )


@AI_router.post("/perguntar")
async def perguntar_geral_ia(
    payload: PerguntaGeralRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    _professor: Annotated[Any, Depends(pegar_professor_logado)],
):
    """Envia uma consulta pedagógica direta para a API de IA com RAG e guardrails."""
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/perguntar",
        token=credentials.credentials,
        json_data=payload.model_dump(),
    )


@AI_router.get("/enviatxtuser/{txt}")
async def enviatxtuser(txt: str):
    """Endpoint legado de eco/teste de texto."""
    try:
        return {"mensagem": txt}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao processar o texto. Erro: {e}",
        )


@AI_router.post("/txtIA")
async def txtIA(
    IAtxt: TextoIA,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(security_scheme)
    ] = None,
):
    """Endpoint legado para envio de texto à IA, compatibilizado com httpx.AsyncClient e autenticação."""
    token = credentials.credentials if credentials else ""
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/query/perguntar",
        token=token,
        json_data={"pergunta": IAtxt.txt},
    )


@AI_router.post("/simular")
async def simular_ia_sem_login(payload: SimularIA):
    """Endpoint público (sem login) para enviar várias neurodivergências e perguntas e testar o alinhamento da IA."""
    return await _encaminhar_requisicao_ia(
        metodo="POST",
        endpoint="/mock/simular",
        token="",
        json_data=payload.model_dump(),
        timeout=300.0,
    )
