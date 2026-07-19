from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

app=FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from routers.ai import AI_router
from routers.auth import Auth_router
from routers.students import Student_router

app.include_router(AI_router)
app.include_router(Auth_router)
app.include_router(Student_router)

#utilize no terminal: pip install fastapi uvicorn python-dotenv
#para rodar o codigo, utilize no terminal: python -m uvicorn main:app --reload
#para ver o site que mostra todas as rotas, use o link gerado pelo uvicorn juntamente com um /docs
#estou pesquisando sobre a implementação do SQLAlchemy, ele vai orquestrar uma tradução de linguagem Python para linguagem SQL