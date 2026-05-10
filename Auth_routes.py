from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from DB_conn import engine, alunos, professores, mensagens, mensagem_al, select, Session
from pydantic import BaseModel

Auth_router = APIRouter()

class CadastroProfessor(BaseModel):
    nomeProf: str
    senhaProf: str

@Auth_router.post("/cadastro")
def cadastrarProfessor(dadosForm: CadastroProfessor):
    with Session(engine) as sessao:
        novo = professores(
            nome_prof=dadosForm.nomeProf,
            senha_prof=dadosForm.senhaProf
        )
        sessao.add(novo)
        sessao.commit()

    return {"mensagem": "Professor cadastrado check"}