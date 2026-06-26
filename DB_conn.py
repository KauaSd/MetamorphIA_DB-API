from sqlalchemy import create_engine, select, Column, Integer, String, ForeignKey, Date, Table
from sqlalchemy.orm import declarative_base, relationship, Session
from sqlalchemy.exc import IntegrityError, OperationalError
engine = create_engine('postgresql+psycopg2://postgres:123@localhost:5432/Usuarios_DB')

base = declarative_base()
mensagem_al = Table(
    'mensag_al',
    base.metadata,
    Column('id_aluno', Integer, ForeignKey('alunos.id_aluno'), primary_key=True),
    Column('id_mensagem', Integer, ForeignKey('mensagens.id_mensagem'), primary_key=True)
)
class alunos(base):
    __tablename__='alunos'
    id_aluno = Column(Integer, primary_key=True)
    nome_aluno = Column(String)
    neurodiv_aluno = Column(String)
    mensagens_rel = relationship("mensagens", secondary=mensagem_al, back_populates="alunos_rel")
class professores(base):
    __tablename__='professores'
    id_prof =Column(Integer, primary_key=True)
    nome_prof = Column(String)
    senha_prof = Column(String)
class mensagens(base):
    __tablename__='mensagens'
    id_mensagem = Column(Integer,primary_key=True)
    id_prof = Column(Integer,ForeignKey(professores.id_prof))
    data_mensagem = Column(Date)
    anexo_mensagem = Column(Integer)
    alunos_rel = relationship("alunos", secondary=mensagem_al, back_populates="mensagens_rel")


if __name__=='__main__':
    with engine.connect() as conn:
        stmt=select(alunos).where(alunos.neurodiv_aluno=='TDAH')
        result = conn.execute(stmt)
        print(result.all())
