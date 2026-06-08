"""按订单类型拆分的履约策略（item / plan / wallet）。

原 ``payment_api._fulfill_paid_order`` 是 280+ 行的单函数，混杂了：

- 选订单类型 + 决定 description / txn_type
- 幂等检查（按类型用不同表 / 字段）
- 真正的履约写入（Purchase / Entitlement / UserPlan / Quota / Wallet / Transaction）
- 共享的 XP 入账 + 事件发布 + 自动部署

本模块把"按类型差异化的部分"抽成 :class:`_FulfilStrategy` 子类，
共享的部分留在 ``payment_api._fulfill_paid_order`` 主函数里。三类策略与原
分支行为严格一一对应，便于回归（见 ``tests/test_payment_*``）。
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict

from sqlalchemy.orm import Session

from modstore_server.models import (
    AuthorEarning,
    CatalogItem,
    Entitlement,
    PlanTemplate,
    Purchase,
    Quota,
    Transaction,
    UserPlan,
    Wallet,
)
from modstore_server.payment_common import _plan_quotas

_PLATFORM_FEE_RATE: float = float(os.environ.get("PLATFORM_FEE_RATE", "0.30"))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- context


@dataclass
class FulfilContext:
    """所有履约策略需要的最小信息（只读）。"""

    out_trade_no: str
    user_id: int
    total_amount: float
    item_id: int
    plan_id: str
    kind: str
    order: Dict[str, Any]


# ---------------------------------------------------------------- base


class FulfilStrategy(ABC):
    """履约策略接口。子类只关注"按类型不同的部分"。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名（用于日志）。"""

    @abstractmethod
    def description_and_txn_type(self, ctx: FulfilContext) -> tuple[str, str]:
        """返回 ``(description, txn_type)``——用于 Transaction 行 / 日志。"""

    @abstractmethod
    def is_already_fulfilled(self, session: Session, ctx: FulfilContext) -> bool:
        """幂等检查：是否已经发放过权益（避免重复回调时双发）。"""

    @abstractmethod
    def fulfill(
        self,
        session: Session,
        ctx: FulfilContext,
        *,
        now: datetime,
        description: str,
        txn_type: str,
    ) -> None:
        """真正的履约写入。调用方负责 commit + 标记 fulfilled。"""


# ---------------------------------------------------------------- item


class ItemFulfilStrategy(FulfilStrategy):
    """商品购买：写 Purchase + Entitlement，员工类商品额外加 employee_count 配额。"""

    name = "item"

    def description_and_txn_type(self, ctx: FulfilContext) -> tuple[str, str]:
        return f"商品购买 ({ctx.out_trade_no})", "item_purchase"

    def is_already_fulfilled(self, session: Session, ctx: FulfilContext) -> bool:
        return (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == ctx.out_trade_no)
            .first()
            is not None
        )

    def fulfill(
        self,
        session: Session,
        ctx: FulfilContext,
        *,
        now: datetime,
        description: str,
        txn_type: str,
    ) -> None:
        item = session.query(CatalogItem).filter(CatalogItem.id == ctx.item_id).first()
        if not item:
            return
        exists = (
            session.query(Purchase)
            .filter(Purchase.user_id == ctx.user_id, Purchase.catalog_id == ctx.item_id)
            .first()
        )
        if not exists:
            session.add(
                Purchase(
                    user_id=ctx.user_id,
                    catalog_id=ctx.item_id,
                    amount=ctx.total_amount,
                )
            )
        ent_type = "employee" if (item.artifact or "") == "employee_pack" else "mod"
        session.add(
            Entitlement(
                user_id=ctx.user_id,
                catalog_id=ctx.item_id,
                entitlement_type=ent_type,
                source_order_id=ctx.out_trade_no,
                metadata_json='{"source":"payment"}',
                granted_at=now,
                is_active=True,
            )
        )
        if ent_type == "employee":
            q = (
                session.query(Quota)
                .filter(Quota.user_id == ctx.user_id, Quota.quota_type == "employee_count")
                .first()
            )
            if not q:
                q = Quota(user_id=ctx.user_id, quota_type="employee_count", total=1, used=0)
            else:
                q.total = int(q.total or 0) + 1
            session.add(q)

        # 写入作者分润记录（仅当商品有关联作者且价格 > 0 时）
        if item.author_id and ctx.total_amount > 0:
            gross = float(ctx.total_amount)
            net = round(gross * (1.0 - _PLATFORM_FEE_RATE), 2)
            already = (
                session.query(AuthorEarning)
                .filter(AuthorEarning.order_id == ctx.out_trade_no)
                .first()
            )
            if not already:
                session.add(
                    AuthorEarning(
                        order_id=ctx.out_trade_no,
                        author_id=item.author_id,
                        item_id=item.id,
                        gross=gross,
                        platform_fee_rate=_PLATFORM_FEE_RATE,
                        net=net,
                        status="pending",
                    )
                )


# ---------------------------------------------------------------- plan


class PlanFulfilStrategy(FulfilStrategy):
    """套餐购买：撤销旧 active UserPlan、写新 UserPlan + Entitlement(plan) +
    重置配额，并按实付价取整元给钱包加 LLM 余额（与 java_payment_service 对齐）。
    """

    name = "plan"

    def description_and_txn_type(self, ctx: FulfilContext) -> tuple[str, str]:
        subject = ctx.order.get("subject", "")
        return f"套餐「{subject}」({ctx.out_trade_no})", "plan_purchase"

    def is_already_fulfilled(self, session: Session, ctx: FulfilContext) -> bool:
        return (
            session.query(Entitlement)
            .filter(
                Entitlement.source_order_id == ctx.out_trade_no,
                Entitlement.entitlement_type == "plan",
            )
            .first()
            is not None
        )

    def fulfill(
        self,
        session: Session,
        ctx: FulfilContext,
        *,
        now: datetime,
        description: str,
        txn_type: str,
    ) -> None:
        plan = session.query(PlanTemplate).filter(PlanTemplate.id == ctx.plan_id).first()
        if not plan:
            return

        session.query(UserPlan).filter(
            UserPlan.user_id == ctx.user_id, UserPlan.is_active == True  # noqa: E712
        ).update({"is_active": False})
        expires = now + timedelta(days=30)
        session.add(
            UserPlan(
                user_id=ctx.user_id,
                plan_id=plan.id,
                started_at=now,
                expires_at=expires,
                is_active=True,
            )
        )
        session.add(
            Entitlement(
                user_id=ctx.user_id,
                catalog_id=None,
                entitlement_type="plan",
                source_order_id=ctx.out_trade_no,
                metadata_json=f'{{"plan_id":"{plan.id}"}}',
                granted_at=now,
                expires_at=expires,
                is_active=True,
            )
        )

        for quota_type, total in _plan_quotas(plan).items():
            row = (
                session.query(Quota)
                .filter(Quota.user_id == ctx.user_id, Quota.quota_type == quota_type)
                .first()
            )
            if not row:
                row = Quota(user_id=ctx.user_id, quota_type=quota_type, total=total, used=0)
            else:
                row.total = total
                row.used = 0
            row.reset_at = now + timedelta(days=30)
            session.add(row)

        # 与 java_payment_service 对齐：按实付价取整元给钱包加 LLM 可用余额
        try:
            grant_yuan = int(
                Decimal(str(ctx.total_amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        except Exception:  # noqa: BLE001
            grant_yuan = int(round(float(ctx.total_amount or 0)))
        if grant_yuan > 0:
            w = (
                session.query(Wallet)
                .filter(Wallet.user_id == ctx.user_id)
                .with_for_update()
                .first()
            )
            if not w:
                w = Wallet(user_id=ctx.user_id, balance=0.0)
                session.add(w)
                session.flush()
            w.balance = float(w.balance or 0) + float(grant_yuan)
            w.updated_at = now
            session.add(
                Transaction(
                    user_id=ctx.user_id,
                    amount=float(grant_yuan),
                    txn_type="plan_membership_tokens",
                    status="completed",
                    description=f"会员随单：按实付价取整的 LLM 可用余额(元) ({ctx.out_trade_no})",
                )
            )


# ---------------------------------------------------------------- wallet / recharge


class WalletFulfilStrategy(FulfilStrategy):
    """钱包充值（kind="wallet"）和未分类支付宝入账（fallback）共享同一履约逻辑。"""

    name = "wallet"

    def description_and_txn_type(self, ctx: FulfilContext) -> tuple[str, str]:
        if ctx.kind == "wallet":
            return f"钱包充值 (订单 {ctx.out_trade_no})", "alipay_wallet"
        return f"支付宝入账 ({ctx.out_trade_no})", "alipay_recharge"

    def is_already_fulfilled(self, session: Session, ctx: FulfilContext) -> bool:
        txn_marker = f"({ctx.out_trade_no})"
        return (
            session.query(Transaction)
            .filter(
                Transaction.user_id == ctx.user_id,
                Transaction.description.contains(txn_marker),
            )
            .first()
            is not None
        )

    def fulfill(
        self,
        session: Session,
        ctx: FulfilContext,
        *,
        now: datetime,
        description: str,
        txn_type: str,
    ) -> None:
        from decimal import Decimal

        wallet = (
            session.query(Wallet).filter(Wallet.user_id == ctx.user_id).with_for_update().first()
        )
        if not wallet:
            wallet = Wallet(user_id=ctx.user_id, balance=Decimal("0"))
            session.add(wallet)
            session.flush()
        amount = Decimal(str(ctx.total_amount))
        wallet.balance += amount
        wallet.updated_at = now
        session.add(
            Transaction(
                user_id=ctx.user_id,
                amount=float(amount),
                txn_type=txn_type,
                status="completed",
                description=description,
            )
        )


# ---------------------------------------------------------------- factory


def select_strategy(ctx: FulfilContext) -> FulfilStrategy:
    """决定该订单走哪个策略。决策顺序与原 ``_fulfill_paid_order`` 完全一致。"""
    if ctx.item_id:
        return ItemFulfilStrategy()
    if ctx.plan_id or ctx.kind == "plan":
        return PlanFulfilStrategy()
    return WalletFulfilStrategy()


__all__ = [
    "FulfilContext",
    "FulfilStrategy",
    "ItemFulfilStrategy",
    "PlanFulfilStrategy",
    "WalletFulfilStrategy",
    "select_strategy",
]
