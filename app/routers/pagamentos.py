from __future__ import annotations

from typing import Optional

from database import Session, Usuario, pegar_bd
from dependencies import pegar_professor_logado
from fastapi import APIRouter, Depends, Header, Query, Request, status
from schemas.schemas import CheckoutPlanoRequest, SincronizarPagamentoRequest
import services.pagamentos as fn_pagamentos

Pagamentos_router = APIRouter(prefix="/pagamentos", tags=["pagamentos-mercadopago"])


@Pagamentos_router.post("/checkout", status_code=status.HTTP_201_CREATED)
def criar_checkout_plano(
    dados: CheckoutPlanoRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    """Inicia checkout no Mercado Pago para os planos pro, pro_plus (pro+) ou institucional."""
    return fn_pagamentos.iniciar_checkout_plano(sessao, usuario_logado, dados)


@Pagamentos_router.post("/webhook/mercadopago", status_code=status.HTTP_200_OK)
async def webhook_mercadopago(
    request: Request,
    sessao: Session = Depends(pegar_bd),
    x_signature: Optional[str] = Header(default=None, alias="x-signature"),
    x_request_id: Optional[str] = Header(default=None, alias="x-request-id"),
    topic: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None, alias="type"),
    query_id: Optional[str] = Query(default=None, alias="id"),
    data_id_query: Optional[str] = Query(default=None, alias="data.id"),
):
    """Recebe notificações do Mercado Pago, valida assinatura e libera permissões do plano pago."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    tipo_evento = body.get("type") or body.get("topic") or event_type or topic or ""
    data_obj = body.get("data") if isinstance(body.get("data"), dict) else {}
    payment_id = str(
        data_obj.get("id")
        or body.get("id")
        or data_id_query
        or query_id
        or ""
    ).strip()

    fn_pagamentos.validar_assinatura_webhook_mp(
        x_signature=x_signature,
        x_request_id=x_request_id,
        data_id=payment_id or None,
    )

    if tipo_evento and tipo_evento != "payment":
        return {"ignorado": True, "motivo": f"Evento '{tipo_evento}' não requer processamento."}

    if not payment_id:
        return {"ignorado": True, "motivo": "Identificador do pagamento ausente na notificação."}

    return fn_pagamentos.processar_notificacao_mercadopago(sessao, payment_id)


@Pagamentos_router.get("/meus")
def listar_meus_pagamentos(
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    """Lista os pagamentos e contratos do usuário autenticado."""
    return fn_pagamentos.listar_pagamentos_usuario(sessao, usuario_logado)


@Pagamentos_router.get("/{id_pgto}")
def consultar_pagamento(
    id_pgto: int,
    payment_id: Optional[str] = Query(default=None),
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    """Consulta o status do pagamento e retorna novo JWT com permissões atualizadas quando pago."""
    return fn_pagamentos.consultar_e_sincronizar_pagamento(
        sessao, usuario_logado, id_pgto, mp_payment_id=payment_id
    )


@Pagamentos_router.post("/{id_pgto}/sincronizar")
def sincronizar_pagamento(
    id_pgto: int,
    dados: SincronizarPagamentoRequest,
    sessao: Session = Depends(pegar_bd),
    usuario_logado: Usuario = Depends(pegar_professor_logado),
):
    """Sincroniza manualmente um pagamento com o Mercado Pago a partir do mp_payment_id."""
    return fn_pagamentos.consultar_e_sincronizar_pagamento(
        sessao, usuario_logado, id_pgto, mp_payment_id=dados.mp_payment_id
    )
