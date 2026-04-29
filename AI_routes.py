from fastapi import APIRouter

AI_router = APIRouter(prefix="/AI", tags= ["AI"])

@AI_router.get("/")
async def exemplo():
    """
    Rota de exemplo. 
    É possivel ver a estrutura base, usamos @auth_router.get("/") para criar a rota, dentro do parenteses você pode 
    trocar o nome, e então ele vai criar uma nova rota para aquela palavra colocada lá. Por exemplo, se colocado 
    @auth_router.get("/exemplo"), se colocarmos apenas /autenticar no fim do link, não vai funcionar, será preciso
    colocar /autenticar/exemplo.
    """
    return {"mensagem":"para acessar essa rota, use o link gerado pelo uvicorn e coloque /AI no fim"}