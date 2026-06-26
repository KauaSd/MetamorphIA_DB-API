from fastapi import APIRouter, HTTPException, status
from DB_conn import engine, professores, select, Session, IntegrityError, OperationalError
from pydantic import BaseModel

Auth_router = APIRouter(prefix="/autenticar", tags=["autenticar"])

class Professor(BaseModel):
    nomeProf: str
    senhaProf: str

@Auth_router.post("/autenticar/cadastro")
async def cadastrarProfessor(dadosForm: Professor):
    try:
        with Session(engine) as sessao:
            novo = professores(
                nome_prof=dadosForm.nomeProf,
                senha_prof=dadosForm.senhaProf
            )
            sessao.add(novo)
            sessao.commit()

        return {"mensagem": "Professor cadastrado check"}
    except IntegrityError as e:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Erro: Este professor já está cadastrado ou dados obrigatórios estão ausentes."
        )
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_CONFLICT,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno"
        )


@Auth_router.post("/autenticar/login")
async def logarProfessor(dadosForm: Professor):
    try:
        with Session(engine) as sessao:
            profResult = sessao.execute(
                select(professores).where(professores.c.nome_prof == dadosForm.nomeProf)).first()
                        
            if profResult is None:
                raise HTTPException(status_code = 404, detail="Erro: Professor não encontrado")

            if profResult.senha_prof != dadosForm.senhaProf:
                return {"erro": "Senha incorreta"}
                
            return {"mensagem": "Professor logado com sucesso!"}
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_CONFLICT,
            detail="Erro: Banco de dados indisponivel"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno"
        )
# fazer rota de consultar alunos, deletar alunos, editar, e receber em Al_routes.py