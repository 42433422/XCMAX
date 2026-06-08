"""退款申请（用户侧 + 管理员审核）。

主路径：``PAYMENT_BACKEND=java`` 时，FastAPI 将 ``/api/refunds/**`` 整段透传到
``JAVA_PAYMENT_SERVICE_URL``，订单事实源在 Java/PostgreSQL（见 ``RefundService``）。

本文件中的 ``payment_orders.find/merge`` 仅在使用 ``PAYMENT_BACKEND=python`` 或本地回滚
调试时参与执行；与 ``payment_orders.is_local_source_of_truth()`` 的语义一致。
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server import (
    account_level_service,
    alipay_service,
    payment_orders,
    webhook_dispatcher,
)
from modstore_server.api.deps import _get_current_user
from modstore_server.eventing.contracts import REFUND_APPROVED, REFUND_FAILED, REFUND_REJECTED
from modstore_server.infrastructure.db import get_db
from modstore_server.models import Entitlement, RefundRequest, User

router = APIRouter(prefix="/api/refunds", tags=["refunds"])


class RefundApplyBody(BaseModel):
    order_no: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(..., min_length=5, max_length=1000)


class RefundReviewBody(BaseModel):
    action: Literal["approve", "reject"]
    admin_note: str = Field(default="", max_length=2000)


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


def _publish_refund_event(event_type: str, refund: RefundRequest) -> None:
    webhook_dispatcher.publish_event(event_type, refund.order_no, _refund_payload(refund))


@router.get("/admin/pending")
async def admin_pending_refunds(
    db: Session = Depends(get_db), user: User = Depends(_get_current_user)
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    rows = (
        db.query(RefundRequest)
        .filter(RefundRequest.status == "pending")
        .order_by(RefundRequest.created_at.desc())
        .all()
    )
    return {
        "refunds": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "order_no": r.order_no,
                "amount": r.amount,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/admin/{refund_id}/review")
async def admin_review_refund(
    refund_id: int,
    body: RefundReviewBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")

    refund = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
    if not refund:
        raise HTTPException(404, "退款申请不存在")
    if refund.status != "pending":
        raise HTTPException(400, f"当前状态为 {refund.status}，无法审核")

    note = (body.admin_note or "").strip()

    if body.action == "reject":
        refund.status = "rejected"
        refund.admin_note = note
        db.commit()
        db.refresh(refund)
        # 站内通知由 ``eventing.subscribers._on_refund_outcome`` 处理
        _publish_refund_event(REFUND_REJECTED, refund)
        return {"ok": True, "status": refund.status}

    order = payment_orders.find(refund.order_no)
    if not order:
        raise HTTPException(404, "关联订单不存在")

    trade_no = order.get("trade_no")
    trade_no_s = str(trade_no).strip() if trade_no else None
    out_req = f"RF{refund.id}_{int(time.time())}"
    reason = (refund.reason or "")[:200] or "用户申请退款"

    res = alipay_service.refund_order(
        out_trade_no=refund.order_no,
        trade_no=trade_no_s,
        refund_amount=f"{float(refund.amount):.2f}",
        out_request_no=out_req,
        refund_reason=reason,
    )

    refund.admin_note = note
    if res.get("ok"):
        refund.status = "refunded"
        db.query(Entitlement).filter(
            Entitlement.source_order_id == refund.order_no,
            Entitlement.is_active == True,
        ).update({"is_active": False})
        try:
            account_level_service.revoke_order_xp(
                db,
                user_id=refund.user_id,
                out_trade_no=refund.order_no,
                description=f"退款扣回经验 ({refund.order_no})",
            )
        except Exception:
            pass
        db.commit()
        db.refresh(refund)
        payment_orders.merge_fields(refund.order_no, refunded=True)
        # 通知由 ``eventing.subscribers._on_refund_outcome`` 监听 refund.* 事件
        _publish_refund_event(REFUND_APPROVED, refund)
    else:
        refund.status = "refund_failed"
        err = res.get("message") or str(res.get("raw") or "")
        refund.admin_note = (note + ("\n" if note else "") + f"支付宝退款失败: {err}")[:2000]
        db.commit()
        db.refresh(refund)
        _publish_refund_event(REFUND_FAILED, refund)

    return {"ok": True, "status": refund.status}


@router.post("/apply")
async def apply_refund(
    body: RefundApplyBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    order = payment_orders.find(body.order_no.strip())
    if not order or int(order.get("user_id") or 0) != user.id:
        raise HTTPException(404, "订单不存在")
    if (order.get("status") or "").strip().lower() != "paid":
        raise HTTPException(400, "只有已支付订单可申请退款")

    existing = (
        db.query(RefundRequest).filter(RefundRequest.order_no == body.order_no.strip()).first()
    )
    if existing:
        raise HTTPException(400, "该订单已有退款申请")

    try:
        amount = float(order.get("total_amount") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "订单金额无效")

    row = RefundRequest(
        user_id=user.id,
        order_no=body.order_no.strip(),
        amount=amount,
        reason=body.reason.strip(),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "refund_id": row.id}


@router.get("/my")
async def my_refunds(db: Session = Depends(get_db), user: User = Depends(_get_current_user)):
    rows = (
        db.query(RefundRequest)
        .filter(RefundRequest.user_id == user.id)
        .order_by(RefundRequest.id.desc())
        .all()
    )
    return {
        "refunds": [
            {
                "id": r.id,
                "order_no": r.order_no,
                "amount": r.amount,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]
    }
