"""MODstore 订单事件 webhook：接收 payment.paid 并桥接进 FHD。

端点：POST /api/xcmax/webhooks/modstore/payment
投递头（见 PAYMENT_CONTRACT §4）：
  X-Modstore-Webhook-Id / Event / Timestamp / Signature: sha256=<hmac>
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from app.application.order_event_app_service import ingest_paid_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax/webhooks", tags=["order-bridge"])


@router.post("/modstore/payment")
async def modstore_payment_webhook(
    request: Request,
    body: dict[str, Any] = Body(...),
    x_modstore_webhook_signature: str | None = Header(
        default=None, alias="X-Modstore-Webhook-Signature"
    ),
):
    raw = await request.body()
    result = ingest_paid_event(
        body,
        hmac_signature=x_modstore_webhook_signature,
        raw=raw,
    )
    if not result.get("accepted"):
        return JSONResponse({"success": False, "reason": result.get("reason")}, status_code=400)
    return JSONResponse({"success": True, "data": result})
