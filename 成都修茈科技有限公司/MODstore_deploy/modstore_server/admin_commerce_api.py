# mypy: disable-error-code="arg-type"
"""管理端订单经营操作：取消、安全改价、退款申请与审核。"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server import alipay_service, payment_orders
from modstore_server.api.deps import get_db, require_admin
from modstore_server.application.payment_gateway import (
    PaymentGatewayService,
    java_payment_unreachable_message,
)
from modstore_server.db.delivery_commerce import CommerceAdminAction
from modstore_server.models import RefundRequest, User

router = APIRouter(prefix="/api/admin/commerce", tags=["admin-commerce"])


class AdminOrderActionBody(BaseModel):
    reason: str = Field(..., min_length=4, max_length=1000)
    idempotency_key: str = Field(..., min_length=12, max_length=192)


class AdminOrderRepriceBody(AdminOrderActionBody):
    new_amount: float = Field(..., gt=0)


class AdminRefundReviewBody(BaseModel):
    action: Literal["approve", "reject"]
    admin_note: str = Field(default="", max_length=2000)


def _action_payload(row: CommerceAdminAction) -> dict[str, Any]:
    try:
        result = json.loads(row.after_json or "{}")
    except ValueError:
        result = {}
    return result if isinstance(result, dict) else {}


def _existing_action(db: Session, key: str) -> CommerceAdminAction | None:
    return (
        db.query(CommerceAdminAction)
        .filter(CommerceAdminAction.idempotency_key == key.strip())
        .first()
    )


def _record_action(
    db: Session,
    *,
    user: User,
    action: str,
    order_no: str,
    key: str,
    reason: str,
    before: dict[str, Any],
    after: dict[str, Any],
    status: str = "completed",
) -> None:
    db.add(
        CommerceAdminAction(
            actor_user_id=int(user.id),
            action=action,
            aggregate_type="payment_order",
            aggregate_id=order_no,
            idempotency_key=key.strip(),
            status=status,
            reason=reason.strip(),
            before_json=json.dumps(before, ensure_ascii=False, default=str),
            after_json=json.dumps(after, ensure_ascii=False, default=str),
        )
    )
    db.commit()


async def _forward_java(request: Request, path: str, *, method: str, body: dict | None = None):
    gw = PaymentGatewayService()
    if gw.backend != "java":
        return None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.request(
                method,
                f"{gw.java_url.rstrip('/')}{path}",
                json=body,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, java_payment_unreachable_message(exc)) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("message") or response.json().get("detail")
        except ValueError:
            detail = response.text
        raise HTTPException(response.status_code, detail or "Java 订单服务请求失败")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "Java 订单服务返回非 JSON 数据") from exc


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "total_orders": len(rows),
        "paid_orders": 0,
        "pending_orders": 0,
        "paid_revenue": 0.0,
        "by_status": {},
    }
    for order in rows:
        status = str(order.get("status") or "unknown")
        result["by_status"][status] = result["by_status"].get(status, 0) + 1
        if status == "paid":
            result["paid_orders"] += 1
            try:
                result["paid_revenue"] += float(order.get("total_amount") or 0)
            except (TypeError, ValueError):
                pass
        if status == "pending":
            result["pending_orders"] += 1
    return result


@router.get("/orders")
async def list_admin_commerce_orders(
    request: Request,
    status: str = Query(default="", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_admin),
):
    java = await _forward_java(
        request,
        f"/api/admin/commerce/orders?status={status}&limit={limit}&offset={offset}",
        method="GET",
    )
    if java is not None:
        return java
    rows, total = payment_orders.list_orders(
        user_id=0,
        status=status or None,
        limit=limit,
        offset=offset,
    )
    all_rows, _ = payment_orders.list_orders(user_id=0, status=None, limit=100000, offset=0)
    return {"items": rows, "total": total, "summary": _summary(all_rows), "source": "python_json"}


def _close_provider_order(order: dict[str, Any]) -> None:
    pay_type = str(order.get("pay_type") or "").lower()
    if "wechat" in pay_type:
        raise HTTPException(409, "微信待支付单需先在微信支付后台关单，本次未修改本地状态")
    if pay_type or order.get("qr_code"):
        closed = alipay_service.close_order(out_trade_no=str(order.get("out_trade_no") or ""))
        if not closed.get("ok"):
            raise HTTPException(
                409, f"支付平台关单失败，未修改本地订单：{closed.get('message') or '未知错误'}"
            )


@router.post("/orders/{order_no}/cancel")
async def cancel_admin_order(
    order_no: str,
    body: AdminOrderActionBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    existing = _existing_action(db, body.idempotency_key)
    if existing:
        return {**_action_payload(existing), "duplicate": True}
    java = await _forward_java(
        request,
        f"/api/admin/commerce/orders/{order_no}/cancel",
        method="POST",
        body=body.model_dump(),
    )
    if java is not None:
        _record_action(
            db,
            user=user,
            action="cancel",
            order_no=order_no,
            key=body.idempotency_key,
            reason=body.reason,
            before={},
            after=java,
        )
        return java
    order = payment_orders.find(order_no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if str(order.get("status") or "") != "pending":
        raise HTTPException(409, "只能取消待支付订单")
    before = dict(order)
    _close_provider_order(order)
    payment_orders.merge_fields(
        order_no,
        status="closed",
        cancelled_at=datetime.now(UTC).isoformat(),
        cancel_reason=body.reason.strip(),
        cancelled_by=int(user.id),
    )
    after = {"ok": True, "order": payment_orders.find(order_no), "status": "closed"}
    _record_action(
        db,
        user=user,
        action="cancel",
        order_no=order_no,
        key=body.idempotency_key,
        reason=body.reason,
        before=before,
        after=after,
    )
    return after


@router.post("/orders/{order_no}/reprice")
async def reprice_admin_order(
    order_no: str,
    body: AdminOrderRepriceBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    existing = _existing_action(db, body.idempotency_key)
    if existing:
        return {**_action_payload(existing), "duplicate": True}
    java = await _forward_java(
        request,
        f"/api/admin/commerce/orders/{order_no}/reprice",
        method="POST",
        body=body.model_dump(),
    )
    if java is not None:
        _record_action(
            db,
            user=user,
            action="reprice",
            order_no=order_no,
            key=body.idempotency_key,
            reason=body.reason,
            before={},
            after=java,
        )
        return java
    order = payment_orders.find(order_no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if str(order.get("status") or "") != "pending":
        raise HTTPException(409, "已支付或终态订单不允许改价，请走退款审核")
    old_amount = round(float(order.get("total_amount") or 0), 2)
    new_amount = round(float(body.new_amount), 2)
    if new_amount == old_amount:
        raise HTTPException(409, "新金额与原金额相同")
    before = dict(order)
    _close_provider_order(order)
    replacement_no = f"ADJ{int(time.time())}{uuid.uuid4().hex[:8].upper()}"
    created = payment_orders.create(
        out_trade_no=replacement_no,
        subject=str(order.get("subject") or "人工改价订单"),
        total_amount=f"{new_amount:.2f}",
        user_id=int(order.get("user_id") or 0),
        item_id=int(order.get("item_id") or 0),
        plan_id=str(order.get("plan_id") or ""),
        order_kind=str(order.get("order_kind") or ""),
    )
    if not created.get("ok"):
        payment_orders.merge_fields(order_no, status="closed", replacement_failed=True)
        after = {
            "ok": False,
            "partial_success": True,
            "status": "replacement_failed",
            "original_order_no": order_no,
            "message": f"原支付单已关闭，但新订单创建失败：{created.get('message') or '未知错误'}",
        }
        _record_action(
            db,
            user=user,
            action="reprice",
            order_no=order_no,
            key=body.idempotency_key,
            reason=body.reason,
            before=before,
            after=after,
            status="partial",
        )
        return after
    pay = alipay_service.create_pay_order(
        out_trade_no=replacement_no,
        subject=str(order.get("subject") or "人工改价订单"),
        total_amount=f"{new_amount:.2f}",
        user_agent=request.headers.get("user-agent", ""),
        notify_url=(os.environ.get("ALIPAY_NOTIFY_URL") or "").strip() or None,
    )
    if not pay.get("ok"):
        payment_orders.merge_fields(
            replacement_no, status="failed", provider_error=pay.get("message")
        )
        payment_orders.merge_fields(
            order_no, status="closed", replacement_failed=True, replaced_by=replacement_no
        )
        after = {
            "ok": False,
            "partial_success": True,
            "status": "provider_failed",
            "original_order_no": order_no,
            "replacement_order_no": replacement_no,
            "message": f"原支付单已关闭，新金额支付单创建失败：{pay.get('message') or '未知错误'}",
        }
        _record_action(
            db,
            user=user,
            action="reprice",
            order_no=order_no,
            key=body.idempotency_key,
            reason=body.reason,
            before=before,
            after=after,
            status="partial",
        )
        return after
    payment_orders.merge_fields(
        replacement_no,
        pay_type=pay.get("type"),
        qr_code=pay.get("qr_code"),
        redirect_url=pay.get("redirect_url"),
        adjusted_from=order_no,
        adjustment_reason=body.reason.strip(),
    )
    payment_orders.merge_fields(
        order_no,
        status="closed",
        replaced_by=replacement_no,
        reprice_reason=body.reason.strip(),
    )
    after = {
        "ok": True,
        "status": "replaced",
        "original_order_no": order_no,
        "replacement_order": payment_orders.find(replacement_no),
    }
    _record_action(
        db,
        user=user,
        action="reprice",
        order_no=order_no,
        key=body.idempotency_key,
        reason=body.reason,
        before=before,
        after=after,
    )
    return after


@router.post("/orders/{order_no}/refund-request")
async def create_admin_refund_request(
    order_no: str,
    body: AdminOrderActionBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    existing_action = _existing_action(db, body.idempotency_key)
    if existing_action:
        return {**_action_payload(existing_action), "duplicate": True}
    java = await _forward_java(
        request,
        f"/api/admin/commerce/orders/{order_no}/refund-request",
        method="POST",
        body=body.model_dump(),
    )
    if java is not None:
        _record_action(
            db,
            user=user,
            action="refund_request",
            order_no=order_no,
            key=body.idempotency_key,
            reason=body.reason,
            before={},
            after=java,
        )
        return java
    order = payment_orders.find(order_no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if str(order.get("status") or "") != "paid":
        raise HTTPException(409, "只有已支付订单可发起退款审核")
    existing = db.query(RefundRequest).filter(RefundRequest.order_no == order_no).first()
    if existing:
        result = {
            "ok": True,
            "refund_id": existing.id,
            "status": existing.status,
            "duplicate": True,
        }
    else:
        refund = RefundRequest(
            user_id=int(order.get("user_id") or 0),
            order_no=order_no,
            amount=float(order.get("total_amount") or 0),
            reason=body.reason.strip(),
            status="pending",
        )
        db.add(refund)
        db.flush()
        result = {"ok": True, "refund_id": refund.id, "status": "pending"}
    _record_action(
        db,
        user=user,
        action="refund_request",
        order_no=order_no,
        key=body.idempotency_key,
        reason=body.reason,
        before=order,
        after=result,
    )
    return result


@router.get("/refunds/pending")
async def list_pending_refunds(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    java = await _forward_java(request, "/api/refunds/admin/pending", method="GET")
    if java is not None:
        return java
    rows = (
        db.query(RefundRequest)
        .filter(RefundRequest.status == "pending")
        .order_by(RefundRequest.created_at.asc())
        .all()
    )
    return {
        "refunds": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "order_no": row.order_no,
                "amount": row.amount,
                "reason": row.reason,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/refunds/{refund_id}/review")
async def review_pending_refund(
    refund_id: int,
    body: AdminRefundReviewBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    java = await _forward_java(
        request,
        f"/api/refunds/admin/{refund_id}/review",
        method="POST",
        body=body.model_dump(),
    )
    if java is not None:
        return java
    from modstore_server.refund_api import admin_review_refund

    return await admin_review_refund(refund_id, body, db, user)
