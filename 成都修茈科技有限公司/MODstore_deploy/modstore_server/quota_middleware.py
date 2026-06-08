"""配额检查与消耗工具。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import HTTPException

from modstore_server.eventing import new_event
from modstore_server.eventing.global_bus import neuro_bus
from modstore_server.models import Quota, Transaction, Wallet


def _month_reset() -> datetime:
    now = datetime.now(timezone.utc)
    return now + timedelta(days=30)


def _as_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_quota(session, user_id: int, quota_type: str) -> Optional[Quota]:
    row = (
        session.query(Quota)
        .filter(Quota.user_id == user_id, Quota.quota_type == quota_type)
        .first()
    )
    reset_at = _as_utc_aware(row.reset_at) if row else None
    if row and reset_at and reset_at <= datetime.now(timezone.utc):
        row.used = 0
        row.reset_at = _month_reset()
        session.add(row)
        session.commit()
    return row


def require_quota(session, user_id: int, quota_type: str, amount: int = 1) -> Quota:
    row = get_quota(session, user_id, quota_type)
    if not row:
        raise HTTPException(403, f"缺少配额: {quota_type}")
    if row.total >= 0 and row.used + amount > row.total:
        raise HTTPException(403, f"配额不足: {quota_type}")
    return row


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def require_llm_credit(session, user_id: int, amount: int = 1) -> str:
    """Allow LLM work with either monthly call quota or wallet balance."""
    row = get_quota(session, user_id, "llm_calls")
    if row:
        if row.total >= 0 and row.used + amount > row.total:
            raise HTTPException(403, "配额不足: llm_calls")
        return "quota"
    min_charge = _money(__import__("os").environ.get("COSER_DEFAULT_MIN_CHARGE", "0.02"))
    if (__import__("os").environ.get("PAYMENT_BACKEND") or "").strip().lower() == "java":
        return "java_wallet"
    wallet = session.query(Wallet).filter(Wallet.user_id == user_id).first()
    if wallet and _money(wallet.balance) >= min_charge:
        return "wallet"
    raise HTTPException(
        402, f"余额不足，需要 ¥{min_charge}，当前 ¥{wallet.balance if wallet else 0}"
    )


def consume_llm_credit(session, user_id: int, amount: int = 1) -> str:
    """Consume LLM quota when present; otherwise charge the wallet minimum."""
    row = get_quota(session, user_id, "llm_calls")
    if row:
        consume_quota(session, user_id, "llm_calls", amount)
        return "quota"
    min_charge = _money(__import__("os").environ.get("COSER_DEFAULT_MIN_CHARGE", "0.02"))
    if (__import__("os").environ.get("PAYMENT_BACKEND") or "").strip().lower() == "java":
        return "java_wallet"
    wallet = session.query(Wallet).filter(Wallet.user_id == user_id).with_for_update().first()
    if not wallet or _money(wallet.balance) < min_charge:
        raise HTTPException(
            402, f"余额不足，需要 ¥{min_charge}，当前 ¥{wallet.balance if wallet else 0}"
        )
    wallet.balance = float(_money(wallet.balance) - min_charge)
    wallet.updated_at = datetime.now(timezone.utc)
    session.add(wallet)
    session.add(
        Transaction(
            user_id=user_id,
            amount=-float(min_charge),
            txn_type="llm_wallet_charge",
            status="completed",
            description=f"AI 调用钱包扣费 ({amount} 次)",
        )
    )
    session.commit()
    return "wallet"


def consume_quota(session, user_id: int, quota_type: str, amount: int = 1) -> Quota:
    row = require_quota(session, user_id, quota_type, amount)
    row.used += amount
    if not row.reset_at:
        row.reset_at = _month_reset()
    session.add(row)
    session.commit()
    if quota_type.startswith("llm") or quota_type in {"tokens", "llm_tokens"}:
        neuro_bus.publish(
            new_event(
                "llm.quota_consumed",
                producer="quota",
                subject_id=str(user_id),
                payload={
                    "user_id": user_id,
                    "quota_type": quota_type,
                    "amount": amount,
                    "used": row.used,
                    "total": row.total,
                },
            )
        )
    return row
