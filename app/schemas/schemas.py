from typing import Annotated
import re
from fastapi import Form
from pydantic import BaseModel, field_validator, Field
from enum import Enum

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
    numprof: str
    senhaProf: str = Field(...) #os tres pontos (ellipsis) enfatiza que precisa desse campo (o louco é que isso é do proprio python)
    @field_validator("senhaProf")
    @classmethod
    def req_senha(cls, senha: str) -> str: #o classmethod é do proprio python, ele usa o cls ali dentro da função pra chamar a propria class
        if re.match(r"^.*(?=.{12,})(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*+=!?._-]).*$", senha): #sempre que vejo esse treco do re eu lembro do meme dos Hieróglifos (estranhamente eu to começando a entender)
            return senha
        else:
            raise ValueError(
                "digite uma senha com letras maiúsculas, minúsculas, caractere especial e números que tenha ao menos 12 caracteres"
            )




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

class Turma(BaseModel):
	nome: str

class TurmaSchema(BaseModel):
	id_turma: int


class Token(BaseModel):
    access_token: str
    token_type: str


class Validar2FARequest(BaseModel):
    codigo: str

class Tipo2FA(str, Enum):
    NONE = "none"
    TOTP = "totp"
    EMAIL = "email"
    SMS = "sms"


class PesquisaAluno(BaseModel):
    nome:str

class Professoredita(BaseModel):
    nomeProf: str
    emailprof: str
    numprof: str

class EditaAlunoSchema(BaseModel):
    id:int 