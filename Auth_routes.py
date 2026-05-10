from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session
from DB_conn import engine, professores

router = APIRouter()

class CadastroProfessor(BaseModel):
    nomeProf: str
    senhaProf: str

@router.post("/cadastro")
def cadastrarProfessor(dadosForm: CadastroProfessor):
    with Session(engine) as sessao:
        novo = professores(
            nome_prof=dadosForm.nomeProf,
            senha_prof=dadosForm.senhaProf
        )
        sessao.add(novo)
        sessao.commit()

    return {"mensagem": "Professor cadastrado check"}