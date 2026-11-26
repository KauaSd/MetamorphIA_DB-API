import io
import json
from typing import Annotated, Optional
import zipfile
from config.settings import settings
from database import OperationalError, Session, Tipo2FA, pegar_bd, professores
from dependencies import pegar_professor_logado, pegar_usuario_pendente_2fa
from fastapi import APIRouter, Cookie, Depends, Request, Response
from schemas.schemas import (
    AlternarModoRequest,
    AlterarSenhaRequest,
    GoogleAuthRequest,
    InstrucoesIARequest,
    LoginForm,
    MicrosoftAuthRequest,
    Professor,
    Professoredita,
    RecuperarSenhaRequest,
    RedefinirSenhaRequest,
    RefreshTokenRequest,
    Token,
    TutorialVistoRequest,
    Validar2FARequest,
    VerificarCodigoSenhaRequest,
)
from security import limiter
import services.mfa as fnmfa
import services.password_reset as pwd_reset
import services.users as users

Auth_router = APIRouter(prefix="/autenticar", tags=["autenticar"])


@Auth_router.get("/me")
def obter_meu_perfil(
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return users.obter_perfil_completo_usuario(sessao, professor_logado)


@Auth_router.post("/alternar-modo")
def alternar_modo_adm_professor(
    dados: Optional[AlternarModoRequest] = None,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    """Alterna o ADM de escola institucional entre 'adm' e 'professor'."""
    return users.alternar_modo_usuario(
        sessao, professor_logado, dados.modo if dados else None
    )


@Auth_router.post("/cadastro")
@limiter.limit("5/minute")
async def cadastrarProfessor(
    request: Request,
    dadosForm: Professor,
    sessao: Session = Depends(pegar_bd),
):
    return users.cria_prof(sessao, dadosForm)


@Auth_router.post("/login")
@limiter.limit("5/minute")
def logar(
    request: Request,
    dados: Annotated[LoginForm, Depends()],
    sessao: Annotated[Session, Depends(pegar_bd)],
) -> Token:
    return users.logarProfessor(dados, sessao)


@Auth_router.post("/google")
@limiter.limit("10/minute")
def logar_google(
    request: Request,
    dados: GoogleAuthRequest,
    sessao: Annotated[Session, Depends(pegar_bd)],
) -> Token:
    return users.logar_com_google(dados, sessao)


@Auth_router.post("/microsoft")
@limiter.limit("10/minute")
def logar_microsoft(
    request: Request,
    dados: MicrosoftAuthRequest,
    sessao: Annotated[Session, Depends(pegar_bd)],
) -> Token:
    return users.logar_com_microsoft(dados, sessao)


@Auth_router.post("/refresh")
@limiter.limit("20/minute")
def renovar_token(
    request: Request,
    sessao: Annotated[Session, Depends(pegar_bd)],
    dados: Optional[RefreshTokenRequest] = None,
    refresh_token_cookie: Optional[str] = Cookie(default=None, alias="refresh_token"),
) -> Token:
    token_raw = (dados.refresh_token if dados else None) or refresh_token_cookie
    return users.renovar_tokens_por_refresh(sessao, token_raw)


@Auth_router.post("/ativar2fa")
def ativar2fa(
    tipo_mfa: Tipo2FA,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return fnmfa.troca_user2famethods(
        sessao, professor_logado.id_prof, tipo_mfa, professor_logado.email_prof
    )


@Auth_router.post("/verificar-2fa")
@limiter.limit("5/minute")
def verificar(
    request: Request,
    dados: Validar2FARequest,
    dados_pendentes: Annotated[dict, Depends(pegar_usuario_pendente_2fa)],
    sessao: Annotated[Session, Depends(pegar_bd)],
) -> Token:
    return fnmfa.verificar2fa(dados, dados_pendentes, sessao)


@Auth_router.post("/confirma_totp")
def confirma_totp(
    sessao: Annotated[Session, Depends(pegar_bd)],
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return fnmfa.fn_confirma_totp(sessao, professor_logado.id_prof)


@Auth_router.post("/envia_token")
@limiter.limit("3/minute")
def token(
    request: Request,
    sessao: Annotated[Session, Depends(pegar_bd)],
    professor: Annotated[dict, Depends(pegar_usuario_pendente_2fa)],
):
    return fnmfa.envia_token(sessao, professor["id_prof"])


@Auth_router.delete("/deletaProfessor/{id_professor}")
def deletar(
    id_professor: int,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return users.deletaProfessor(sessao, id_professor, professor_logado.id_prof)


@Auth_router.put("/EditaProfessor/")
def editar(
    dados: Professoredita,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return users.EditaProfessor(sessao, professor_logado, dados)


@Auth_router.patch("/tutorial")
def atualizar_tutorial_visto(
    dados: TutorialVistoRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return users.atualizar_tutorial_visto_usuario(
        sessao,
        professor_logado,
        tutorial_visto=dados.tutorial_visto,
        tutorial_institucional_visto=dados.tutorial_institucional_visto,
    )


@Auth_router.patch("/instrucoes")
def atualizar_instrucoes_ia(
    dados: InstrucoesIARequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return users.atualizar_instrucoes_ia_usuario(sessao, professor_logado, dados.instrucoes_ia)


@Auth_router.post("/desconectar-todos")
def desconectar_todos_dispositivos(
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return users.desconectar_todos_dispositivos_usuario(sessao, professor_logado)


@Auth_router.post("/recuperar-senha")
@limiter.limit("3/minute")
def recuperar_senha(
    request: Request,
    dados: RecuperarSenhaRequest,
    sessao: Session = Depends(pegar_bd),
):
    return pwd_reset.solicitar_recuperacao_senha(sessao, dados)


@Auth_router.post("/verificar-codigo-senha")
@limiter.limit("5/minute")
def verificar_codigo_senha(
    request: Request,
    dados: VerificarCodigoSenhaRequest,
    sessao: Session = Depends(pegar_bd),
):
    return pwd_reset.verificar_codigo_recuperacao(sessao, dados)


@Auth_router.post("/redefinir-senha")
@limiter.limit("5/minute")
def redefinir_senha(
    request: Request,
    dados: RedefinirSenhaRequest,
    sessao: Session = Depends(pegar_bd),
):
    return pwd_reset.redefinir_senha_com_token(sessao, dados)


@Auth_router.put("/alterar-senha")
@limiter.limit("5/minute")
def alterar_senha(
    request: Request,
    dados: AlterarSenhaRequest,
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    return pwd_reset.alterar_senha_autenticado(sessao, professor_logado, dados)


@Auth_router.get("/exportar-dados")
def exportar_dados_lgpd(
    formato: str = "json",
    sessao: Session = Depends(pegar_bd),
    professor_logado: professores = Depends(pegar_professor_logado),
):
    dados = users.exportar_dados_usuario(sessao, professor_logado)
    if (formato or "json").strip().lower() == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "dados_metamorphia.json",
                json.dumps(dados, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="dados_metamorphia_usuario_{professor_logado.id_usuario}.zip"'
            },
        )
    return dados
