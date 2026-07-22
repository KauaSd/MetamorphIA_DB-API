from sqlalchemy import create_engine, Column,Integer,select, String, ForeignKey, Date, Table, Boolean, DateTime, Enum as sqlenum
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import declarative_base, relationship, Session
from enum import Enum
from datetime import datetime, timezone 
class Tipo2FA(str, Enum):
    NONE = 'none'
    TOTP = 'totp'
    EMAIL = 'email'
    SMS = 'sms'

engine = create_engine('postgresql+psycopg2://postgres:123@localhost:5432/Usuarios_DB')

base = declarative_base()

mensagem_al = Table(
    'mensag_al',
    base.metadata,
    Column('id_aluno', Integer, ForeignKey('alunos.id_aluno'), primary_key=True),
    Column('id_mensagem', Integer, ForeignKey('mensagens.id_mensagem'), primary_key=True)
)
class professores(base):
    __tablename__='professores'
    id_prof =Column(Integer, primary_key=True)
    email_prof = Column (String, unique= True , index=True, nullable=False)
    num_prof = Column (String, unique= True , index=True, nullable=False)
    nome_prof = Column(String)
    senha_prof = Column(String)
class turmas(base):
    __tablename__ = 'turmas'
    id_turma = Column(Integer, primary_key=True)
    id_prof = Column(Integer, ForeignKey(professores.id_prof))
    nome_turma = Column(String)
    
class alunos(base):
    __tablename__='alunos'
    id_aluno = Column(Integer, primary_key=True)
    id_prof = Column(Integer,ForeignKey(professores.id_prof))
    id_turma = Column( Integer, ForeignKey(turmas.id_turma))
    nome_aluno = Column(String)
    neurodiv_aluno = Column(String)
    desc_aluno = Column(String)
    idade_aluno= Column(Integer)
    mensagens_rel = relationship('mensagens', secondary=mensagem_al, back_populates='alunos_rel')

class mensagens(base):
    __tablename__='mensagens'
    id_mensagem = Column(Integer,primary_key=True)
    id_prof = Column(Integer,ForeignKey(professores.id_prof))
    data_mensagem = Column(Date)
    anexo_mensagem = Column(Integer)
    alunos_rel = relationship('alunos', secondary=mensagem_al, back_populates='mensagens_rel')

class user2famethods(base):
    __tablename__ = 'user_2fa_methods'
    id_methods = Column(Integer, primary_key=True)
    tipo = Column(sqlenum(Tipo2FA), nullable= False)
    secret = Column(String, nullable=True)
    usa_verificacao = Column(Boolean)
    data_criacao = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    id_prof = Column(Integer, ForeignKey(professores.id_prof))


def pegar_bd():
    sessao = Session(engine)
    try:
        yield sessao
    finally:
        sessao.close
