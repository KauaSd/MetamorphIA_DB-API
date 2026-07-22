from pydantic import BaseModel
from fastapi import Form
from typing import Annotated
class LoginForm:
    def __init__(
        self,
        indentificador: Annotated[str, Form()],
        senhaProf: Annotated[str, Form()],
    ):
        self.indentificador = indentificador
        self.senhaProf = senhaProf
class Professor(BaseModel):
    nomeProf: str
    emailprof: str
    numprof : str
    senhaProf: str
    
class Aluno(BaseModel):
    nome: str
    idade: int
    turma: int
    neurodivergencia: str
    descricao: str
class Alunoschema(BaseModel):
    id_aluno: int
    nome_aluno: str
    neurodiv_aluno: str
    id_turma: int
    desc_aluno: str
    idade_aluno: int

    model_config = {"from_attributes": True}
class Token(BaseModel):
    access_token: str
    token_type: str

class Validar2FARequest(BaseModel):
    codigo: str