from datetime import date, datetime, timedelta, timezone
from config.settings import settings
from schemas.schemas import Tipo2FA
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy import Enum as sqlenum
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, declarative_base, relationship, synonym

_connect_args = (
    {"check_same_thread": False}
    if settings.BD_ACCESS.startswith("sqlite")
    else {}
)
engine = create_engine(settings.BD_ACCESS, connect_args=_connect_args)

base = declarative_base()

# Tabela associativa mantida por retrocompatibilidade
mensagem_al = Table(
    "mensag_al",
    base.metadata,
    Column("id_aluno", Integer, ForeignKey("aluno.id_aluno"), primary_key=True),
    Column("id_mensagem", Integer, ForeignKey("mensagem.id_mensagem"), primary_key=True),
)


class Plano(base):
    __tablename__ = "plano"
    id_plano = Column(Integer, primary_key=True, autoincrement=True)
    nome_plano = Column(String(100), unique=True, nullable=False)
    max_escolas = Column(Integer, nullable=True)
    max_turmas_por_escola = Column(Integer, nullable=True)
    max_alunos_por_turma = Column(Integer, nullable=True)


class Usuario(base):
    __tablename__ = "usuario"
    id_usuario = Column(Integer, primary_key=True, autoincrement=True)
    nome_usuario = Column(String(150), nullable=False)
    email_usuario = Column(String(150), unique=True, index=True, nullable=True)
    telefone_usuario = Column(String(20), unique=True, index=True, nullable=True)
    senha_usuario = Column(String(255), nullable=True)
    google_id = Column(String(150), unique=True, index=True, nullable=True)
    cpf_cnpj = Column(String(20), nullable=True)
    tipo_usuario = Column(String(50), nullable=False, default="normal")
    tags_usuario = Column(Text, nullable=True)

    # Synonyms para retrocompatibilidade total com código que referencia 'professores'
    id_prof = synonym("id_usuario")
    nome_prof = synonym("nome_usuario")
    email_prof = synonym("email_usuario")
    num_prof = synonym("telefone_usuario")
    senha_prof = synonym("senha_usuario")


class Contrato(base):
    __tablename__ = "contrato"
    id_cont = Column(Integer, primary_key=True, autoincrement=True)
    tipo_cont = Column(String(50), nullable=False, default="cpf")
    documento_cont = Column(String(20), nullable=True)
    email_institucional = Column(String(150), nullable=True)
    max_qtd_user = Column(Integer, nullable=False, default=1)
    max_qtd_turmas = Column(Integer, nullable=True)
    max_qtd_alunos = Column(Integer, nullable=True)
    max_qtd_escolas = Column(Integer, nullable=True)
    valor_contrato = Column(Numeric(10, 2), nullable=True)
    data_inicio = Column(Date, default=date.today)
    data_fim = Column(Date, default=lambda: date.today() + timedelta(days=30))
    status_contrato = Column(String(30), nullable=False, default="ativo")
    fk_Plano_id_plano = Column(Integer, ForeignKey("plano.id_plano"), nullable=False)


class Grupo(base):
    __tablename__ = "grupo"
    id_grupo = Column(Integer, primary_key=True, autoincrement=True)
    nome_grupo = Column(String(150), nullable=False)
    email_institucional = Column(String(150), nullable=True)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
    fk_Contrato_id_cont = Column(Integer, ForeignKey("contrato.id_cont"), nullable=True)


class Escola(base):
    __tablename__ = "escola"
    id_escola = Column(Integer, primary_key=True, autoincrement=True)
    nome_escola = Column(String(150), nullable=False)
    email_institucional = Column(String(150), nullable=True)
    fk_Grupo_id_grupo = Column(Integer, ForeignKey("grupo.id_grupo"), nullable=False)
    fk_Contrato_id_cont = Column(Integer, ForeignKey("contrato.id_cont"), nullable=True)


class User_grupo(base):
    __tablename__ = "user_grupo"
    id_user_grupo = Column(Integer, primary_key=True, autoincrement=True)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
    fk_Grupo_id_grupo = Column(Integer, ForeignKey("grupo.id_grupo"), nullable=False)
    papel = Column(String(50), nullable=False, default="professor")
    tags_areas = Column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("fk_Usuario_id_usuario", "fk_Grupo_id_grupo", name="uk_user_grupo"),
    )


class User_esc(base):
    __tablename__ = "user_esc"
    id_user_esc = Column(Integer, primary_key=True, autoincrement=True)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
    fk_Escola_id_escola = Column(Integer, ForeignKey("escola.id_escola"), nullable=False)
    papel = Column(String(50), nullable=False, default="professor")
    tags_areas = Column(Text, nullable=True)
    pode_chat = Column(Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint("fk_Usuario_id_usuario", "fk_Escola_id_escola", name="uk_user_esc"),
    )


class User_cont(base):
    __tablename__ = "user_cont"
    id_user_cont = Column(Integer, primary_key=True, autoincrement=True)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
    fk_Contrato_id_cont = Column(Integer, ForeignKey("contrato.id_cont"), nullable=False)
    eh_pagador = Column(Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint("fk_Usuario_id_usuario", "fk_Contrato_id_cont", name="uk_user_cont"),
    )


class Nota_fiscal(base):
    __tablename__ = "nota_fiscal"
    id_nota = Column(Integer, primary_key=True, autoincrement=True)
    valor_nota = Column(Numeric(10, 2), nullable=False)
    data_emissao = Column(Date, nullable=False, default=date.today)
    fk_Contrato_id_cont = Column(Integer, ForeignKey("contrato.id_cont"), nullable=False)


class Pgto(base):
    __tablename__ = "pgto"
    id_pgto = Column(Integer, primary_key=True, autoincrement=True)
    data_vencimento = Column(Date, nullable=False, default=lambda: date.today() + timedelta(days=30))
    status_pagamento = Column(String(50), nullable=False, default="Pendente")
    fk_Contrato_id_cont = Column(Integer, ForeignKey("contrato.id_cont"), nullable=False)


class Turma(base):
    __tablename__ = "turma"
    id_turma = Column(Integer, primary_key=True, autoincrement=True)
    nome_turma = Column(String(100), nullable=False)
    fk_Escola_id_escola = Column(Integer, ForeignKey("escola.id_escola"), nullable=False)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=True)

    id_escola = synonym("fk_Escola_id_escola")
    id_prof = synonym("fk_Usuario_id_usuario")


class Aluno(base):
    __tablename__ = "aluno"
    id_aluno = Column(Integer, primary_key=True, autoincrement=True)
    nome_aluno = Column(String(150), nullable=False)
    idade_aluno = Column(Integer, nullable=True)
    desc_aluno = Column(Text, nullable=True)
    neuro_aluno = Column(String(150), nullable=False)
    perfil_ia = Column(Text, nullable=True)
    fk_Turma_id_turma = Column(Integer, ForeignKey("turma.id_turma"), nullable=False)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=True)

    neurodiv_aluno = synonym("neuro_aluno")
    id_turma = synonym("fk_Turma_id_turma")
    id_prof = synonym("fk_Usuario_id_usuario")

    mensagens_rel = relationship(
        "Mensagem", secondary=mensagem_al, back_populates="alunos_rel"
    )


class chat(base):
    __tablename__ = "chat"
    id_chat = Column(String(100), primary_key=True)
    nome_chat = Column(String(100), nullable=True)
    fk_Aluno_id_aluno = Column(Integer, ForeignKey("aluno.id_aluno"), nullable=False)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    atualizado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    id_conversa = synonym("id_chat")
    titulo = synonym("nome_chat")
    id_aluno = synonym("fk_Aluno_id_aluno")
    id_prof = synonym("fk_Usuario_id_usuario")


class Mensagem(base):
    __tablename__ = "mensagem"
    id_mensagem = Column(Integer, primary_key=True, autoincrement=True)
    tipo_remetente = Column(String(50), nullable=False, default="user")
    texto_mensagem = Column(Text, nullable=True)
    anexo_mensagem = Column(Text, nullable=True)
    data_envio = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fk_chat_id_chat = Column(String(100), ForeignKey("chat.id_chat"), nullable=True)
    fk_Aluno_id_aluno = Column(Integer, ForeignKey("aluno.id_aluno"), nullable=True)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=True)

    role = synonym("tipo_remetente")
    conteudo = synonym("texto_mensagem")
    data_mensagem = synonym("data_envio")
    id_conversa = synonym("fk_chat_id_chat")
    id_aluno = synonym("fk_Aluno_id_aluno")
    id_prof = synonym("fk_Usuario_id_usuario")

    alunos_rel = relationship(
        "Aluno", secondary=mensagem_al, back_populates="mensagens_rel"
    )


class user2famethods(base):
    __tablename__ = "user_2fa_methods"
    id_methods = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(sqlenum(Tipo2FA), nullable=False)
    secret = Column(String, nullable=True)
    usa_verificacao = Column(Boolean, default=False)
    data_criacao = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"))


class user2facodes(base):
    __tablename__ = "user_2fa_codes"
    id_codigo = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(6))
    expira_em = Column(DateTime(timezone=True))
    tentativas = Column(Integer, default=0)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"))


# Aliases de classes para manter 100% de compatibilidade com imports legados
professores = Usuario
turmas = Turma
alunos = Aluno
conversas = chat
mensagens = Mensagem


PLANOS_PADRAO = {
    "basico": {"max_escolas": 3, "max_turmas_por_escola": 2, "max_alunos_por_turma": 2},
    "pro": {"max_escolas": 10, "max_turmas_por_escola": 5, "max_alunos_por_turma": 10},
    "pro_plus": {"max_escolas": 1, "max_turmas_por_escola": None, "max_alunos_por_turma": None},
    "institucional": {"max_escolas": None, "max_turmas_por_escola": None, "max_alunos_por_turma": None},
}


def garantir_planos_iniciais(sessao: Session) -> dict[str, Plano]:
    """Garante que os 4 planos base existam na tabela Plano e retorna um mapa por nome."""
    existentes = {
        p.nome_plano: p
        for p in sessao.execute(select(Plano)).scalars().all()
    }
    alterou = False
    for nome, cfg in PLANOS_PADRAO.items():
        if nome not in existentes:
            novo = Plano(
                nome_plano=nome,
                max_escolas=cfg["max_escolas"],
                max_turmas_por_escola=cfg["max_turmas_por_escola"],
                max_alunos_por_turma=cfg["max_alunos_por_turma"],
            )
            sessao.add(novo)
            existentes[nome] = novo
            alterou = True
    if alterou:
        sessao.commit()
        for p in existentes.values():
            sessao.refresh(p)
    return existentes


def pegar_bd():
    sessao = Session(engine)
    try:
        yield sessao
    finally:
        sessao.close()
