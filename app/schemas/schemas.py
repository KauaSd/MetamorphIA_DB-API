from pydantic import BaseModel
from fastapi import Form
from typing import Annotated
class LoginForm:
    def __init__(
        self,
        nomeProf: Annotated[str, Form()],
        senhaProf: Annotated[str, Form()],
    ):
        self.nomeProf = nomeProf
        self.senhaProf = senhaProf
class Professor(BaseModel):
    nomeProf: str
    senhaProf: str
    
class Aluno(BaseModel):
    nome: str
    idade: int
    serie: str
    neurodivergencia: str
    diagnosticado: bool
    descricao: str
class Alunoschema(BaseModel):
    id_aluno: int
    nome_aluno: str
    neurodiv_aluno: str
    serie_aluno: str
    diag_aluno: bool
    desc_aluno: str
    idade_aluno: int

    model_config = {"from_attributes": True}
class Token(BaseModel):
    access_token: str
    token_type: str

