from database import Contrato, Escola, Plano, Session, Usuario, pegar_bd, select
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, Query, status
from schemas.schemas import AtualizarPerfilUsuarioRequest
from services.planos import invalidar_cache_permissoes

Admin_router = APIRouter(prefix="/admin/sistema", tags=["admin-sistema"])

_PERFIS_VALIDOS = {
    "normal",
    "prof_institucional",
    "adm_escola",
    "adm_institucional",
    "adm_sistema",
}


def _exigir_admin_sistema(
    usuario_logado: Usuario = Depends(pegar_professor_logado),
) -> Usuario:
    if usuario_logado.tipo_usuario != "adm_sistema":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao administrador do sistema.",
        )
    return usuario_logado


@Admin_router.get("/usuarios")
def listar_usuarios_sistema(
    limite: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sessao: Session = Depends(pegar_bd),
    _adm: Usuario = Depends(_exigir_admin_sistema),
):
    usuarios = sessao.execute(select(Usuario).offset(offset).limit(limite)).scalars().all()
    return [
        {
            "id_usuario": u.id_usuario,
            "nome_usuario": u.nome_usuario,
            "email_usuario": u.email_usuario,
            "telefone_usuario": u.telefone_usuario,
            "tipo_usuario": u.tipo_usuario,
            "tags_usuario": u.tags_usuario,
        }
        for u in usuarios
    ]


@Admin_router.patch("/usuarios/{id_usuario}/perfil")
def atualizar_perfil_usuario_sistema(
    id_usuario: int,
    dados: AtualizarPerfilUsuarioRequest,
    sessao: Session = Depends(pegar_bd),
    _adm: Usuario = Depends(_exigir_admin_sistema),
):
    novo_tipo = (dados.tipo_usuario or "").strip()
    if novo_tipo not in _PERFIS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Perfil inválido. Opções permitidas: {sorted(_PERFIS_VALIDOS)}",
        )
    usuario = sessao.get(Usuario, id_usuario)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    usuario.tipo_usuario = novo_tipo
    sessao.commit()
    invalidar_cache_permissoes()
    return {
        "mensagem": "Perfil do usuário atualizado com sucesso.",
        "id_usuario": usuario.id_usuario,
        "tipo_usuario": usuario.tipo_usuario,
    }


@Admin_router.get("/escolas")
def listar_todas_escolas_sistema(
    limite: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sessao: Session = Depends(pegar_bd),
    _adm: Usuario = Depends(_exigir_admin_sistema),
):
    escolas = sessao.execute(select(Escola).offset(offset).limit(limite)).scalars().all()
    return [
        {
            "id_escola": e.id_escola,
            "nome_escola": e.nome_escola,
            "email_institucional": e.email_institucional,
            "id_grupo": e.fk_Grupo_id_grupo,
            "id_contrato": e.fk_Contrato_id_cont,
        }
        for e in escolas
    ]


@Admin_router.get("/contratos")
def listar_contratos_sistema(
    limite: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sessao: Session = Depends(pegar_bd),
    _adm: Usuario = Depends(_exigir_admin_sistema),
):
    planos_map = {p.id_plano: p.nome_plano for p in sessao.execute(select(Plano)).scalars().all()}
    contratos = sessao.execute(select(Contrato).offset(offset).limit(limite)).scalars().all()
    return [
        {
            "id_cont": c.id_cont,
            "plano": planos_map.get(c.fk_Plano_id_plano),
            "tipo_cont": c.tipo_cont,
            "status_contrato": c.status_contrato,
            "max_qtd_user": c.max_qtd_user,
            "max_qtd_escolas": c.max_qtd_escolas,
            "max_qtd_turmas": c.max_qtd_turmas,
            "max_qtd_alunos": c.max_qtd_alunos,
        }
        for c in contratos
    ]
