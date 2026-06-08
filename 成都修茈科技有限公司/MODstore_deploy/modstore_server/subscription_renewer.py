"""订阅自动续费模块。

每天凌晨 02:00 扫描即将到期（24 小时内）且开启自动续费的 UserPlan，
从用户钱包扣款续期；余额不足时发站内通知并关闭自动续费。

调度器入口：start_subscription_scheduler()
  — 由 app_factory.create_app() 在应用启动时调用。

API 端点：
  PATCH /api/plan/auto-renew   — 用户开/关自动续费
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from modstore_server import payment_orders as _po
from modstore_server.api.auth_deps import require_user
from modstore_server.eventing.contracts import SUBSCRIPTION_RENEWAL_FAILED, SUBSCRIPTION_RENEWED
from modstore_server.models import (
    Entitlement,
    PlanTemplate,
    Transaction,
    User,
    UserPlan,
    Wallet,
    get_session_factory,
)
from modstore_server.notification_service import NotificationType, create_notification
from modstore_server.payment_common import _plan_quotas

logger = logging.getLogger(__name__)

router = APIRouter(tags=["subscription"])


# ---------------------------------------------------------------- DTO


class AutoRenewDTO(BaseModel):
    auto_renew: bool


# ---------------------------------------------------------------- API


@router.patch("/api/plan/auto-renew")
def patch_auto_renew(
    body: AutoRenewDTO,
    user: User = Depends(require_user),
):
    """用户开/关当前激活套餐的自动续费。"""
    sf = get_session_factory()
    with sf() as session:
        plan = (
            session.query(UserPlan)
            .filter(UserPlan.user_id == user.id, UserPlan.is_active == True)  # noqa: E712
            .order_by(UserPlan.created_at.desc())
            .first()
        )
        if not plan:
            raise HTTPException(404, "当前账号没有激活的套餐")
        plan.auto_renew = body.auto_renew
        if body.auto_renew:
            plan.renewal_fail_reason = ""
        session.commit()
        return {
            "ok": True,
            "plan_id": plan.plan_id,
            "auto_renew": plan.auto_renew,
            "expires_at": plan.expires_at.isoformat() if plan.expires_at else None,
        }


# ---------------------------------------------------------------- 续费核心逻辑


def renew_expiring_plans() -> dict:
    """扫描即将到期套餐，尝试从钱包扣款续期。由调度器每日调用。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_end = now + timedelta(hours=24)

    sf = get_session_factory()
    renewed = 0
    failed = 0

    with sf() as session:
        expiring = (
            session.query(UserPlan)
            .filter(
                UserPlan.is_active == True,  # noqa: E712
                UserPlan.auto_renew == True,  # noqa: E712
                UserPlan.expires_at != None,  # noqa: E711
                UserPlan.expires_at >= now,
                UserPlan.expires_at <= window_end,
            )
            .all()
        )
        logger.info("订阅续费扫描：找到 %d 条即将到期套餐", len(expiring))

        for user_plan in expiring:
            try:
                _renew_one(session, user_plan, now)
                renewed += 1
            except Exception:
                logger.exception(
                    "续费失败 user_id=%s plan_id=%s", user_plan.user_id, user_plan.plan_id
                )
                failed += 1

    logger.info("订阅续费完成：续费 %d，失败 %d", renewed, failed)
    return {"renewed": renewed, "failed": failed}


def _renew_one(session, user_plan: UserPlan, now: datetime) -> None:
    """对单个 UserPlan 执行续费，含余额校验、扣款、写 Transaction 和 payment_orders。"""
    plan_tmpl = session.query(PlanTemplate).filter(PlanTemplate.id == user_plan.plan_id).first()
    if not plan_tmpl or not plan_tmpl.is_active:
        logger.info("套餐模板不存在或已下架，跳过续费 plan_id=%s", user_plan.plan_id)
        user_plan.auto_renew = False
        user_plan.renewal_fail_reason = "套餐已下架"
        return

    price = float(plan_tmpl.price or 0)
    if price <= 0:
        # 免费套餐直接续期
        user_plan.expires_at = (user_plan.expires_at or now) + timedelta(days=30)
        return

    wallet = (
        session.query(Wallet).filter(Wallet.user_id == user_plan.user_id).with_for_update().first()
    )
    balance = float(wallet.balance if wallet else 0)

    if balance < price:
        # 余额不足：关闭自动续费并发通知
        user_plan.auto_renew = False
        user_plan.renewal_fail_reason = f"余额不足（余额 {balance:.2f}，需 {price:.2f}）"
        logger.info(
            "余额不足，关闭自动续费 user_id=%s plan_id=%s balance=%.2f price=%.2f",
            user_plan.user_id,
            user_plan.plan_id,
            balance,
            price,
        )
        try:
            create_notification(
                user_id=user_plan.user_id,
                notification_type=NotificationType.PAYMENT_FAILED,
                title="套餐自动续费失败",
                content=(
                    f"您的套餐「{plan_tmpl.name}」即将到期，"
                    f"自动续费失败（钱包余额 {balance:.2f} 元，续费需 {price:.2f} 元）。"
                    "请充值后手动续期，或重新开启自动续费。"
                ),
                data={"plan_id": user_plan.plan_id, "price": price, "balance": balance},
            )
        except Exception:
            logger.exception("发送续费失败通知出错 user_id=%s", user_plan.user_id)
        # 发布 subscription.renewal_failed 事件（事务内入 outbox）
        try:
            from modstore_server import webhook_dispatcher

            webhook_dispatcher.enqueue_event(
                session,
                SUBSCRIPTION_RENEWAL_FAILED,
                str(user_plan.user_id),
                {
                    "user_id": user_plan.user_id,
                    "plan_id": user_plan.plan_id,
                    "reason": user_plan.renewal_fail_reason,
                },
            )
        except Exception:
            logger.exception("续费失败事件入 outbox 出错 user_id=%s", user_plan.user_id)
        return

    # 余额充足：扣款
    if wallet:
        wallet.balance = round(balance - price, 6)
        wallet.updated_at = now

    out_trade_no = f"renew_{user_plan.user_id}_{user_plan.plan_id}_{uuid.uuid4().hex[:8]}"
    session.add(
        Transaction(
            user_id=user_plan.user_id,
            amount=-price,
            txn_type="plan_renewal",
            status="completed",
            description=f"套餐自动续费「{plan_tmpl.name}」({out_trade_no})",
        )
    )

    # 延长有效期
    base = user_plan.expires_at if user_plan.expires_at and user_plan.expires_at > now else now
    user_plan.expires_at = base + timedelta(days=30)
    user_plan.renewal_fail_reason = ""

    # 刷新 Entitlement 到期时间
    session.query(Entitlement).filter(
        Entitlement.user_id == user_plan.user_id,
        Entitlement.entitlement_type == "plan",
        Entitlement.is_active == True,  # noqa: E712
    ).update({"expires_at": user_plan.expires_at})

    # 写订单存根（供对账用）
    try:
        _po.create(
            out_trade_no=out_trade_no,
            subject=f"套餐自动续费「{plan_tmpl.name}」",
            total_amount=str(price),
            user_id=user_plan.user_id,
            plan_id=user_plan.plan_id,
            order_kind="plan",
        )
        _po.merge_fields(
            out_trade_no,
            status="paid",
            paid_at=now.isoformat(),
            fulfilled=True,
            pay_channel="wallet",
            kind="plan",
        )
    except Exception:
        logger.exception("写续费订单存根失败 out_trade_no=%s", out_trade_no)

    session.flush()
    logger.info(
        "自动续费成功 user_id=%s plan_id=%s price=%.2f expires_at=%s",
        user_plan.user_id,
        user_plan.plan_id,
        price,
        user_plan.expires_at,
    )
    # 事务内入 outbox：续费业务写与事件入队同一 session.flush()，确保原子性。
    # DB outbox worker 稍后把该行 drain 到 NeuroBus + webhook。
    try:
        from modstore_server import webhook_dispatcher

        webhook_dispatcher.enqueue_event(
            session,
            SUBSCRIPTION_RENEWED,
            str(user_plan.user_id),
            {
                "user_id": user_plan.user_id,
                "plan_id": user_plan.plan_id,
                "out_trade_no": out_trade_no,
                "amount": price,
                "expires_at": user_plan.expires_at.isoformat() if user_plan.expires_at else None,
                "plan_name": plan_tmpl.name,
            },
        )
    except Exception:
        logger.exception("续费事件入 outbox 出错 user_id=%s", user_plan.user_id)
    try:
        create_notification(
            user_id=user_plan.user_id,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="套餐自动续费成功",
            content=(
                f"您的套餐「{plan_tmpl.name}」已自动续费成功，"
                f"扣款 {price:.2f} 元，有效期延至 {user_plan.expires_at.strftime('%Y-%m-%d')}。"
            ),
            data={"plan_id": user_plan.plan_id, "price": price},
        )
    except Exception:
        logger.exception("发送续费成功通知出错 user_id=%s", user_plan.user_id)


# ---------------------------------------------------------------- 调度器


def start_subscription_scheduler() -> None:
    """在 FastAPI lifespan 内启动 APScheduler，每天 02:00 执行续费任务。"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("APScheduler 未安装，订阅自动续费调度器未启动")
        return

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        renew_expiring_plans,
        CronTrigger(hour=2, minute=0),
        id="subscription_auto_renew",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("订阅自动续费调度器已启动（每日 02:00 Asia/Shanghai）")


__all__ = ["router", "start_subscription_scheduler", "renew_expiring_plans"]
