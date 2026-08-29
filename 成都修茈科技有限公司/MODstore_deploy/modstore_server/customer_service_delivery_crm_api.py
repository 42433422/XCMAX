"""定制交付商务 CRM API。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_api import _visible_ticket_or_404
from modstore_server.customer_service_delivery_api import (
    _custom_delivery_evidence,
    _custom_delivery_payload,
    _start_custom_delivery_run,
)
from modstore_server.customer_service_delivery_completion import (
    complete_delivery_if_ready,
)
from modstore_server.customer_service_delivery_models import (
    CustomDeliveryCrmUpdateBody,
    custom_delivery_commerce_blockers,
    custom_delivery_crm,
    custom_delivery_pricing_mode,
)
from modstore_server.customer_service_orchestrator import audit
from modstore_server.customer_service_tools import json_dumps
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.payment_cs_internal import find_matching_paid_order

router = APIRouter()


@router.post("/custom-deliveries/{ticket_id}/crm")
async def update_custom_delivery_crm(
    ticket_id: int,
    body: CustomDeliveryCrmUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery":
        raise HTTPException(404, "定制交付工单不存在")
    evidence = _custom_delivery_evidence(ticket)
    crm = custom_delivery_crm(evidence)
    now = datetime.now(UTC).isoformat()
    if body.section == "assignment":
        owner = body.owner_name.strip()
        if len(owner) < 2:
            raise HTTPException(422, "请填写交付负责人")
        crm["assignment"] = {
            "status": "assigned",
            "owner_name": owner,
            "assigned_at": now,
            "note": body.note.strip(),
        }
    elif body.section == "quote":
        status = body.status.strip() or "draft"
        if status not in {"draft", "sent", "accepted", "rejected", "waived"}:
            raise HTTPException(422, "报价状态无效")
        if status != "waived" and (body.amount is None or body.amount <= 0):
            raise HTTPException(422, "报价金额必须大于 0")
        if status in {"sent", "accepted"} and not body.number.strip():
            raise HTTPException(422, "报价单号不能为空")
        crm["quote"] = {
            "status": status,
            "quote_no": body.number.strip(),
            "amount": body.amount or 0,
            "currency": body.currency.strip().upper() or "CNY",
            "valid_until": body.valid_until.strip(),
            "note": body.note.strip(),
            "updated_at": now,
        }
    elif body.section == "contract":
        status = body.status.strip() or "draft"
        if status not in {"draft", "sent", "signed", "void", "waived"}:
            raise HTTPException(422, "合同状态无效")
        if status in {"sent", "signed"} and not body.number.strip():
            raise HTTPException(422, "合同编号不能为空")
        if status == "signed" and not body.reference.strip():
            raise HTTPException(422, "已签合同必须填写文件或签署凭证")
        crm["contract"] = {
            "status": status,
            "contract_no": body.number.strip(),
            "reference": body.reference.strip(),
            "note": body.note.strip(),
            "updated_at": now,
        }
    else:
        status = body.status.strip() or "unpaid"
        if status not in {"unpaid", "partial", "paid", "refunded", "waived"}:
            raise HTTPException(422, "收款状态无效")
        if status in {"partial", "paid"} and (body.amount is None or body.amount <= 0):
            raise HTTPException(422, "到账金额必须大于 0")
        if status in {"partial", "paid"} and not body.reference.strip():
            raise HTTPException(422, "收款状态不能只靠手工点选，请填写支付流水或线下凭证")
        quote_amount = float(crm.get("quote", {}).get("amount") or 0)
        if status == "paid" and quote_amount > 0 and float(body.amount or 0) < quote_amount:
            raise HTTPException(409, "到账金额小于已确认报价，应记为部分收款")
        if status == "paid" and custom_delivery_pricing_mode(evidence) == "post_delivery_addon":
            order = find_matching_paid_order(
                int(ticket.user_id),
                expected_out_trade_no=body.reference.strip(),
            )
            if not isinstance(order, dict):
                raise HTTPException(409, "交付后新增开发必须填写已支付的真实订单号")
            if str(order.get("order_kind") or "") != "custom_delivery":
                raise HTTPException(409, "该订单不是本定制交付的收款单")
            try:
                paid_amount = float(order.get("total_amount") or 0)
            except (TypeError, ValueError):
                paid_amount = 0
            if quote_amount > 0 and paid_amount < quote_amount:
                raise HTTPException(409, "真实支付订单金额小于已确认报价")
        crm["payment"] = {
            "status": status,
            "amount_paid": body.amount or 0,
            "currency": body.currency.strip().upper() or "CNY",
            "reference": body.reference.strip(),
            "note": body.note.strip(),
            "updated_at": now,
        }
    evidence["crm"] = crm
    evidence["schema_version"] = max(int(evidence.get("schema_version") or 1), 3)
    if (
        custom_delivery_pricing_mode(evidence) == "post_delivery_addon"
        and not custom_delivery_commerce_blockers(evidence)
        and not [row for row in evidence.get("runs", []) if isinstance(row, dict)]
    ):
        try:
            evidence["runs"] = [
                await _start_custom_delivery_run(
                    user_id=int(ticket.user_id),
                    evidence=evidence,
                    attempt=1,
                )
            ]
            evidence.pop("start_error", None)
        except RECOVERABLE_ERRORS as exc:
            evidence["start_error"] = str(exc)[:1000]
    payload = await _custom_delivery_payload(ticket)
    artifacts = payload.get("custom_delivery", {}).get("artifacts", [])
    if artifacts:
        evidence["delivery_artifacts"] = artifacts
    complete_delivery_if_ready(ticket, evidence)
    audit(
        db,
        event_type=f"custom_delivery_crm_{body.section}_updated",
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor=user,
        actor_type="admin",
        detail={
            "section": body.section,
            "status": crm[body.section].get("status"),
            "source": "admin_delivery_center",
        },
    )
    setattr(ticket, "evidence_json", json_dumps(evidence))
    setattr(ticket, "updated_at", datetime.now(UTC))
    db.commit()
    db.refresh(ticket)
    return await _custom_delivery_payload(ticket)
