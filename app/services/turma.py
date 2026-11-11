from database import (
    Escola,
    IntegrityError,
    OperationalError,
    Session,
    Turma,
    Usuario,
    select,
    turmas,
)
from fastapi import HTTPException, status
from schemas.schemas import Turma as TurmaRequest
from services.planos import obter_contexto_escola, obter_escola_padrao_usuario


def AdicionarTurma(sessao: Session, form: TurmaRequest, id_prof: int):
    try:
        usuario = sessao.get(Usuario, id_prof)
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        if usuario.tipo_usuario == "prof_institucional":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Professores institucionais não podem criar ou alterar turmas.",
            )

        id_escola = form.id_escola
        if not id_escola:
            escola_padrao = obter_escola_padrao_usuario(sessao, usuario)
            id_escola = escola_padrao.id_escola

        ctx = obter_contexto_escola(sessao, id_prof, id_escola)

        # Em escolas Pro+ e Institucional, apenas o adm pode configurar turmas
        if ctx["papel"] != "adm":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o administrador da escola pode criar ou editar turmas.",
            )

        turmas_escola = sessao.execute(
            select(Turma).where(Turma.fk_Escola_id_escola == id_escola)
        ).scalars().all()

        max_turmas = ctx["max_turmas"]
        if max_turmas is not None and len(turmas_escola) >= max_turmas:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {max_turmas} turmas por escola atingido no plano '{ctx['plano']}'.",
                    "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["pro", "pro_plus", "institucional"],
                },
            )

        new = turmas(
            id_prof=id_prof,
            fk_Escola_id_escola=id_escola,
            nome_turma=form.nome,
        )
        sessao.add(new)
        sessao.commit()
        sessao.refresh(new)
        return {
            "mensagem": "Turma cadastrada com sucesso",
            "id_turma": new.id_turma,
            "id_escola": new.fk_Escola_id_escola,
            "nome_turma": new.nome_turma,
        }
    except HTTPException:
        raise
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Erro: Turma já cadastrada ou dados obrigatórios ausentes. Erro:{e}",
        )
    except OperationalError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}",
        )
    except Exception as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro:{e}",
        )


def DeletaTurma(sessao: Session, id_turma: int, id_prof: int):
    try:
        turma = sessao.get(turmas, id_turma)
        if not turma:
            raise HTTPException(status_code=404, detail="Turma não encontrada")

        ctx = obter_contexto_escola(sessao, id_prof, turma.fk_Escola_id_escola)
        if ctx["papel"] != "adm":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para apagar esta turma",
            )
        sessao.delete(turma)
        sessao.commit()
        return {"mensagem": "Turma apagada com sucesso"}
    except HTTPException:
        raise
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro:{e}",
        )


def PesquisarTurma(sessao: Session, pesquisa: str, id_prof: int):
    try:
        from database import User_esc

        escolas_vinculadas = select(User_esc.fk_Escola_id_escola).where(
            User_esc.fk_Usuario_id_usuario == id_prof
        )
        query = select(turmas).where(
            turmas.nome_turma.icontains(pesquisa),
            (turmas.id_prof == id_prof) | (turmas.fk_Escola_id_escola.in_(escolas_vinculadas)),
        )
        result = sessao.execute(query).scalars().all()
        return result
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro:{e}",
        )
