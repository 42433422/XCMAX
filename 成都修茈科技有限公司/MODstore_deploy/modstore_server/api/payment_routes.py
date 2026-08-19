"""XC AGI 支付宝支付路由：下单、回调、查询、套餐、诊断。

⚠️ 兼容层：当 ``PAYMENT_BACKEND=java`` 时（生产推荐），FastAPI 中间件会将
``/api/payment/**`` 整段透传到 Java 支付服务（见 ``app._payment_backend_proxy_middleware``），
本文件中的实现仅作为本地开发或灰度回滚用 fallback。任何对账/履约的真实入口请改写
``java_payment_service``，并通过 ``payment_contract`` + ``test_payment_contract`` 维护契约。

新增端点应优先：
1. 在 ``payment_contract.PAYMENT_ENDPOINTS`` 注册；
2. 在 Java 控制器实现；
3. 仅在 fallback 必要时在本文件实现。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request

from modstore_server import (
    alipay_service,
    cache,
    payment_orders,
)
from modstore_server.account_license_plans import public_account_license_plans
from modstore_server.api.deps import _get_current_user
from modstore_server.api.payment_router import router as router
from modstore_server.models import (
    PlanTemplate,
    Quota,
    User,
    get_session_factory,
    init_db,
)
from modstore_server.payment_common import (
    REPLAY_WINDOW as REPLAY_WINDOW,
    CheckoutDTO as CheckoutDTO,
    RefundDTO as RefundDTO,
    SignCheckoutBody as SignCheckoutBody,
    _amounts_match,
    _membership_meta,
    _plan_as_dict,
    _plan_rows,
    canonical_checkout_sign_data as canonical_checkout_sign_data,
)

logger = logging.getLogger(__name__)
init_db()
# Plan 模板可能在 init_db() 中被升级（VIP/VIP+/svip 改名 + SVIP2~8 新增），
# 立刻清掉 /plans 的缓存，避免老旧 5 分钟缓存遮蔽新数据。
try:
    cache.delete("modstore:plans:active")
except Exception:
    pass


# ── 套餐列表 ─────────────────────────────────────────────────


def _fulfill_paid_order(out_trade_no: str) -> None:
    """支付成功后幂等入账（钱包 / 套餐 / 市场商品）。"""
    if not payment_orders.is_local_source_of_truth():
        logger.warning(
            "PAYMENT_BACKEND=java; skipping Python _fulfill_paid_order for %s (Java owns fulfillment)",
            out_trade_no,
        )
        return
    order = payment_orders.find(out_trade_no)
    if not order:
        logger.warning("_fulfill_paid_order: order not found %s", out_trade_no)
        return
    if order.get("fulfilled"):
        return

    from datetime import datetime, timezone

    from modstore_server.models import get_session_factory
    from modstore_server.payment_fulfilment import FulfilContext, select_strategy

    try:
        user_id = int(order.get("user_id") or 0)
        total_amount = float(order.get("total_amount") or 0)
        item_id = int(order.get("item_id") or 0)
        plan_id = str(order.get("plan_id") or "").strip()
        order_kind = str(order.get("order_kind") or "").strip()
    except (TypeError, ValueError):
        logger.warning("_fulfill_paid_order: malformed order %s", out_trade_no)
        return

    ctx = FulfilContext(
        out_trade_no=out_trade_no,
        user_id=user_id,
        total_amount=total_amount,
        item_id=item_id,
        plan_id=plan_id,
        kind=order_kind,
        order=dict(order),
    )
    strategy = select_strategy(ctx)
    sf = get_session_factory()
    now = datetime.now(timezone.utc)
    with sf() as session:
        if strategy.is_already_fulfilled(session, ctx):
            payment_orders.merge_fields(out_trade_no, fulfilled=True)
            session.commit()
            return
        description, txn_type = strategy.description_and_txn_type(ctx)
        strategy.fulfill(session, ctx, now=now, description=description, txn_type=txn_type)
        payment_orders.merge_fields(out_trade_no, fulfilled=True)
        session.commit()
    logger.info("_fulfill_paid_order completed for %s", out_trade_no)


# ── 套餐列表 ─────────────────────────────────────────────────


@router.get("/plans")
def api_payment_plans():
    """获取可用套餐列表。"""
    cached = cache.get_json("modstore:plans:active")
    if cached is not None:
        return cached
    sf = get_session_factory()
    with sf() as session:
        result = {"plans": [_plan_as_dict(p) for p in _plan_rows(session)]}
        cache.set_json("modstore:plans:active", result, 300)
        return result


@router.get("/account-plans")
def api_payment_account_plans():
    """Public XCAGI desktop account licenses; never mixed with VIP/SVIP quota plans."""

    return {"plans": public_account_license_plans()}


@router.get("/my-plan")
def api_my_plan(user: User = Depends(_get_current_user)):
    from modstore_server.account_lifecycle import active_membership_plan

    sf = get_session_factory()
    with sf() as session:
        row = active_membership_plan(session, int(user.id))
        if not row:
            return {"plan": None, "quotas": [], "membership": _membership_meta(None)}
        plan = session.query(PlanTemplate).filter(PlanTemplate.id == row.plan_id).first()
        membership = _membership_meta(row.plan_id)
        quotas = session.query(Quota).filter(Quota.user_id == user.id).all()
        return {
            "plan": {
                "id": row.plan_id,
                "name": plan.name if plan else row.plan_id,
                "started_at": row.started_at.isoformat() if row.started_at else "",
                "expires_at": row.expires_at.isoformat() if row.expires_at else "",
                **membership,
            },
            "membership": membership,
            "quotas": [
                {
                    "quota_type": q.quota_type,
                    "total": q.total,
                    "used": q.used,
                    "remaining": max((q.total or 0) - (q.used or 0), 0),
                    "reset_at": q.reset_at.isoformat() if q.reset_at else "",
                }
                for q in quotas
            ],
        }


# ── 下单（Checkout） ─────────────────────────────────────────


from modstore_server.api.payment_checkout_routes import (  # noqa: E402
    _forward_checkout_to_java as _forward_checkout_to_java,
)
from modstore_server.api.payment_checkout_routes import (  # noqa: E402
    api_payment_checkout as api_payment_checkout,
)
from modstore_server.api.payment_checkout_routes import (  # noqa: E402
    api_sign_checkout as api_sign_checkout,
)


# ── 支付宝异步通知回调 ────────────────────────────────────────


@router.post("/notify/alipay")
async def api_payment_notify_alipay(request: Request):
    """
    支付宝异步通知。
    验签 → 更新订单 → 发放权益。
    """
    try:
        form_data = await request.form()
        data = dict(form_data)

        signature = data.pop("sign", "")
        if not signature:
            logger.warning("支付宝通知缺少签名")
            return "fail"

        # 验签
        if not alipay_service.verify_notify(data, signature):
            logger.warning("支付宝通知验签失败")
            return "fail"

        out_trade_no = data.get("out_trade_no", "")
        trade_status = data.get("trade_status", "")
        trade_no = data.get("trade_no", "")
        total_amount = data.get("total_amount", "")
        buyer_id = data.get("buyer_id", "")

        if not out_trade_no:
            logger.warning("支付宝通知缺少 out_trade_no")
            return "fail"

        # 只处理支付成功的通知
        if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            return "success"

        # 查询本地订单
        order = payment_orders.find(out_trade_no)
        if not order:
            logger.warning("本地订单不存在: %s", out_trade_no)
            return "fail"

        if order.get("status") == "paid":
            logger.info("订单已处理，跳过: %s", out_trade_no)
            return "success"

        # 金额校验（规范化 + 容差，避免 str/float 与格式差异）
        if not _amounts_match(order.get("total_amount"), total_amount):
            logger.warning(
                "金额不匹配: 期望 %s, 实际 %s",
                order.get("total_amount"),
                total_amount,
            )
            return "fail"

        # 更新订单状态
        paid_at = datetime.now(timezone.utc).isoformat()
        payment_orders.update_status(
            out_trade_no=out_trade_no,
            status="paid",
            trade_no=trade_no,
            buyer_id=buyer_id,
            paid_at=paid_at,
        )

        _fulfill_paid_order(out_trade_no)
        logger.info("订单支付成功并已发放权益: %s, 金额 %s", out_trade_no, total_amount)
        return "success"
    except Exception as e:
        logger.error("处理支付宝通知异常: %s", e)
        return "fail"


# ── 订单查询 ──────────────────────────────────────────────────


@router.get("/query/{out_trade_no}")
def api_payment_query(out_trade_no: str, user: User = Depends(_get_current_user)):
    """查询本地订单状态，同时调用支付宝接口确认。登录用户只能查询自己的订单；管理员可查任意订单。"""
    try:
        order = payment_orders.find(out_trade_no)
        if not order:
            raise HTTPException(404, "订单不存在")
        if not user.is_admin and str(order.get("user_id", "")) != str(user.id):
            raise HTTPException(403, "无权查看该订单")

        # 如果本地状态为 pending，尝试调用支付宝确认
        if order.get("status") == "pending":
            try:
                alipay_result = alipay_service.query_order(out_trade_no=out_trade_no)
                if alipay_result.get("ok"):
                    raw = alipay_result.get("raw", {})
                    trade_status = raw.get("trade_status", "")
                    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                        remote_amt = raw.get("total_amount")
                        if not _amounts_match(order.get("total_amount"), remote_amt):
                            logger.warning(
                                "查询同步金额不匹配: order=%s 本地=%s 支付宝=%s",
                                out_trade_no,
                                order.get("total_amount"),
                                remote_amt,
                            )
                        else:
                            payment_orders.update_status(
                                out_trade_no=out_trade_no,
                                status="paid",
                                trade_no=raw.get("trade_no"),
                                buyer_id=raw.get("buyer_id"),
                                paid_at=datetime.now(timezone.utc).isoformat(),
                            )
                            _fulfill_paid_order(out_trade_no)
                            order = payment_orders.find(out_trade_no) or order
            except Exception as e:
                logger.error("查询支付宝订单状态异常: %s", e)
                # 继续返回本地订单状态，不影响查询

        if order.get("status") == "paid" and not order.get("fulfilled"):
            try:
                _fulfill_paid_order(out_trade_no)
                order = payment_orders.find(out_trade_no) or order
            except Exception as e:
                logger.error("发放权益异常: %s", e)
                # 继续返回订单状态

        return order
    except HTTPException:
        raise
    except Exception as e:
        logger.error("查询订单异常: %s", e)
        raise HTTPException(500, "系统内部错误，请稍后重试")


@router.get("/orders")
def api_payment_list_orders(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(_get_current_user),
):
    """列出当前用户的支付订单。"""
    try:
        rows, total = payment_orders.list_orders(
            user_id=user.id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"orders": rows, "total": total}
    except Exception as e:
        logger.error("查询订单列表异常: %s", e)
        raise HTTPException(500, "系统内部错误，请稍后重试")


@router.post("/orders/dismiss-non-active")
def api_payment_dismiss_non_active_orders(user: User = Depends(_get_current_user)):
    """将当前用户所有「非活跃」（closed / expired / refunded）订单标记为已读/隐藏。
    前端 paymentDismissNonActiveOrders 消费此接口。
    """
    try:
        rows, _ = payment_orders.list_orders(user_id=user.id, status=None, limit=500, offset=0)
        dismissed = 0
        for o in rows:
            if (o.get("status") or "").lower() in ("closed", "expired", "refunded", "cancelled"):
                ono = o.get("out_trade_no") or o.get("order_no") or ""
                if ono:
                    payment_orders.merge_fields(ono, dismissed=True)
                    dismissed += 1
        return {"ok": True, "dismissed": dismissed}
    except Exception as e:
        logger.error("dismiss-non-active 异常: %s", e)
        raise HTTPException(500, "系统内部错误")


@router.post("/cancel/{order_no}")
def api_payment_cancel_order(order_no: str, user: User = Depends(_get_current_user)):
    """取消待支付订单。"""
    ono = (order_no or "").strip()
    order = payment_orders.find(ono)
    if not order or int(order.get("user_id") or 0) != user.id:
        raise HTTPException(404, "订单不存在")
    if (order.get("status") or "").strip().lower() != "pending":
        raise HTTPException(400, f"订单状态为 {order.get('status')}，无法取消")
    payment_orders.merge_fields(ono, status="closed")
    return {"ok": True}


# ── 诊断 ─────────────────────────────────────────────────────


@router.get("/diagnostics")
def api_payment_diagnostics(user: User = Depends(_get_current_user)):
    """支付配置诊断（管理员用）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return alipay_service.diagnostics_snapshot()


# ── 已购权益 ─────────────────────────────────────────────────


from modstore_server.api.payment_account_routes import (  # noqa: E402
    api_payment_entitlements as api_payment_entitlements,
)
from modstore_server.api.payment_account_routes import (  # noqa: E402
    api_payment_refund as api_payment_refund,
)
from modstore_server.api.payment_account_routes import (  # noqa: E402
    api_usage_metrics as api_usage_metrics,
)
