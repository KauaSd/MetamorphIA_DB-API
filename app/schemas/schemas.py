from datetime import datetime
from enum import Enum
import re
from typing import Annotated, List, Optional
from fastapi import Form
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SENHA_FORTE_REGEX = re.compile(
    r"^.*(?=.{12,})(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*+=!?._-]).*$"
)


def _validar_email_formato(email: str) -> str:
    limpo = (email or "").strip().lower()
    if not _EMAIL_REGEX.match(limpo) or len(limpo) > 150:
        raise ValueError("Formato de e-mail inválido.")
    return limpo


def _validar_senha_forte(senha: str) -> bool:
    return bool(
        len(senha) >= 12
        and re.search(r"\d", senha)
        and re.search(r"[a-z]", senha)
        and re.search(r"[A-Z]", senha)
        and re.search(r"[^A-Za-z0-9\s]", senha)
    )


class LoginForm:
    def __init__(
        self,
        indentificador: Annotated[str, Form()],
        senhaProf: Annotated[str, Form()],
    ):
        self.indentificador = indentificador
        self.senhaProf = senhaProf


class Professor(BaseModel):
    nomeProf: str = Field(..., min_length=1, max_length=150)
    emailprof: Optional[str] = Field(None, max_length=150)
    numprof: Optional[str] = Field(None, max_length=30)
    senhaProf: str = Field(...)
    cpf_cnpj: Optional[str] = Field(None, max_length=20)
    tags: Optional[List[str] | str] = None
    nome_escola_inicial: Optional[str] = Field(None, max_length=150)

    @field_validator("emailprof")
    @classmethod
    def validar_email(cls, email: Optional[str]) -> Optional[str]:
        if email is None or not email.strip():
            return None
        return _validar_email_formato(email)

    @field_validator("numprof")
    @classmethod
    def validar_numprof(cls, num: Optional[str]) -> Optional[str]:
        if num is None or not num.strip():
            return None
        apenas_digitos = re.sub(r"\D", "", num)
        return apenas_digitos or num.strip()

    @field_validator("senhaProf")
    @classmethod
    def req_senha(cls, senha: str) -> str:
        if _validar_senha_forte(senha):
            return senha
        raise ValueError(
            "digite uma senha com letras maiúsculas, minúsculas, caractere especial e números que tenha ao menos 12 caracteres"
        )


class GoogleAuthRequest(BaseModel):
    id_token: Optional[str] = Field(None, max_length=4096)
    email: Optional[str] = Field(None, max_length=150)
    nome: Optional[str] = Field(None, max_length=150)
    google_id: Optional[str] = Field(None, max_length=150)


class MicrosoftAuthRequest(BaseModel):
    id_token: Optional[str] = Field(None, max_length=4096)
    access_token: Optional[str] = Field(None, max_length=4096)
    email: Optional[str] = Field(None, max_length=150)
    nome: Optional[str] = Field(None, max_length=150)
    microsoft_id: Optional[str] = Field(None, max_length=150)


class Aluno(BaseModel):
    nome: str = Field(..., min_length=1, max_length=150)
    idade: int = Field(..., ge=0, le=120)
    turma: int = Field(..., gt=0)
    neurodivergencia: str = Field(..., min_length=1, max_length=150)
    descricao: str = Field(default="", max_length=5000)


class Alunoschema(BaseModel):
    id_aluno: int
    nome_aluno: str
    neurodiv_aluno: str
    id_turma: int
    desc_aluno: Optional[str] = None
    perfil_ia: Optional[str] = None
    idade_aluno: Optional[int] = None
    pei_feito: bool = False
    pei_valido_ate: Optional[datetime] = None
    pei_ativo: bool = False

    model_config = {"from_attributes": True}


class Turma(BaseModel):
    nome: Optional[str] = Field(None, max_length=100)
    serie_ano: Optional[str] = Field(
        None,
        max_length=60,
        validation_alias=AliasChoices("serie_ano", "serie", "ano_escolar"),
    )
    letra: Optional[str] = Field(None, max_length=20)
    horario: Optional[str] = Field(None, max_length=60)
    id_escola: Optional[int] = Field(None, gt=0)

    @model_validator(mode="after")
    def _garantir_nome_turma(self) -> "Turma":
        nome_limpo = (self.nome or "").strip()
        if not nome_limpo and self.serie_ano and self.serie_ano.strip():
            partes = [self.serie_ano.strip()]
            if self.letra and self.letra.strip():
                partes.append(self.letra.strip())
            nome_limpo = " ".join(partes)
            if self.horario and self.horario.strip():
                nome_limpo = f"{nome_limpo} - {self.horario.strip()}"
        if not nome_limpo:
            raise ValueError("Informe o nome ou a série/ano da turma.")
        self.nome = nome_limpo[:100]
        return self


class TurmaSchema(BaseModel):
    id_turma: int = Field(..., gt=0)


class Token(BaseModel):
    access_token: str
    token_type: str
    requires_2fa: Optional[bool] = False
    refresh_token: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = Field(None, min_length=10, max_length=4096)


class Validar2FARequest(BaseModel):
    codigo: str = Field(..., min_length=4, max_length=10)


class Tipo2FA(str, Enum):
    NONE = "none"
    TOTP = "totp"
    EMAIL = "email"
    SMS = "sms"


class PesquisaAluno(BaseModel):
    nome: str = Field(default="", max_length=150)


class Professoredita(BaseModel):
    nomeProf: Optional[str] = Field(None, max_length=150)
    nomeReal: Optional[str] = Field(None, max_length=150)
    emailprof: Optional[str] = Field(None, max_length=150)
    numprof: Optional[str] = Field(None, max_length=30)
    tags: Optional[List[str] | str] = None
    instrucoes_ia: Optional[str] = Field(None, max_length=3000)

    @field_validator("emailprof")
    @classmethod
    def validar_email(cls, email: Optional[str]) -> Optional[str]:
        if email is None or not email.strip():
            return None
        return _validar_email_formato(email)


class InstrucoesIARequest(BaseModel):
    instrucoes_ia: str = Field(default="", max_length=3000)


class TutorialVistoRequest(BaseModel):
    tutorial_visto: Optional[bool] = None
    tutorial_institucional_visto: Optional[bool] = None


class RecuperarSenhaRequest(BaseModel):
    identificador: str = Field(..., min_length=3, max_length=150)


class VerificarCodigoSenhaRequest(BaseModel):
    identificador: str = Field(..., min_length=3, max_length=150)
    codigo: str = Field(..., min_length=4, max_length=10)


class RedefinirSenhaRequest(BaseModel):
    reset_token: str = Field(..., min_length=10, max_length=4096)
    nova_senha: str = Field(...)

    @field_validator("nova_senha")
    @classmethod
    def validar_nova_senha(cls, senha: str) -> str:
        if _validar_senha_forte(senha):
            return senha
        raise ValueError(
            "digite uma senha com letras maiúsculas, minúsculas, caractere especial e números que tenha ao menos 12 caracteres"
        )


class AlterarSenhaRequest(BaseModel):
    senha_atual: Optional[str] = Field(None)
    nova_senha: str = Field(...)

    @field_validator("nova_senha")
    @classmethod
    def validar_nova_senha(cls, senha: str) -> str:
        if _validar_senha_forte(senha):
            return senha
        raise ValueError(
            "digite uma senha com letras maiúsculas, minúsculas, caractere especial e números que tenha ao menos 12 caracteres"
        )


class EditaAlunoSchema(BaseModel):
    id: int = Field(..., gt=0)


# Schemas para Planos, Contratos, Escolas, Grupos e Professores
class CriarEscolaRequest(BaseModel):
    nome_escola: str = Field(..., min_length=2, max_length=150)
    id_grupo: Optional[int] = Field(None, gt=0)
    usar_plano: Optional[str] = Field(None, max_length=30)  # 'normal' ou 'pro'


class EditarEscolaRequest(BaseModel):
    nome_escola: str = Field(..., min_length=2, max_length=150)


class ContratarPlanoRequest(BaseModel):
    nome_plano: str = Field(..., max_length=40)  # 'normal', 'pro', 'institucional', 'institucional_plus'
    tipo_cont: str = "cpf"  # 'cpf' ou 'cnpj'
    documento_cont: str = Field(..., min_length=11, max_length=20)
    email_institucional: Optional[str] = Field(None, max_length=150)
    nome_escola: Optional[str] = Field(None, max_length=150)
    id_escola: Optional[int] = Field(None, gt=0)
    nome_grupo: Optional[str] = Field(None, max_length=150)
    escolas_ids: Optional[List[int]] = None
    adm_pode_chat: Optional[bool] = True


class AdicionarProfessorRequest(BaseModel):
    nome: Optional[str] = Field(None, min_length=2, max_length=150)
    email: str = Field(..., max_length=150)
    telefone: Optional[str] = Field(None, min_length=8, max_length=20)
    senha: Optional[str] = None
    tags_areas: List[str] | str = Field(default_factory=list)
    escolas_ids: Optional[List[int]] = None

    @field_validator("email")
    @classmethod
    def validar_email(cls, email: str) -> str:
        return _validar_email_formato(email)

    @field_validator("senha")
    @classmethod
    def validar_senha_opcional(cls, senha: Optional[str]) -> Optional[str]:
        if senha is None or senha == "":
            return None
        if _SENHA_FORTE_REGEX.match(senha):
            return senha
        raise ValueError(
            "A senha deve ter ao menos 12 caracteres com maiúsculas, minúsculas, números e caractere especial."
        )


class ConvidarProfessorRequest(BaseModel):
    email: str = Field(..., max_length=150)
    tags_areas: List[str] | str = Field(default_factory=list)
    link_base: Optional[str] = Field(None, max_length=300)

    @field_validator("email")
    @classmethod
    def validar_email_convite(cls, email: str) -> str:
        return _validar_email_formato(email)


class AceitarConviteEscolaRequest(BaseModel):
    codigo_convite: str = Field(..., min_length=4, max_length=20)
    id_convite: Optional[int] = Field(None, gt=0)


class AtualizarTagsRequest(BaseModel):
    tags_areas: List[str] | str
    id_escola: Optional[int] = Field(None, gt=0)
    id_grupo: Optional[int] = Field(None, gt=0)


class CheckoutPlanoRequest(ContratarPlanoRequest):
    success_url: Optional[str] = Field(None, max_length=500)
    failure_url: Optional[str] = Field(None, max_length=500)
    pending_url: Optional[str] = Field(None, max_length=500)
    notification_url: Optional[str] = Field(None, max_length=500)


class SincronizarPagamentoRequest(BaseModel):
    mp_payment_id: str = Field(..., min_length=1, max_length=100)


class AtualizarPerfilUsuarioRequest(BaseModel):
    tipo_usuario: str = Field(..., max_length=50)


class AlternarModoRequest(BaseModel):
    modo: Optional[str] = Field(
        default=None,
        description="Opcional: 'professor' ou 'adm'. Se omitido, alterna entre os dois modos.",
    )
