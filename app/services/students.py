from typing import List

from database import (
    IntegrityError,
    OperationalError,
    Session,
    alunos,
    pegar_bd,
    professores,
    select,
)
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, HTTPException, status
from schemas.schemas import Aluno, Alunoschema, PesquisaAluno, EditaAlunoSchema


def DeletaAluno(
    id_aluno: int,
    sessao: Session ,
    id_prof: int
):
    try:
        aluno = sessao.get(alunos, id_aluno)
        if not aluno:
            raise HTTPException(status_code=404, detail="aluno não encontrado")
        if aluno.id_prof != id_prof:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para apagar este aluno",
            )
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


def RecebeAluno(
    form: Aluno,
    sessao: Session,
    id_prof: int
):
    try:
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
        return {"mensagem": "Aluno cadastrado com sucesso"}
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
        print(e)
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno. Erro: {e}",
        )
    

def ConsultaAluno(
    pesquisaAluno: PesquisaAluno,
    sessao: Session,
    id_prof: int
):
    try:
        query = select(alunos).where(alunos.id_prof == id_prof, alunos.nome_aluno.icontains(pesquisaAluno.nome))
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
    id_prof: int
):
    stmt = select(alunos).where(alunos.id_prof == id_prof, alunos.id_aluno == alunoed.id)
    aluno = sessao.execute(stmt).scalar_one_or_none()
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")

    try:
            if aluno.nome_aluno!=form.nome:
                aluno.nome_aluno=form.nome
            if aluno.idade_aluno!=form.idade:
                aluno.idade_aluno=form.idade
            if aluno.id_turma!=form.turma:
                aluno.id_turma=form.turma
            if aluno.neurodiv_aluno!=form.neurodivergencia:
                aluno.neurodiv_aluno=form.neurodivergencia
            if aluno.desc_aluno!=form.descricao:
                aluno.desc_aluno=form.descricao


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
