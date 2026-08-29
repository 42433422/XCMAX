# mypy: disable-error-code="arg-type, assignment, index, union-attr"
"""Customer-owned checkout and authoritative payment reconciliation for custom delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_api import _visible_ticket_or_404
from modstore_server.customer_service_delivery_api import _start_custom_delivery_run
from modstore_server.customer_service_delivery_completion import complete_delivery_if_ready
from modstore_server.customer_service_delivery_models import (
    CustomDeliveryPaymentCheckoutBody,
    custom_delivery_commerce_blockers,
    custom_delivery_crm,
    custom_delivery_evidence,
    custom_delivery_pricing_mode,
)
from modstore_server.customer_service_orchestrator import audit
from modstore_server.customer_service_tools import json_dumps
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.payment_cs_internal import (
    create_custom_delivery_payment_order,
    find_matching_paid_order,
)

router = APIRouter()
_get_current_user = get_current_user
_custom_delivery_evidence = custom_delivery_evidence

async def reconcile_custom_delivery_payment(
    db: Session, ticket: CustomerServiceTicket
) -> bool:
    """Turn a paid dedicated order into commerce proof and start production."""
    evidence = _custom_delivery_evidence(ticket)
    if custom_delivery_pricing_mode(evidence) != "post_delivery_addon":
        return False
    crm = custom_delivery_crm(evidence)
    payment = crm["payment"]
    if str(payment.get("status") or "") == "paid":
        return False
    order_nos = [str(payment.get("reference") or "").strip()]
    order_nos.extend(
        str(row.get("order_no") or "").strip()
        for row in reversed(evidence.get("payment_attempts") or [])
        if isinstance(row, dict)
    )
    order_nos = list(dict.fromkeys(value for value in order_nos if value))
    if not order_nos:
        return False
    order = None
    order_no = ""
    for candidate in order_nos:
        matched = find_matching_paid_order(
            int(ticket.user_id), expected_out_trade_no=candidate
        )
        if isinstance(matched, dict):
            order, order_no = matched, candidate
            break
    if not isinstance(order, dict) or str(order.get("order_kind") or "") != "custom_delivery":
        return False
    try:
        paid_amount = float(order.get("total_amount") or 0)
        quote_amount = float(crm["quote"].get("amount") or 0)
    except (TypeError, ValueError):
        return False
    if quote_amount <= 0 or paid_amount < quote_amount:
        return False
    now = datetime.now(UTC).isoformat()
    crm["payment"] = {
        **payment,
        "status": "paid",
        "amount_paid": paid_amount,
        "currency": str(crm["quote"].get("currency") or "CNY"),
        "reference": order_no,
        "provider_trade_no": str(order.get("trade_no") or ""),
        "verified_source": str(order.get("source") or "payment_ssot"),
        "updated_at": now,
    }
    evidence["crm"] = crm
    run_rows = [row for row in evidence.get("runs", []) if isinstance(row, dict)]
    if not custom_delivery_commerce_blockers(evidence) and not run_rows:
        try:
            evidence["runs"] = [
                await _start_custom_delivery_run(
                    user_id=int(ticket.user_id), evidence=evidence, attempt=1
                )
            ]
            evidence.pop("start_error", None)
        except RECOVERABLE_ERRORS as exc:
            evidence["start_error"] = str(exc)[:1000]
    complete_delivery_if_ready(ticket, evidence)
    audit(
        db,
        event_type="custom_delivery_payment_verified",
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor_type="system",
        detail={
            "order_no": order_no,
            "amount": paid_amount,
            "source": "authoritative_payment_order",
        },
    )
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    return True


@router.post("/custom-deliveries/{ticket_id}/payment-checkout")
async def create_custom_delivery_checkout(
    ticket_id: int,
    body: CustomDeliveryPaymentCheckoutBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery" or int(ticket.user_id) != int(user.id):
        raise HTTPException(404, "定制交付工单不存在")
    evidence = _custom_delivery_evidence(ticket)
    if custom_delivery_pricing_mode(evidence) != "post_delivery_addon":
        raise HTTPException(409, "首次内含交付不需要重新付款")
    crm = custom_delivery_crm(evidence)
    quote = crm["quote"]
    if str(quote.get("status") or "") != "accepted":
        raise HTTPException(409, "请先确认报价后再付款")
    try:
        amount = float(quote.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        raise HTTPException(409, "已确认报价金额无效")
    if str(crm["payment"].get("status") or "") == "paid":
        raise HTTPException(409, "本定制交付已完成付款")
    checkout = await create_custom_delivery_payment_order(
        int(user.id),
        ticket_no=str(ticket.ticket_no),
        subject=f"定制交付新增开发·{str(ticket.title or ticket.ticket_no)}",
        total_amount=f"{amount:.2f}",
        pay_channel=body.pay_channel,
    )
    if not checkout.get("ok") or not str(checkout.get("order_id") or "").strip():
        raise HTTPException(502, str(checkout.get("message") or "支付单创建失败"))
    order_no = str(checkout["order_id"])
    now = datetime.now(UTC).isoformat()
    crm["payment"] = {
        **crm["payment"],
        "status": "unpaid",
        "amount_paid": 0,
        "currency": str(quote.get("currency") or "CNY"),
        "reference": order_no,
        "checkout_type": str(checkout.get("type") or ""),
        "checkout_path": str(checkout.get("checkout_path") or ""),
        "created_at": now,
        "updated_at": now,
    }
    attempts = [
        row for row in evidence.get("payment_attempts", []) if isinstance(row, dict)
    ]
    attempts.append(
        {
            "order_no": order_no,
            "amount": amount,
            "currency": str(quote.get("currency") or "CNY"),
            "pay_channel": body.pay_channel,
            "checkout_type": str(checkout.get("type") or ""),
            "checkout_path": str(checkout.get("checkout_path") or ""),
            "created_at": now,
        }
    )
    evidence["payment_attempts"] = attempts[-20:]
    evidence["crm"] = crm
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    audit(
        db,
        event_type="custom_delivery_payment_order_created",
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor=user,
        actor_type="user",
        detail={
            "order_no": order_no,
            "amount": amount,
            "pay_channel": body.pay_channel,
            "source": "customer_delivery_portal",
        },
    )
    db.commit()
    return {
        "ok": True,
        "order_id": order_no,
        "type": str(checkout.get("type") or ""),
        "redirect_url": str(checkout.get("redirect_url") or ""),
        "qr_code": str(checkout.get("qr_code") or ""),
        "checkout_path": str(checkout.get("checkout_path") or ""),
        "total_amount": f"{amount:.2f}",
    }
