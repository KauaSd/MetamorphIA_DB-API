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

_is_sqlite = settings.BD_ACCESS.startswith("sqlite")
try:
    from pgvector.sqlalchemy import Vector as _PgVector
except ImportError:
    _PgVector = None
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
_engine_kwargs = (
    {"connect_args": _connect_args}
    if _is_sqlite
    else {
        "connect_args": _connect_args,
        "pool_size": 5,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
)
engine = create_engine(settings.BD_ACCESS, **_engine_kwargs)

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
    nome_real = Column(String(150), nullable=True)
    email_usuario = Column(String(150), unique=True, index=True, nullable=True)
    telefone_usuario = Column(String(20), unique=True, index=True, nullable=True)
    senha_usuario = Column(String(255), nullable=True)
    google_id = Column(String(150), unique=True, index=True, nullable=True)
    microsoft_id = Column(String(150), unique=True, index=True, nullable=True)
    cpf_cnpj = Column(String(20), nullable=True)
    tipo_usuario = Column(String(50), nullable=False, default="normal")
    modo_ativo = Column(String(30), nullable=False, default="adm")
    tags_usuario = Column(Text, nullable=True)
    instrucoes_ia = Column(Text, nullable=True)
    perfil_professor_feito = Column(Boolean, nullable=False, default=False)
    identificacao_feita = Column(Boolean, nullable=False, default=False)
    tutorial_visto = Column(Boolean, nullable=False, default=False)
    tutorial_institucional_visto = Column(Boolean, nullable=False, default=False)
    token_version = Column(Integer, nullable=False, default=1)

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
    codigo_convite = Column(String(20), nullable=True, unique=True, index=True)
    fk_Grupo_id_grupo = Column(Integer, ForeignKey("grupo.id_grupo"), nullable=False)
    fk_Contrato_id_cont = Column(Integer, ForeignKey("contrato.id_cont"), nullable=True)


class ConviteEscola(base):
    __tablename__ = "convite_escola"
    id_convite = Column(Integer, primary_key=True, autoincrement=True)
    fk_Escola_id_escola = Column(Integer, ForeignKey("escola.id_escola"), nullable=False, index=True)
    fk_Usuario_convidado_id = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=True, index=True)
    email_convidado = Column(String(150), nullable=False, index=True)
    codigo_convite = Column(String(20), nullable=False)
    tags_areas = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="pendente")
    criado_por_id = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    respondido_em = Column(DateTime(timezone=True), nullable=True)


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
    mp_preference_id = Column(String(150), nullable=True, index=True)
    mp_payment_id = Column(String(100), nullable=True, unique=True, index=True)
    mp_external_reference = Column(String(150), nullable=True, index=True)
    mp_status = Column(String(50), nullable=True)
    valor_pagamento = Column(Numeric(10, 2), nullable=True)
    metodo_pagamento = Column(String(50), nullable=True)
    data_pagamento = Column(DateTime(timezone=True), nullable=True)
    dados_ativacao_json = Column(Text, nullable=True)


class Turma(base):
    __tablename__ = "turma"
    id_turma = Column(Integer, primary_key=True, autoincrement=True)
    nome_turma = Column(String(100), nullable=False)
    serie_ano = Column(String(60), nullable=True)
    letra = Column(String(20), nullable=True)
    horario = Column(String(60), nullable=True)
    fk_Escola_id_escola = Column(Integer, ForeignKey("escola.id_escola"), nullable=False)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=True)

    id_escola = synonym("fk_Escola_id_escola")
    id_prof = synonym("fk_Usuario_id_usuario")


VALIDADE_PEI_DIAS = 60


def pei_esta_valido(aluno: "Aluno | None") -> bool:
    """Verifica se o aluno possui PEI concluído e dentro da validade bimestral (60 dias)."""
    if not aluno or not bool(getattr(aluno, "pei_feito", False)):
        return False
    valido_ate = getattr(aluno, "pei_valido_ate", None)
    if valido_ate is None:
        return False
    if valido_ate.tzinfo is None:
        valido_ate = valido_ate.replace(tzinfo=timezone.utc)
    return valido_ate > datetime.now(timezone.utc)


class Aluno(base):
    __tablename__ = "aluno"
    id_aluno = Column(Integer, primary_key=True, autoincrement=True)
    nome_aluno = Column(String(150), nullable=False)
    idade_aluno = Column(Integer, nullable=True)
    desc_aluno = Column(Text, nullable=True)
    neuro_aluno = Column(String(150), nullable=False)
    perfil_ia = Column(Text, nullable=True)
    indicadores_desenvolvimento_json = Column(Text, nullable=True)
    metas_bimestre_json = Column(Text, nullable=True)
    pei_feito = Column(Boolean, nullable=False, default=False)
    pei_valido_ate = Column(DateTime(timezone=True), nullable=True)
    fk_Turma_id_turma = Column(Integer, ForeignKey("turma.id_turma"), nullable=False)
    fk_Usuario_id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=True)

    neurodiv_aluno = synonym("neuro_aluno")
    id_turma = synonym("fk_Turma_id_turma")
    id_prof = synonym("fk_Usuario_id_usuario")

    @property
    def pei_ativo(self) -> bool:
        return pei_esta_valido(self)

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


class PasswordResetCode(base):
    __tablename__ = "password_reset_codes"
    id_reset = Column(Integer, primary_key=True, autoincrement=True)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False, index=True)
    codigo = Column(String(6), nullable=False)
    expira_em = Column(DateTime(timezone=True), nullable=False)
    tentativas = Column(Integer, nullable=False, default=0)
    usado = Column(Boolean, nullable=False, default=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ArquivoAnexo(base):
    __tablename__ = "arquivo_anexo"
    id_arquivo = Column(String(64), primary_key=True)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False, index=True)
    id_aluno = Column(Integer, ForeignKey("aluno.id_aluno"), nullable=True, index=True)
    id_conversa = Column(String(100), nullable=True, index=True)
    nome_arquivo = Column(String(255), nullable=False)
    mime_type = Column(String(150), nullable=False, default="application/octet-stream")
    tamanho_bytes = Column(Integer, nullable=False, default=0)
    caminho_arquivo = Column(String(500), nullable=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PeiDisciplina(base):
    __tablename__ = "pei_disciplina"
    id_pei_disciplina = Column(Integer, primary_key=True, autoincrement=True)
    id_aluno = Column(Integer, ForeignKey("aluno.id_aluno"), nullable=False, index=True)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False, index=True)
    disciplina = Column(String(120), nullable=False)
    status = Column(String(30), nullable=False, default="nao_iniciado")
    pei_id = Column(String(64), nullable=True)
    atualizado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RefreshToken(base):
    __tablename__ = "refresh_tokens"
    jti = Column(String(64), primary_key=True)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False, index=True)
    token_version = Column(Integer, nullable=False, default=1)
    expira_em = Column(DateTime(timezone=True), nullable=False)
    revogado = Column(Boolean, nullable=False, default=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UsoIA(base):
    __tablename__ = "uso_ia"
    id = Column(Integer, primary_key=True, autoincrement=True)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, index=True)  # "adaptacao" | "pei"
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class AlunoMemoriaVetorial(base):
    """Armazena chunks vetorizados (pgvector 384d) de PEIs e vivências por aluno."""

    __tablename__ = "aluno_memoria_vetorial"
    id_vetor = Column(Integer, primary_key=True, autoincrement=True)
    id_aluno = Column(Integer, ForeignKey("aluno.id_aluno", ondelete="CASCADE"), nullable=False, index=True)
    id_prof = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="SET NULL"), nullable=True, index=True)
    origem = Column(String(40), nullable=False, index=True)  # "pei" | "relato_chat" | "cadastro"
    disciplina = Column(String(120), nullable=True, index=True)
    pei_id = Column(String(64), nullable=True, index=True)
    conversa_id = Column(String(100), nullable=True, index=True)
    texto_chunk = Column(Text, nullable=False)
    hash_chunk = Column(String(64), nullable=False, index=True)
    embedding = Column(
        _PgVector(384) if (not _is_sqlite and _PgVector is not None) else Text,
        nullable=False,
    )
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


# Aliases de classes para manter 100% de compatibilidade com imports legados
professores = Usuario
turmas = Turma
alunos = Aluno
conversas = chat
mensagens = Mensagem


PLANOS_PADRAO = {
    "normal": {"max_escolas": 3, "max_turmas_por_escola": 2, "max_alunos_por_turma": 5},
    "pro": {"max_escolas": 10, "max_turmas_por_escola": None, "max_alunos_por_turma": 30},
    "institucional": {"max_escolas": 1, "max_turmas_por_escola": None, "max_alunos_por_turma": None},
    "institucional_plus": {"max_escolas": None, "max_turmas_por_escola": None, "max_alunos_por_turma": None},
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
        else:
            plano_atual = existentes[nome]
            if (
                plano_atual.max_escolas != cfg["max_escolas"]
                or plano_atual.max_turmas_por_escola != cfg["max_turmas_por_escola"]
                or plano_atual.max_alunos_por_turma != cfg["max_alunos_por_turma"]
            ):
                plano_atual.max_escolas = cfg["max_escolas"]
                plano_atual.max_turmas_por_escola = cfg["max_turmas_por_escola"]
                plano_atual.max_alunos_por_turma = cfg["max_alunos_por_turma"]
                alterou = True
    if alterou:
        sessao.commit()
        for p in existentes.values():
            sessao.refresh(p)
    return {k: existentes[k] for k in PLANOS_PADRAO if k in existentes}


def _corrigir_fks_legadas_postgres(eng) -> None:
    """Corrige FKs antigas em user_2fa_methods/user_2fa_codes que apontavam para 'professores' em vez de 'usuario'."""
    if eng.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    DO $$
                    DECLARE
                        r RECORD;
                    BEGIN
                        FOR r IN (
                            SELECT tc.table_name, tc.constraint_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.constraint_column_usage ccu
                              ON tc.constraint_name = ccu.constraint_name
                             AND tc.table_schema = ccu.table_schema
                            WHERE tc.constraint_type = 'FOREIGN KEY'
                              AND tc.table_name IN ('user_2fa_methods', 'user_2fa_codes')
                              AND ccu.table_name = 'professores'
                        ) LOOP
                            EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', r.table_name, r.constraint_name);
                        END LOOP;
                    END $$;
                    """
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE user_2fa_methods DROP CONSTRAINT IF EXISTS fk_user_2fa_professores"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE user_2fa_codes DROP CONSTRAINT IF EXISTS fk_user_2fa_codes_professores"
                )
            )
    except Exception as exc:
        print(f"[Aviso] Não foi possível ajustar FKs legadas no PostgreSQL: {exc}")


def _garantir_colunas_novas(eng) -> None:
    """Adiciona colunas novas em usuario e aluno caso o banco já existisse antes da atualização."""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(eng)
        comandos: list[str] = []
        if insp.has_table("usuario"):
            colunas_usuario = {c["name"] for c in insp.get_columns("usuario")}
            if "microsoft_id" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN microsoft_id VARCHAR(150)")
            if "instrucoes_ia" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN instrucoes_ia TEXT")
            if "token_version" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1")
            if "modo_ativo" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN modo_ativo VARCHAR(30) NOT NULL DEFAULT 'adm'")
            if "nome_real" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN nome_real VARCHAR(150)")
            if "perfil_professor_feito" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN perfil_professor_feito BOOLEAN NOT NULL DEFAULT FALSE")
            if "identificacao_feita" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN identificacao_feita BOOLEAN NOT NULL DEFAULT FALSE")
            if "tutorial_visto" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN tutorial_visto BOOLEAN NOT NULL DEFAULT FALSE")
            if "tutorial_institucional_visto" not in colunas_usuario:
                comandos.append("ALTER TABLE usuario ADD COLUMN tutorial_institucional_visto BOOLEAN NOT NULL DEFAULT FALSE")
        if insp.has_table("aluno"):
            colunas_aluno = {c["name"] for c in insp.get_columns("aluno")}
            tipo_ts = "TIMESTAMPTZ" if eng.dialect.name == "postgresql" else "TIMESTAMP"
            if "pei_feito" not in colunas_aluno:
                comandos.append("ALTER TABLE aluno ADD COLUMN pei_feito BOOLEAN NOT NULL DEFAULT FALSE")
            if "pei_valido_ate" not in colunas_aluno:
                comandos.append(f"ALTER TABLE aluno ADD COLUMN pei_valido_ate {tipo_ts}")
            if "indicadores_desenvolvimento_json" not in colunas_aluno:
                comandos.append("ALTER TABLE aluno ADD COLUMN indicadores_desenvolvimento_json TEXT")
            if "metas_bimestre_json" not in colunas_aluno:
                comandos.append("ALTER TABLE aluno ADD COLUMN metas_bimestre_json TEXT")
        if insp.has_table("turma"):
            colunas_turma = {c["name"] for c in insp.get_columns("turma")}
            if "serie_ano" not in colunas_turma:
                comandos.append("ALTER TABLE turma ADD COLUMN serie_ano VARCHAR(60)")
            if "letra" not in colunas_turma:
                comandos.append("ALTER TABLE turma ADD COLUMN letra VARCHAR(20)")
            if "horario" not in colunas_turma:
                comandos.append("ALTER TABLE turma ADD COLUMN horario VARCHAR(60)")
        if insp.has_table("escola"):
            colunas_escola = {c["name"] for c in insp.get_columns("escola")}
            if "codigo_convite" not in colunas_escola:
                comandos.append("ALTER TABLE escola ADD COLUMN codigo_convite VARCHAR(20)")
        if comandos:
            with eng.begin() as conn:
                for sql in comandos:
                    conn.execute(text(sql))
    except Exception as exc:
        print(f"[Aviso] Não foi possível migrar colunas novas: {exc}")


def _garantir_extensao_e_indices_pgvector(eng) -> None:
    """Habilita extensão pgvector e índice HNSW no PostgreSQL."""
    if eng.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:
        print(f"[Aviso] Não foi possível habilitar extensão pgvector: {exc}")


def _garantir_indice_hnsw_pgvector(eng) -> None:
    if eng.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_aluno_vetor_hnsw "
                    "ON aluno_memoria_vetorial USING hnsw (embedding vector_cosine_ops)"
                )
            )
    except Exception as exc:
        print(f"[Aviso] Não foi possível criar índice HNSW pgvector: {exc}")


def _inicializar_banco_com_fallback() -> None:
    """Garante que o banco esteja acessível e com as tabelas criadas (fallback local apenas fora de produção)."""
    global engine
    try:
        _garantir_extensao_e_indices_pgvector(engine)
        base.metadata.create_all(bind=engine)
        _garantir_colunas_novas(engine)
        _corrigir_fks_legadas_postgres(engine)
        _garantir_indice_hnsw_pgvector(engine)
    except Exception as exc:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(f"Falha ao conectar/inicializar o banco de produção: {exc}") from exc
        if not settings.BD_ACCESS.startswith("sqlite"):
            print(f"[Aviso] Banco remoto indisponível ({exc}). Usando SQLite local para testes.")
            sqlite_path = Path(__file__).resolve().parent / "metamorphia_local.db"
            engine = create_engine(
                f"sqlite:///{sqlite_path}",
                connect_args={"check_same_thread": False},
            )
            base.metadata.create_all(bind=engine)
            _garantir_colunas_novas(engine)


from pathlib import Path as _Path  # noqa: E402
Path = _Path
_inicializar_banco_com_fallback()


def pegar_bd():
    sessao = Session(engine)
    try:
        yield sessao
    finally:
        sessao.close()
