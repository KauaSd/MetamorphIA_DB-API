from pathlib import Path
import sys

_APP_DIR = str(Path(__file__).resolve().parent)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from routers.ai import AI_router
from routers.auth import Auth_router
from routers.planos import Planos_router
from routers.students import Student_router
from routers.turmas import Turma_router

app.include_router(AI_router)
app.include_router(Auth_router)
app.include_router(Planos_router)
app.include_router(Student_router)
app.include_router(Turma_router)
