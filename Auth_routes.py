from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from DB_conn import engine, alunos, professores, mensagens, mensagem_al, select
Auth_router = APIRouter(prefix="/autenticar", tags= ["autenticar"])

@Auth_router.get("/exemplo")
async def exemplo():
    """
    Rota de exemplo. 
    É possivel ver a estrutura base, usamos @auth_router.get("/") para criar a rota, dentro do parenteses você pode 
    trocar o nome, e então ele vai criar uma nova rota para aquela palavra colocada lá. Por exemplo, se colocado 
    @auth_router.get("/exemplo"), se colocarmos apenas /autenticar no fim do link, não vai funcionar, será preciso
    colocar /autenticar/exemplo.
    """
    with engine.connect() as conn:
        stmt = select(alunos)
        result = conn.execute(stmt).all()
        query=[row._asdict() for row in result]
    return jsonable_encoder(query)

@Auth_router.get("/cavalo")
async def exemplo():
    """
    Rota de exemplo. 
    É possivel ver a estrutura base, usamos @auth_router.get("/") para criar a rota, dentro do parenteses você pode 
    trocar o nome, e então ele vai criar uma nova rota para aquela palavra colocada lá. Por exemplo, se colocado 
    @auth_router.get("/exemplo"), se colocarmos apenas /autenticar no fim do link, não vai funcionar, será preciso
    colocar /autenticar/exemplo.
    """
    return {"mensagem":"para acessar essa rota, use o link gerado pelo uvicorn e coloque /autenticar no fim"}