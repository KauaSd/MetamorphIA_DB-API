from pathlib import Path
import sys

_APP_DIR = str(Path(__file__).resolve().parent)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from config.settings import settings
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from security import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

_eh_producao = settings.ENVIRONMENT == "production"

app = FastAPI(
    docs_url=None if _eh_producao else "/docs",
    redoc_url=None if _eh_producao else "/redoc",
    openapi_url=None if _eh_producao else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def adicionar_headers_seguranca(request: Request, call_next) -> Response:
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response

from routers.admin import Admin_router
from routers.ai import AI_router
from routers.auth import Auth_router
from routers.pagamentos import Pagamentos_router
from routers.planos import Planos_router
from routers.students import Student_router
from routers.turmas import Turma_router

app.include_router(Admin_router)
app.include_router(AI_router)
app.include_router(Auth_router)
app.include_router(Pagamentos_router)
app.include_router(Planos_router)
app.include_router(Student_router)
app.include_router(Turma_router)


@app.get("/health", tags=["health"])
def health() -> Response:
    """Endpoint leve de liveness sem roundtrip ao banco."""
    import json

    return Response(
        content=json.dumps({"status": "ok", "service": "api-db"}),
        media_type="application/json",
        status_code=200,
    )


@app.get("/health/deep", tags=["health"])
def health_deep() -> Response:
    """Endpoint de verificação profunda com teste real de conectividade ao banco."""
    import json
    from database import engine
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return Response(
            content=json.dumps({"status": "ok", "service": "api-db", "database": "ok"}),
            media_type="application/json",
            status_code=200,
        )
    except Exception:
        return Response(
            content=json.dumps({"status": "degraded", "service": "api-db", "database": "unreachable"}),
            media_type="application/json",
            status_code=503,
        )
