"""Administrative business webhook operations."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server import payment_orders, webhook_dispatcher
from modstore_server.api.deps import _get_current_user
from modstore_server.application.payment_gateway import java_payment_unreachable_message
from modstore_server.eventing.contracts import (
    PAYMENT_PAID,
    REFUND_APPROVED,
    REFUND_FAILED,
    REFUND_REJECTED,
)
from modstore_server.infrastructure.db import get_db
from modstore_server.models import RefundRequest, User

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookReplayBody(BaseModel):
    event_id: str = Field(default="", max_length=200)
    order_no: str = Field(default="", max_length=64)
    event_type: str = Field(default="", max_length=64)


def _payment_payload(order: dict) -> dict:
    return {
        "out_trade_no": order.get("out_trade_no"),
        "trade_no": order.get("trade_no"),
        "buyer_id": order.get("buyer_id"),
        "user_id": order.get("user_id"),
        "subject": order.get("subject"),
        "total_amount": order.get("total_amount"),
        "order_kind": order.get("order_kind"),
        "item_id": order.get("item_id"),
        "plan_id": order.get("plan_id"),
        "paid_at": order.get("paid_at"),
    }


def _refund_payload(refund: RefundRequest) -> dict:
    return {
        "refund_id": refund.id,
        "user_id": refund.user_id,
        "order_no": refund.order_no,
        "amount": refund.amount,
        "reason": refund.reason,
        "status": refund.status,
        "admin_note": refund.admin_note or "",
        "created_at": refund.created_at.isoformat() if refund.created_at else "",
        "updated_at": refund.updated_at.isoformat() if refund.updated_at else "",
    }


@router.post("/admin/replay")
async def admin_replay_webhook(
    body: WebhookReplayBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
    authorization: str | None = Header(None),
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    event_id = (body.event_id or "").strip()
    if event_id:
        result = webhook_dispatcher.replay_event(event_id)
        if not result.get("ok") and result.get("message") == "webhook event not found":
            raise HTTPException(404, "Webhook 事件不存在")
        return {"ok": bool(result.get("ok")), "result": result}

    order_no = (body.order_no or "").strip()
    if not order_no:
        raise HTTPException(400, "请提供 event_id 或 order_no")

    requested_type = (body.event_type or "").strip()
    if (
        os.environ.get("PAYMENT_BACKEND") or "python"
    ).strip().lower() == "java" and not requested_type.startswith("refund."):
        target = (
            (os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080")
            .strip()
            .rstrip("/")
        )
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    f"{target}/api/webhooks/admin/replay",
                    json=body.model_dump(),
                    headers={"Authorization": authorization or ""},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(502, java_payment_unreachable_message(exc)) from exc
        try:
            data = response.json()
        except ValueError:
            data = {"ok": False, "message": response.text}
        if response.status_code >= 400:
            raise HTTPException(response.status_code, data.get("message") or data)
        return data

    if requested_type.startswith("refund."):
        refund = (
            db.query(RefundRequest)
            .filter(RefundRequest.order_no == order_no)
            .order_by(RefundRequest.id.desc())
            .first()
        )
        if not refund:
            raise HTTPException(404, "退款申请不存在")
        event_type = requested_type or {
            "refunded": REFUND_APPROVED,
            "rejected": REFUND_REJECTED,
            "refund_failed": REFUND_FAILED,
        }.get(refund.status, "")
        if not event_type:
            raise HTTPException(400, f"退款状态 {refund.status} 不支持重放")
        result = webhook_dispatcher.publish_event(event_type, order_no, _refund_payload(refund))
        return {"ok": bool(result.get("ok")), "result": result}

    order = payment_orders.find(order_no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if (order.get("status") or "").strip().lower() != "paid":
        raise HTTPException(400, f"只有已支付订单可重放 {PAYMENT_PAID}")
    result = webhook_dispatcher.publish_event(PAYMENT_PAID, order_no, _payment_payload(order))
    return {"ok": bool(result.get("ok")), "result": result}
