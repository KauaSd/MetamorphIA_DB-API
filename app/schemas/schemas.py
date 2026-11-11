from enum import Enum
import re
from typing import Annotated, List, Optional
from fastapi import Form
from pydantic import BaseModel, Field, field_validator


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
    senhaProf: str = Field(...)
    cpf_cnpj: Optional[str] = None
    tags: Optional[List[str] | str] = None
    nome_escola_inicial: Optional[str] = None

    @field_validator("senhaProf")
    @classmethod
    def req_senha(cls, senha: str) -> str:
        if re.match(
            r"^.*(?=.{12,})(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*+=!?._-]).*$",
            senha,
        ):
            return senha
        raise ValueError(
            "digite uma senha com letras maiúsculas, minúsculas, caractere especial e números que tenha ao menos 12 caracteres"
        )


class GoogleAuthRequest(BaseModel):
    id_token: Optional[str] = None
    email: Optional[str] = None
    nome: Optional[str] = None
    google_id: Optional[str] = None


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
    desc_aluno: Optional[str] = None
    idade_aluno: Optional[int] = None

    model_config = {"from_attributes": True}


class Turma(BaseModel):
    nome: str
    id_escola: Optional[int] = None


class TurmaSchema(BaseModel):
    id_turma: int


class Token(BaseModel):
    access_token: str
    token_type: str
    requires_2fa: Optional[bool] = False


class Validar2FARequest(BaseModel):
    codigo: str


class Tipo2FA(str, Enum):
    NONE = "none"
    TOTP = "totp"
    EMAIL = "email"
    SMS = "sms"


class PesquisaAluno(BaseModel):
    nome: str


class Professoredita(BaseModel):
    nomeProf: str
    emailprof: str
    numprof: str
    tags: Optional[List[str] | str] = None


class EditaAlunoSchema(BaseModel):
    id: int


# Schemas para Planos, Contratos, Escolas, Grupos e Professores
class CriarEscolaRequest(BaseModel):
    nome_escola: str
    id_grupo: Optional[int] = None
    usar_plano: Optional[str] = None  # 'basico' ou 'pro'


class ContratarPlanoRequest(BaseModel):
    nome_plano: str  # 'basico', 'pro', 'pro_plus', 'institucional'
    tipo_cont: str = "cpf"  # 'cpf' ou 'cnpj'
    documento_cont: str
    email_institucional: Optional[str] = None
    nome_escola: Optional[str] = None
    id_escola: Optional[int] = None
    nome_grupo: Optional[str] = None
    escolas_ids: Optional[List[int]] = None
    max_qtd_user: Optional[int] = None
    max_qtd_turmas: Optional[int] = None
    max_qtd_alunos: Optional[int] = None
    max_qtd_escolas: Optional[int] = None
    adm_pode_chat: Optional[bool] = True
    valor_contrato: Optional[float] = None


class AdicionarProfessorRequest(BaseModel):
    nome: Optional[str] = None
    email: str
    telefone: Optional[str] = None
    senha: Optional[str] = None
    tags_areas: List[str] | str = Field(default_factory=list)
    escolas_ids: Optional[List[int]] = None


class AtualizarTagsRequest(BaseModel):
    tags_areas: List[str] | str
    id_escola: Optional[int] = None
    id_grupo: Optional[int] = None
