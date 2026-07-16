from fastapi import FastAPI

app=FastAPI()

from AI_routes import AI_router
from Auth_routes import Auth_router
from Students_routes import Student_router

app.include_router(AI_router)
app.include_router(Auth_router)
app.include_router(Student_router)

#utilize no terminal: pip install fastapi uvicorn python-dotenv
#para rodar o codigo, utilize no terminal: python -m uvicorn main:app --reload
#para ver o site que mostra todas as rotas, use o link gerado pelo uvicorn juntamente com um /docs
#estou pesquisando sobre a implementação do SQLAlchemy, ele vai orquestrar uma tradução de linguagem Python para linguagem SQL