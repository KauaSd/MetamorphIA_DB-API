import os
import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

AI_router = APIRouter(prefix="/AI", tags= ["AI"])
URL = os.getenv("URL", "")
class TextoIA(BaseModel):
    txt:str

@AI_router.get("/enviatxtuser/{txt}")
async def enviatxtuser(txt:str):
    try:
        return {"mensagem": txt}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Erro ao processar o texto."
        )

@AI_router.post("/txtIA")
async def txtIA(IAtxt : TextoIA):
    async with httpx.asyncClient() as client:
        try:
            external_response= await client.post(
                URL,
                json={"prompt": IAtxt.txt},
                timeout=30.0
            )
            external_response.raise_for_status()
            data = external_response.json()
            return {
            "status": "sucesso", 
            "dados": data
            }
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                    status_code=exc.response.status_code,
                    detail=f"Erro na API da IA: {exc.response.text}"
                )
        except (httpx.RequestError, httpx.TimeoutException):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possivel se comunicar co a outra API"
            )