from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
from typing import Any, Optional

from config.settings import settings
from database import (
    Contrato,
    Nota_fiscal,
    Pgto,
    Plano,
    Session,
    User_cont,
    Usuario,
    garantir_planos_iniciais,
    select,
)
from fastapi import HTTPException, status
import httpx
from schemas.schemas import CheckoutPlanoRequest
import security
from services.planos import (
    PLANOS_PAGOS_PRECOS,
    ativar_contrato_e_permissoes,
    invalidar_cache_permissoes,
    normalizar_nome_plano,
    validar_documento_contrato,
)
from services.users import (
    obter_claims_jwt_usuario,
    provisionar_estrutura_inicial_usuario,
)

MP_API_BASE = "https://api.mercadopago.com"


def _exigir_mp_access_token() -> str:
    token = (settings.MP_ACCESS_TOKEN or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Integração com Mercado Pago não configurada (MP_ACCESS_TOKEN ausente).",
        )
    return token


def _headers_mp(idempotency_key: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_exigir_mp_access_token()}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


def validar_assinatura_webhook_mp(
    x_signature: str | None,
    x_request_id: str | None,
    data_id: str | None,
) -> None:
    """Valida assinatura HMAC-SHA256 do webhook do Mercado Pago quando MP_WEBHOOK_SECRET estiver configurado."""
    secret = (settings.MP_WEBHOOK_SECRET or "").strip()
    if not secret:
        return

    if not x_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabeçalho x-signature ausente no webhook.",
        )

    partes: dict[str, str] = {}
    for item in x_signature.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            partes[k.strip().lower()] = v.strip()

    ts = partes.get("ts")
    v1 = partes.get("v1")
    if not ts or not v1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato inválido de x-signature.",
        )

    manifest_parts = []
    if data_id:
        manifest_parts.append(f"id:{data_id};")
    if x_request_id:
        manifest_parts.append(f"request-id:{x_request_id};")
    manifest_parts.append(f"ts:{ts};")
    manifest = "".join(manifest_parts)

    assinatura_esperada = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(assinatura_esperada, v1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Assinatura do webhook do Mercado Pago inválida.",
        )


def iniciar_checkout_plano(
    sessao: Session,
    usuario: Usuario,
    dados: CheckoutPlanoRequest,
) -> dict[str, Any]:
    """Cria contrato pendente, registra pagamento e gera preferência Checkout Pro no Mercado Pago."""
    if usuario.tipo_usuario in ("adm_institucional", "prof_institucional"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuários institucionais (adm ou professor) não podem contratar outra assinatura.",
        )

    planos = garantir_planos_iniciais(sessao)
    nome_plano = normalizar_nome_plano(dados.nome_plano)
    if nome_plano not in PLANOS_PAGOS_PRECOS or nome_plano not in planos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plano inválido para pagamento. Escolha entre: pro, institucional, institucional_plus (institucional+).",
        )

    tipo_cont, doc_limpo = validar_documento_contrato(dados.tipo_cont, dados.documento_cont)
    if nome_plano == "institucional_plus" and not dados.email_institucional:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O e-mail institucional é obrigatório para o plano Institucional+.",
        )

    preco_minimo = PLANOS_PAGOS_PRECOS[nome_plano]
    valor_final = preco_minimo
    if dados.valor_contrato is not None:
        if dados.valor_contrato < preco_minimo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Valor informado ({dados.valor_contrato}) é inferior ao preço do plano ({preco_minimo}).",
            )
        valor_final = float(dados.valor_contrato)

    _exigir_mp_access_token()
    usuario.cpf_cnpj = doc_limpo
    plano_obj = planos[nome_plano]
    provisionar_estrutura_inicial_usuario(sessao, usuario)

    if nome_plano == "pro":
        contrato = Contrato(
            tipo_cont=tipo_cont,
            documento_cont=doc_limpo,
            max_qtd_user=1,
            max_qtd_escolas=dados.max_qtd_escolas or plano_obj.max_escolas,
            max_qtd_turmas=plano_obj.max_turmas_por_escola,
            max_qtd_alunos=plano_obj.max_alunos_por_turma,
            valor_contrato=valor_final,
            fk_Plano_id_plano=plano_obj.id_plano,
            status_contrato="pendente",
        )
    elif nome_plano == "institucional":
        contrato = Contrato(
            tipo_cont=tipo_cont,
            documento_cont=doc_limpo,
            email_institucional=dados.email_institucional,
            max_qtd_user=dados.max_qtd_user or 5,
            max_qtd_escolas=1,
            max_qtd_turmas=dados.max_qtd_turmas or 10,
            max_qtd_alunos=dados.max_qtd_alunos or 30,
            valor_contrato=valor_final,
            fk_Plano_id_plano=plano_obj.id_plano,
            status_contrato="pendente",
        )
    else:  # institucional_plus
        contrato = Contrato(
            tipo_cont=tipo_cont,
            documento_cont=doc_limpo,
            email_institucional=dados.email_institucional,
            max_qtd_user=dados.max_qtd_user or 50,
            max_qtd_escolas=dados.max_qtd_escolas or 20,
            max_qtd_turmas=dados.max_qtd_turmas or 20,
            max_qtd_alunos=dados.max_qtd_alunos or 40,
            valor_contrato=valor_final,
            fk_Plano_id_plano=plano_obj.id_plano,
            status_contrato="pendente",
        )

    sessao.add(contrato)
    sessao.flush()

    sessao.add(
        User_cont(
            fk_Usuario_id_usuario=usuario.id_usuario,
            fk_Contrato_id_cont=contrato.id_cont,
            eh_pagador=True,
        )
    )

    dados_ativacao = {
        "email_institucional": dados.email_institucional,
        "nome_escola": dados.nome_escola,
        "id_escola": dados.id_escola,
        "nome_grupo": dados.nome_grupo,
        "escolas_ids": dados.escolas_ids,
        "adm_pode_chat": dados.adm_pode_chat,
    }
    pgto = Pgto(
        data_vencimento=date.today() + timedelta(days=3),
        status_pagamento="Pendente",
        fk_Contrato_id_cont=contrato.id_cont,
        valor_pagamento=valor_final,
        dados_ativacao_json=json.dumps(dados_ativacao),
    )
    sessao.add(pgto)
    sessao.flush()

    external_reference = (
        f"metamorphia:pgto:{pgto.id_pgto}:contrato:{contrato.id_cont}:user:{usuario.id_usuario}"
    )
    pgto.mp_external_reference = external_reference

    preferencia_payload: dict[str, Any] = {
        "items": [
            {
                "id": nome_plano,
                "title": f"Plano MetamorphIA {nome_plano.upper()}",
                "description": f"Assinatura mensal do plano {nome_plano}",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": round(float(valor_final), 2),
            }
        ],
        "external_reference": external_reference,
        "metadata": {
            "id_pgto": pgto.id_pgto,
            "id_contrato": contrato.id_cont,
            "id_usuario": usuario.id_usuario,
            "nome_plano": nome_plano,
        },
    }
    if usuario.email_usuario:
        preferencia_payload["payer"] = {
            "name": usuario.nome_usuario,
            "email": usuario.email_usuario,
        }

    notif_url = (dados.notification_url or settings.MP_NOTIFICATION_URL or "").strip()
    if notif_url:
        preferencia_payload["notification_url"] = notif_url

    success_url = (dados.success_url or settings.MP_SUCCESS_URL or "").strip()
    failure_url = (dados.failure_url or settings.MP_FAILURE_URL or "").strip()
    pending_url = (dados.pending_url or settings.MP_PENDING_URL or "").strip()
    if success_url:
        preferencia_payload["back_urls"] = {
            "success": success_url,
            "failure": failure_url or success_url,
            "pending": pending_url or success_url,
        }
        preferencia_payload["auto_return"] = "approved"

    try:
        resp = httpx.post(
            f"{MP_API_BASE}/checkout/preferences",
            headers=_headers_mp(idempotency_key=f"checkout-pgto-{pgto.id_pgto}"),
            json=preferencia_payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        mp_data = resp.json()
    except httpx.HTTPError as exc:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro ao criar preferência de pagamento no Mercado Pago: {exc}",
        ) from exc

    pgto.mp_preference_id = mp_data.get("id")
    sessao.commit()

    return {
        "mensagem": f"Checkout criado para o plano '{nome_plano}'. Conclua o pagamento no Mercado Pago para liberar as permissões.",
        "id_pgto": pgto.id_pgto,
        "id_contrato": contrato.id_cont,
        "plano": nome_plano,
        "valor": float(valor_final),
        "status": "pendente",
        "preference_id": pgto.mp_preference_id,
        "init_point": mp_data.get("init_point"),
        "sandbox_init_point": mp_data.get("sandbox_init_point"),
        "external_reference": external_reference,
    }


def _buscar_pagamento_local(
    sessao: Session,
    mp_payment_id: str,
    external_reference: str | None,
    metadata: dict[str, Any] | None,
) -> Optional[Pgto]:
    pgto = sessao.execute(
        select(Pgto).where(Pgto.mp_payment_id == mp_payment_id)
    ).scalars().first()
    if pgto:
        return pgto

    if external_reference:
        pgto = sessao.execute(
            select(Pgto).where(Pgto.mp_external_reference == external_reference)
        ).scalars().first()
        if pgto:
            return pgto

    if metadata and metadata.get("id_pgto") is not None:
        return sessao.get(Pgto, int(metadata["id_pgto"]))

    return None


def _rebaixar_tipo_usuario_se_sem_plano_superior(sessao: Session, usuario: Usuario) -> None:
    """Reverte tipo_usuario para 'normal' caso não exista mais contrato ativo de institucional/institucional_plus."""
    planos_map = {p.id_plano: p.nome_plano for p in garantir_planos_iniciais(sessao).values()}
    contratos_ativos = sessao.execute(
        select(Contrato)
        .join(User_cont, User_cont.fk_Contrato_id_cont == Contrato.id_cont)
        .where(
            User_cont.fk_Usuario_id_usuario == usuario.id_usuario,
            Contrato.status_contrato == "ativo",
        )
    ).scalars().all()
    nomes_ativos = {planos_map.get(c.fk_Plano_id_plano) for c in contratos_ativos}

    if "institucional_plus" in nomes_ativos:
        usuario.tipo_usuario = "adm_institucional"
    elif "institucional" in nomes_ativos:
        usuario.tipo_usuario = "adm_escola"
    else:
        usuario.tipo_usuario = "normal"


def processar_notificacao_mercadopago(
    sessao: Session,
    payment_id: str,
) -> dict[str, Any]:
    """Consulta o pagamento no Mercado Pago e atualiza contrato/permissões de forma idempotente."""
    payment_id_str = str(payment_id).strip()
    if not payment_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payment_id inválido.",
        )

    try:
        resp = httpx.get(
            f"{MP_API_BASE}/v1/payments/{payment_id_str}",
            headers=_headers_mp(),
            timeout=15.0,
        )
        resp.raise_for_status()
        mp_payment = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Pagamento não encontrado no Mercado Pago.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro ao consultar pagamento no Mercado Pago: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha de comunicação com Mercado Pago: {exc}",
        ) from exc

    mp_status = (mp_payment.get("status") or "").strip().lower()
    external_ref = mp_payment.get("external_reference")
    metadata = mp_payment.get("metadata") or {}
    valor_pago = mp_payment.get("transaction_amount")
    metodo = mp_payment.get("payment_method_id")

    pgto = _buscar_pagamento_local(sessao, payment_id_str, external_ref, metadata)
    if not pgto:
        return {
            "processado": False,
            "motivo": "Pagamento não corresponde a nenhum registro local.",
            "mp_payment_id": payment_id_str,
        }

    contrato = sessao.get(Contrato, pgto.fk_Contrato_id_cont)
    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato vinculado ao pagamento não encontrado.")

    plano = sessao.get(Plano, contrato.fk_Plano_id_plano)
    nome_plano = plano.nome_plano if plano else "normal"

    user_cont = sessao.execute(
        select(User_cont).where(
            User_cont.fk_Contrato_id_cont == contrato.id_cont,
            User_cont.eh_pagador.is_(True),
        )
    ).scalars().first()
    if not user_cont:
        raise HTTPException(status_code=404, detail="Pagador do contrato não encontrado.")

    usuario = sessao.get(Usuario, user_cont.fk_Usuario_id_usuario)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário pagador não encontrado.")

    pgto.mp_payment_id = payment_id_str
    pgto.mp_status = mp_status
    if metodo:
        pgto.metodo_pagamento = str(metodo)

    if mp_status == "approved":
        valor_esperado = float(pgto.valor_pagamento or contrato.valor_contrato or 0)
        if valor_pago is not None and float(valor_pago) + 0.01 < valor_esperado:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valor pago no Mercado Pago é inferior ao valor do contrato.",
            )

        ja_aprovado = pgto.status_pagamento == "Pago" and contrato.status_contrato == "ativo"
        if not ja_aprovado:
            pgto.status_pagamento = "Pago"
            pgto.data_pagamento = datetime.now(timezone.utc)

            dados_ativacao = (
                json.loads(pgto.dados_ativacao_json)
                if pgto.dados_ativacao_json
                else {}
            )
            ativar_contrato_e_permissoes(
                sessao=sessao,
                usuario=usuario,
                contrato=contrato,
                nome_plano=nome_plano,
                dados_ativacao=dados_ativacao,
            )

            nota_existente = sessao.execute(
                select(Nota_fiscal).where(Nota_fiscal.fk_Contrato_id_cont == contrato.id_cont)
            ).scalars().first()
            if not nota_existente:
                sessao.add(
                    Nota_fiscal(
                        valor_nota=pgto.valor_pagamento or contrato.valor_contrato or 0,
                        data_emissao=date.today(),
                        fk_Contrato_id_cont=contrato.id_cont,
                    )
                )

            sessao.commit()
            invalidar_cache_permissoes()
        else:
            sessao.commit()

        return {
            "processado": True,
            "id_pgto": pgto.id_pgto,
            "id_contrato": contrato.id_cont,
            "plano": nome_plano,
            "status_pagamento": pgto.status_pagamento,
            "status_contrato": contrato.status_contrato,
            "permissoes_liberadas": True,
        }

    if mp_status in ("rejected", "cancelled"):
        pgto.status_pagamento = "Recusado" if mp_status == "rejected" else "Cancelado"
        if contrato.status_contrato == "pendente":
            contrato.status_contrato = "cancelado"
        sessao.commit()
    elif mp_status in ("refunded", "charged_back"):
        pgto.status_pagamento = "Estornado"
        contrato.status_contrato = "cancelado"
        sessao.flush()
        _rebaixar_tipo_usuario_se_sem_plano_superior(sessao, usuario)
        sessao.commit()
        invalidar_cache_permissoes()
    else:
        sessao.commit()

    return {
        "processado": True,
        "id_pgto": pgto.id_pgto,
        "id_contrato": contrato.id_cont,
        "plano": nome_plano,
        "status_pagamento": pgto.status_pagamento,
        "status_contrato": contrato.status_contrato,
        "permissoes_liberadas": contrato.status_contrato == "ativo",
    }


def consultar_e_sincronizar_pagamento(
    sessao: Session,
    usuario: Usuario,
    id_pgto: int,
    mp_payment_id: str | None = None,
) -> dict[str, Any]:
    """Consulta o status do pagamento do usuário, sincroniza com o MP se necessário e emite novo JWT se pago."""
    pgto = sessao.get(Pgto, id_pgto)
    if not pgto:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado.")

    vinculo = sessao.execute(
        select(User_cont).where(
            User_cont.fk_Contrato_id_cont == pgto.fk_Contrato_id_cont,
            User_cont.fk_Usuario_id_usuario == usuario.id_usuario,
        )
    ).scalars().first()
    if not vinculo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar este pagamento.",
        )

    id_mp = mp_payment_id or pgto.mp_payment_id
    if id_mp and pgto.status_pagamento == "Pendente":
        processar_notificacao_mercadopago(sessao, id_mp)
        sessao.refresh(pgto)
        sessao.refresh(usuario)

    contrato = sessao.get(Contrato, pgto.fk_Contrato_id_cont)
    plano = sessao.get(Plano, contrato.fk_Plano_id_plano) if contrato else None
    nome_plano = plano.nome_plano if plano else "normal"

    resposta: dict[str, Any] = {
        "id_pgto": pgto.id_pgto,
        "id_contrato": pgto.fk_Contrato_id_cont,
        "plano": nome_plano,
        "valor": float(pgto.valor_pagamento) if pgto.valor_pagamento is not None else None,
        "status_pagamento": pgto.status_pagamento,
        "status_contrato": contrato.status_contrato if contrato else None,
        "mp_preference_id": pgto.mp_preference_id,
        "mp_payment_id": pgto.mp_payment_id,
        "mp_status": pgto.mp_status,
        "permissoes_liberadas": bool(contrato and contrato.status_contrato == "ativo"),
    }

    if pgto.status_pagamento == "Pago" and contrato and contrato.status_contrato == "ativo":
        claims = obter_claims_jwt_usuario(sessao, usuario)
        resposta["access_token"] = security.criar_access_token(
            data=claims,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        resposta["token_type"] = "bearer"

    return resposta


def listar_pagamentos_usuario(sessao: Session, usuario: Usuario) -> list[dict[str, Any]]:
    """Lista todos os pagamentos vinculados aos contratos do usuário."""
    planos_map = {p.id_plano: p.nome_plano for p in garantir_planos_iniciais(sessao).values()}
    rows = sessao.execute(
        select(Pgto, Contrato)
        .join(Contrato, Contrato.id_cont == Pgto.fk_Contrato_id_cont)
        .join(User_cont, User_cont.fk_Contrato_id_cont == Contrato.id_cont)
        .where(User_cont.fk_Usuario_id_usuario == usuario.id_usuario)
        .order_by(Pgto.id_pgto.desc())
    ).all()

    return [
        {
            "id_pgto": pgto.id_pgto,
            "id_contrato": contrato.id_cont,
            "plano": planos_map.get(contrato.fk_Plano_id_plano, "normal"),
            "valor": float(pgto.valor_pagamento) if pgto.valor_pagamento is not None else None,
            "status_pagamento": pgto.status_pagamento,
            "status_contrato": contrato.status_contrato,
            "mp_payment_id": pgto.mp_payment_id,
            "mp_status": pgto.mp_status,
            "data_vencimento": pgto.data_vencimento.isoformat() if pgto.data_vencimento else None,
        }
        for pgto, contrato in rows
    ]
