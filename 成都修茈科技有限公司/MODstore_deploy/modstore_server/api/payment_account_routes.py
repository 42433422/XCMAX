# mypy: disable-error-code="arg-type, assignment"
"""Entitlement, usage, and refund routes for payment accounts."""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException

from modstore_server import account_level_service, payment_orders
from modstore_server.api.deps import _get_current_user
from modstore_server.api.payment_router import router
from modstore_server.models import (
    CatalogItem,
    EmployeeExecutionMetric,
    Entitlement,
    Purchase,
    Transaction,
    User,
    Wallet,
    get_session_factory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.payment_common import RefundDTO

logger = logging.getLogger(__name__)


@router.get("/entitlements")
def api_payment_entitlements(user: User = Depends(_get_current_user)):
    """获取用户已购买的 MOD/AI 员工列表。"""
    sf = get_session_factory()
    with sf() as session:
        purchases = (
            session.query(Purchase)
            .filter(Purchase.user_id == user.id)
            .order_by(Purchase.created_at.desc())
            .all()
        )
        items = []
        for p in purchases:
            item = session.query(CatalogItem).filter(CatalogItem.id == p.catalog_id).first()
            if item:
                items.append(
                    {
                        "purchase_id": p.id,
                        "catalog_id": item.id,
                        "pkg_id": item.pkg_id,
                        "version": item.version,
                        "name": item.name,
                        "price_paid": p.amount,
                        "purchased_at": p.created_at.isoformat() if p.created_at else "",
                    }
                )
        return {"items": items, "total": len(items)}


@router.get("/usage-metrics")
def api_usage_metrics(user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.user_id.in_([0, user.id]))
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(200)
            .all()
        )
        total = len(rows)
        ok = len([r for r in rows if r.status == "success"])
        token_sum = sum(int(r.llm_tokens or 0) for r in rows)
        duration = sum(float(r.duration_ms or 0) for r in rows)
        return {
            "total_calls": total,
            "success_rate": (ok / total * 100.0) if total else 0,
            "total_tokens": token_sum,
            "avg_duration_ms": (duration / total) if total else 0.0,
            "rows": [
                {
                    "employee_id": r.employee_id,
                    "task": r.task,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "llm_tokens": r.llm_tokens,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows[:30]
            ],
        }


@router.post("/refund")
def api_payment_refund(body: RefundDTO, user: User = Depends(_get_current_user)):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    order = payment_orders.find(body.out_trade_no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.get("status") != "paid":
        raise HTTPException(400, "仅支持已支付订单退款")
    if order.get("refunded"):
        raise HTTPException(400, "订单已退款")
    sf = get_session_factory()
    with sf() as session:
        user_id = int(order.get("user_id") or 0)
        amount = float(order.get("total_amount") or 0)
        wallet = session.query(Wallet).filter(Wallet.user_id == user_id).with_for_update().first()
        if not wallet:
            wallet = Wallet(user_id=user_id, balance=0.0)
            session.add(wallet)
            session.flush()
        # 按订单类型决定是否调整钱包余额：
        #   wallet  — 充值退款，需从余额扣回（余额必须充足，否则拒绝）
        #   plan    — 套餐退款，同步收回已发放的 LLM 余额（向下取 0，不允许负数）
        #   item    — 市场商品通过支付宝退款，钱包余额无需变动
        kind = (order.get("kind") or "").strip()
        if kind == "wallet":
            current = float(wallet.balance or 0)
            if current < amount:
                raise HTTPException(
                    400,
                    f"钱包余额（{current:.2f}）不足以退款（{amount:.2f}），请先检查账户",
                )
            wallet.balance = current - amount
        elif kind == "plan":
            wallet.balance = max(0.0, float(wallet.balance or 0) - amount)
        # else: item/其他 — 支付宝渠道退款，不动钱包余额
        session.add(
            Transaction(
                user_id=user_id,
                amount=-amount,
                txn_type="refund",
                status="completed",
                description=f"退款 {body.out_trade_no}: {body.reason}",
            )
        )
        session.query(Entitlement).filter(
            Entitlement.source_order_id == body.out_trade_no,
            Entitlement.is_active == True,  # noqa: E712
        ).update({"is_active": False})
        try:
            xp_revoked = account_level_service.revoke_order_xp(
                session,
                user_id=user_id,
                out_trade_no=body.out_trade_no,
                description=f"管理员退款扣回经验 ({body.out_trade_no})",
            )
            if xp_revoked:
                logger.info(
                    "账号经验 -%s user=%s order=%s",
                    xp_revoked,
                    user_id,
                    body.out_trade_no,
                )
        except RECOVERABLE_ERRORS:
            logger.exception("管理员退款扣回经验失败: %s", body.out_trade_no)
        payment_orders.merge_fields(body.out_trade_no, refunded=True, refund_reason=body.reason)
        session.commit()
    return {"ok": True}
