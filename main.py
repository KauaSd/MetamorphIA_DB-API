from fastapi import FastAPI

app=FastAPI()

<<<<<<< HEAD:main.py
from AI_routes import AI_router
from Auth_routes import Auth_router

app.include_router(AI_router)
app.include_router(Auth_router)
=======
from routers.ai import AI_router
from routers.auth import Auth_router
from routers.students import Student_router
from routers.turmas import Turma_router

app.include_router(AI_router)
app.include_router(Auth_router)
app.include_router(Student_router)
app.include_router(Turma_router)
>>>>>>> 649741c (rotas da turma e aluno):app/main.py

#utilize no terminal: pip install fastapi uvicorn python-dotenv
#para rodar o codigo, utilize no terminal: python -m uvicorn main:app --reload
#para ver o site que mostra todas as rotas, use o link gerado pelo uvicorn juntamente com um /docs
#estou pesquisando sobre a implementação do SQLAlchemy, ele vai orquestrar uma tradução de linguagem Python para linguagem SQL