from database import Session, Usuario, pegar_bd
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, status
from schemas.schemas import (
    AdicionarProfessorRequest,
    AtualizarTagsRequest,
    ContratarPlanoRequest,
    CriarEscolaRequest,
)
import services.planos as fn_planos

Planos_router = APIRouter(tags=["planos-escolas-grupos"])


@Planos_router.post("/escolas", status_code=status.HTTP_201_CREATED)
def criar_escola(
    dados: CriarEscolaRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.criar_escola_no_grupo(sessao, usuario_logado, dados)


@Planos_router.get("/escolas")
def listar_escolas(
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.listar_escolas_usuario(sessao, usuario_logado)


@Planos_router.get("/escolas/{id_escola}/contexto")
def contexto_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.obter_contexto_escola(sessao, usuario_logado.id_usuario, id_escola)


@Planos_router.post("/planos/contratar")
@Planos_router.put("/planos/trocar")
def contratar_plano(
    dados: ContratarPlanoRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.contratar_ou_trocar_plano(sessao, usuario_logado, dados)


@Planos_router.post("/escolas/{id_escola}/professores", status_code=status.HTTP_201_CREATED)
def adicionar_professor_na_escola(
    id_escola: int,
    dados: AdicionarProfessorRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.adicionar_professor_escola(sessao, usuario_logado, id_escola, dados)


@Planos_router.post("/grupos/{id_grupo}/professores", status_code=status.HTTP_201_CREATED)
def adicionar_professor_no_grupo(
    id_grupo: int,
    dados: AdicionarProfessorRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.adicionar_professor_grupo_institucional(
        sessao, usuario_logado, id_grupo, dados
    )


@Planos_router.patch("/professores/{id_usuario}/tags")
def atualizar_tags(
    id_usuario: int,
    dados: AtualizarTagsRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.atualizar_tags_professor(sessao, usuario_logado, id_usuario, dados)
