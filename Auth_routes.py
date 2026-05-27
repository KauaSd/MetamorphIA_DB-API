from fastapi import APIRouter, HTTPException
from DB_conn import engine, alunos, professores, mensagens, mensagem_al, select, Session
from pydantic import BaseModel

Auth_router = APIRouter(prefix="/autenticar", tags=["autenticar"])

class Professor(BaseModel):
    nomeProf: str
    senhaProf: str

@Auth_router.post("/autenticar/cadastro")
async def cadastrarProfessor(dadosForm: Professor):
    with Session(engine) as sessao:
        novo = professores(
            nome_prof=dadosForm.nomeProf,
            senha_prof=dadosForm.senhaProf
        )
        sessao.add(novo)
        sessao.commit()

    return {"mensagem": "Professor cadastrado check"}

@Auth_router.post("/autenticar/login")
async def logarProfessor(dadosForm: Professor):
    with Session(engine) as sessao:
        profResult = sessao.execute(
            select(professores).where(professores.c.nome_prof == dadosForm.nomeProf)).first()
                    
        if profResult is None:
            return {"erro": "Professor não encontrado :("}

        if profResult.senha_prof != dadosForm.senhaProf:
            return {"erro": "Senha incorreta"}
            
        return {"mensagem": "Professor logado com sucesso!"}

@Auth_router.get("/DeletaAluno/{id}")
async def DeletaAluno(id: int):
    with Session(engine) as db:
        aluno = db.get(alunos, id)
        if not aluno:
            raise HTTPException(status_code = 404, detail="aluno não encontrado")
        db.delete(aluno)
        db.commit() 
    return {"mensagem" : "Aluno apagado com sucesso"}

# Coloquei o async antes do def pq segundo a Claude é melhor no nosso contexto, já que seriam múltiplas pessoas logando ao mesmo tempo (o que só funciona com o async). 
# Mantive o prefix por motivos de organização e identificação das rotas. Mas vê o que for melhor aí.