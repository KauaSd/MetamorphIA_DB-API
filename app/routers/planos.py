from database import Session, Usuario, pegar_bd
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, Response, status
from schemas.schemas import (
    AceitarConviteEscolaRequest,
    AdicionarProfessorRequest,
    AtualizarTagsRequest,
    ContratarPlanoRequest,
    ConvidarProfessorRequest,
    CriarEscolaRequest,
    EditarEscolaRequest,
)
import services.planos as fn_planos
from services.disciplinas import CATALOGO_DISCIPLINAS

Planos_router = APIRouter(tags=["planos-escolas-grupos"])


@Planos_router.get("/disciplinas")
def listar_disciplinas():
    return CATALOGO_DISCIPLINAS


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


@Planos_router.put("/escolas/{id_escola}")
def editar_escola(
    id_escola: int,
    dados: EditarEscolaRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.editar_escola_usuario(sessao, usuario_logado, id_escola, dados.nome_escola)


@Planos_router.delete("/escolas/{id_escola}")
def deletar_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.deletar_escola_usuario(sessao, usuario_logado, id_escola)


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


@Planos_router.get("/institucional/painel")
@Planos_router.get("/admin/institucional/painel")
def painel_institucional(
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.obter_painel_institucional(sessao, usuario_logado)


@Planos_router.get("/escolas/{id_escola}/codigo")
def obter_codigo_convite_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.obter_codigo_escola(sessao, usuario_logado, id_escola, regenerar=False)


@Planos_router.post("/escolas/{id_escola}/codigo/regenerar")
def regenerar_codigo_convite_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.obter_codigo_escola(sessao, usuario_logado, id_escola, regenerar=True)


@Planos_router.post("/escolas/{id_escola}/convites", status_code=status.HTTP_201_CREATED)
def convidar_professor_na_escola(
    id_escola: int,
    dados: ConvidarProfessorRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.convidar_professor_escola(sessao, usuario_logado, id_escola, dados)


@Planos_router.get("/escolas/{id_escola}/convites")
def listar_convites_na_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.listar_convites_escola(sessao, usuario_logado, id_escola)


@Planos_router.get("/escolas/convites/pendentes")
def listar_meus_convites_pendentes(
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.listar_convites_pendentes_usuario(sessao, usuario_logado)


@Planos_router.get("/escolas/convites/{id_convite}")
def obter_detalhe_convite(
    id_convite: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.obter_detalhe_convite_usuario(sessao, usuario_logado, id_convite)


@Planos_router.post("/escolas/convites/aceitar")
def aceitar_convite_na_escola(
    dados: AceitarConviteEscolaRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.aceitar_convite_escola(sessao, usuario_logado, dados)


@Planos_router.post("/escolas/convites/{id_convite}/recusar")
def recusar_convite_na_escola(
    id_convite: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.recusar_convite_escola(sessao, usuario_logado, id_convite)


@Planos_router.post("/escolas/{id_escola}/professores", status_code=status.HTTP_201_CREATED)
def adicionar_professor_na_escola(
    id_escola: int,
    dados: AdicionarProfessorRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.adicionar_professor_escola(sessao, usuario_logado, id_escola, dados)


@Planos_router.get("/escolas/{id_escola}/professores")
def listar_professores_na_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.listar_professores_escola(sessao, usuario_logado, id_escola)


@Planos_router.delete("/escolas/{id_escola}/professores/{id_usuario}")
def remover_professor_na_escola(
    id_escola: int,
    id_usuario: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.remover_professor_escola(sessao, usuario_logado, id_escola, id_usuario)


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


@Planos_router.get("/grupos/{id_grupo}/professores")
def listar_professores_no_grupo(
    id_grupo: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.listar_professores_grupo(sessao, usuario_logado, id_grupo)


@Planos_router.delete("/grupos/{id_grupo}/professores/{id_usuario}")
def remover_professor_no_grupo(
    id_grupo: int,
    id_usuario: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.remover_professor_grupo(sessao, usuario_logado, id_grupo, id_usuario)


@Planos_router.patch("/professores/{id_usuario}/tags")
def atualizar_tags(
    id_usuario: int,
    dados: AtualizarTagsRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    return fn_planos.atualizar_tags_professor(sessao, usuario_logado, id_usuario, dados)


@Planos_router.get("/escolas/{id_escola}/peis/resumo")
def obter_resumo_peis_da_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    """Retorna total de PEIs concluídos/esperados, último envio, próximo período e detalhamento por professor."""
    return fn_planos.obter_resumo_peis_escola(sessao, usuario_logado, id_escola)


@Planos_router.get("/escolas/{id_escola}/peis/download")
def baixar_todos_peis_escola(
    id_escola: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
) -> Response:
    """Baixa um .zip com todos os PEIs (.docx) dos alunos da escola (exclusivo ADM no modo ADM)."""
    zip_bytes, nome_zip = fn_planos.exportar_peis_zip_escola(sessao, usuario_logado, id_escola)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome_zip}"'},
    )


@Planos_router.get("/escolas/{id_escola}/turmas/{id_turma}/peis/download")
def baixar_peis_turma_escola(
    id_escola: int,
    id_turma: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
) -> Response:
    """Baixa um .zip com os PEIs (.docx) apenas dos alunos de uma turma específica."""
    zip_bytes, nome_zip = fn_planos.exportar_peis_zip_escola(
        sessao, usuario_logado, id_escola, id_turma=id_turma
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome_zip}"'},
    )


@Planos_router.get("/escolas/{id_escola}/alunos/{id_aluno}/peis/download")
def baixar_peis_aluno_escola(
    id_escola: int,
    id_aluno: int,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
) -> Response:
    """Baixa um .zip com os PEIs (.docx) de um aluno específico da escola."""
    zip_bytes, nome_zip = fn_planos.exportar_peis_zip_escola(
        sessao, usuario_logado, id_escola, id_aluno=id_aluno
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome_zip}"'},
    )
