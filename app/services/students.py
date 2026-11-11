from database import (
    Aluno as AlunoModel,
    IntegrityError,
    OperationalError,
    Session,
    Turma,
    Usuario,
    alunos,
    select,
)
from fastapi import HTTPException, status
from schemas.schemas import Aluno, EditaAlunoSchema, PesquisaAluno
from services.planos import obter_contexto_escola


def _validar_acesso_gerenciamento_turma(sessao: Session, id_prof: int, id_turma: int) -> dict:
    """Garante que a turma existe, pertence a uma escola e que o usuário é adm daquela escola."""
    usuario = sessao.get(Usuario, id_prof)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if usuario.tipo_usuario == "prof_institucional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Professores institucionais não podem criar, editar ou apagar alunos.",
        )

    turma = sessao.get(Turma, id_turma)
    if not turma:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turma não encontrada. Um aluno deve obrigatoriamente estar em uma turma válida.",
        )

    ctx = obter_contexto_escola(sessao, id_prof, turma.fk_Escola_id_escola)
    if ctx["papel"] != "adm":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador da escola pode criar, editar ou remover alunos.",
        )
    return ctx


def DeletaAluno(id_aluno: int, sessao: Session, id_prof: int):
    try:
        aluno = sessao.get(alunos, id_aluno)
        if not aluno:
            raise HTTPException(status_code=404, detail="aluno não encontrado")
        _validar_acesso_gerenciamento_turma(sessao, id_prof, aluno.fk_Turma_id_turma)
        sessao.delete(aluno)
        sessao.commit()
        return {"mensagem": "Aluno apagado com sucesso"}
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
            detail=f"Erro interno. Erro: {e}",
        )


def RecebeAluno(form: Aluno, sessao: Session, id_prof: int):
    try:
        if not form.turma:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Todo aluno deve estar vinculado a uma turma.",
            )
        ctx = _validar_acesso_gerenciamento_turma(sessao, id_prof, form.turma)

        alunos_na_turma = sessao.execute(
            select(AlunoModel).where(AlunoModel.fk_Turma_id_turma == form.turma)
        ).scalars().all()
        max_alunos = ctx["max_alunos"]
        if max_alunos is not None and len(alunos_na_turma) >= max_alunos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {max_alunos} alunos por turma atingido no plano '{ctx['plano']}'.",
                    "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["pro", "pro_plus", "institucional"],
                },
            )

        new = alunos(
            id_prof=id_prof,
            id_turma=form.turma,
            nome_aluno=form.nome,
            neurodiv_aluno=form.neurodivergencia,
            desc_aluno=form.descricao,
            idade_aluno=form.idade,
        )
        sessao.add(new)
        sessao.commit()
        sessao.refresh(new)
        return {
            "mensagem": "Aluno cadastrado com sucesso",
            "id_aluno": new.id_aluno,
            "id_turma": new.fk_Turma_id_turma,
        }
    except HTTPException:
        raise
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"aluno já cadastrado ou dados obrigatórios ausentes. Erro: {e}",
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
            detail=f"Erro interno. Erro: {e}",
        )


def ConsultaAluno(pesquisaAluno: PesquisaAluno, sessao: Session, id_prof: int):
    try:
        from database import User_esc

        escolas_vinculadas = select(User_esc.fk_Escola_id_escola).where(
            User_esc.fk_Usuario_id_usuario == id_prof
        )
        turmas_vinculadas = select(Turma.id_turma).where(
            Turma.fk_Escola_id_escola.in_(escolas_vinculadas)
        )
        query = select(alunos).where(
            alunos.nome_aluno.icontains(pesquisaAluno.nome),
            (alunos.id_prof == id_prof) | (alunos.fk_Turma_id_turma.in_(turmas_vinculadas)),
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
            detail=f"Erro interno. Erro: {e}",
        )


def EditaAluno(
    alunoed: EditaAlunoSchema,
    form: Aluno,
    sessao: Session,
    id_prof: int,
):
    aluno = sessao.get(alunos, alunoed.id)
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")

    _validar_acesso_gerenciamento_turma(sessao, id_prof, aluno.fk_Turma_id_turma)
    if form.turma != aluno.fk_Turma_id_turma:
        ctx_dest = _validar_acesso_gerenciamento_turma(sessao, id_prof, form.turma)
        alunos_na_turma_dest = sessao.execute(
            select(AlunoModel).where(AlunoModel.fk_Turma_id_turma == form.turma)
        ).scalars().all()
        max_alunos = ctx_dest["max_alunos"]
        if max_alunos is not None and len(alunos_na_turma_dest) >= max_alunos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "mensagem": f"Limite de {max_alunos} alunos por turma atingido na turma de destino.",
                    "codigo_erro": "LIMITE_PLANO_ATINGIDO",
                    "upgrade_sugerido": True,
                    "opcoes_upgrade": ["pro", "pro_plus", "institucional"],
                },
            )

    try:
        if aluno.nome_aluno != form.nome:
            aluno.nome_aluno = form.nome
        if aluno.idade_aluno != form.idade:
            aluno.idade_aluno = form.idade
        if aluno.id_turma != form.turma:
            aluno.id_turma = form.turma
        if aluno.neurodiv_aluno != form.neurodivergencia:
            aluno.neurodiv_aluno = form.neurodivergencia
        if aluno.desc_aluno != form.descricao:
            aluno.desc_aluno = form.descricao

        sessao.commit()
        sessao.refresh(aluno)
        return {"mensagem": "Aluno editado com sucesso"}
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Erro: Banco de dados indisponivel. Erro:{e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro: {e}",
        )
