"""模型支付订单：FHD PostgreSQL 权威存储。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def record_checkout_pending(
    *,
    out_trade_no: str,
    plan_id: str,
    amount_cents: int,
    amount_yuan: str,
    market_user_id: int = 0,
) -> None:
    from app.db.models.model_payment import ModelPaymentOrder
    from app.db.session import get_db

    now = _utc_now()
    with get_db() as db:
        existing = (
            db.query(ModelPaymentOrder)
            .filter(ModelPaymentOrder.out_trade_no == out_trade_no)
            .first()
        )
        if existing:
            existing.plan_id = plan_id
            existing.amount_cents = int(amount_cents)
            existing.amount_yuan = amount_yuan
            existing.status = "pending_payment"
            existing.updated_at = now
            if market_user_id > 0:
                existing.market_user_id = market_user_id
        else:
            db.add(
                ModelPaymentOrder(
                    out_trade_no=out_trade_no,
                    plan_id=plan_id,
                    amount_cents=int(amount_cents),
                    amount_yuan=amount_yuan,
                    status="pending_payment",
                    market_user_id=market_user_id if market_user_id > 0 else None,
                    notify_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()
    logger.info(
        "[model-payment] PG order pending out_trade_no=%s plan_id=%s", out_trade_no, plan_id
    )


def apply_notify_paid(
    *,
    out_trade_no: str,
    trade_no: str,
    total_amount: str,
) -> tuple[str, dict[str, Any] | None]:
    from app.db.models.model_payment import ModelPaymentEntitlement, ModelPaymentOrder
    from app.db.session import get_db

    with get_db() as db:
        row = (
            db.query(ModelPaymentOrder)
            .filter(ModelPaymentOrder.out_trade_no == out_trade_no)
            .first()
        )
        if not row:
            logger.warning("[model-payment] notify: 未知 out_trade_no=%s", out_trade_no)
            return "unknown_order", None

        try:
            expected_yuan = f"{int(row.amount_cents) / 100:.2f}"
        except (TypeError, ValueError):
            expected_yuan = str(row.amount_yuan or "")

        snap = row.to_snapshot()
        if total_amount != expected_yuan:
            logger.warning(
                "[model-payment] notify: 金额不一致 out_trade_no=%s expected=%s got=%s",
                out_trade_no,
                expected_yuan,
                total_amount,
            )
            return "amount_mismatch", snap

        now = _utc_now()
        if row.status == "paid":
            row.notify_count = int(row.notify_count or 0) + 1
            row.last_notify_at = now
            row.updated_at = now
            db.commit()
            return "already_paid", row.to_snapshot()

        row.notify_count = int(row.notify_count or 0) + 1
        row.last_notify_at = now
        row.status = "paid"
        row.trade_no = trade_no
        row.paid_at = now
        row.updated_at = now

        ent_snapshot: dict[str, Any] | None = None
        plan_id = str(row.plan_id or "")
        if plan_id:
            ent = db.get(ModelPaymentEntitlement, plan_id)
            if ent is None:
                ent = ModelPaymentEntitlement(
                    plan_id=plan_id,
                    purchase_count=0,
                )
                db.add(ent)
            ent.purchase_count = int(ent.purchase_count or 0) + 1
            if ent.first_paid_at is None:
                ent.first_paid_at = now
            ent.last_paid_at = now
            ent.last_out_trade_no = out_trade_no
            ent.last_trade_no = trade_no
            ent_snapshot = ent.to_dict()

        snap = row.to_snapshot()
        if ent_snapshot:
            snap["entitlement"] = ent_snapshot
        db.commit()
        logger.info(
            "[model-payment] PG order paid out_trade_no=%s trade_no=%s plan_id=%s",
            out_trade_no,
            trade_no,
            plan_id,
        )
        return "marked_paid", snap


def list_entitlements() -> list[dict[str, Any]]:
    from app.db.models.model_payment import ModelPaymentEntitlement
    from app.db.session import get_db

    with get_db() as db:
        rows = (
            db.query(ModelPaymentEntitlement)
            .order_by(ModelPaymentEntitlement.last_paid_at.desc())
            .all()
        )
        return [r.to_dict() for r in rows]


def get_entitlement(plan_id: str) -> dict[str, Any] | None:
    if not plan_id:
        return None
    from app.db.models.model_payment import ModelPaymentEntitlement
    from app.db.session import get_db

    with get_db() as db:
        row = db.get(ModelPaymentEntitlement, plan_id)
        return row.to_dict() if row else None


def get_order(out_trade_no: str) -> dict[str, Any] | None:
    if not out_trade_no:
        return None
    from app.db.models.model_payment import ModelPaymentOrder
    from app.db.session import get_db

    with get_db() as db:
        row = (
            db.query(ModelPaymentOrder)
            .filter(ModelPaymentOrder.out_trade_no == out_trade_no)
            .first()
        )
        return row.to_snapshot() if row else None


def update_order_status(
    *,
    out_trade_no: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    from app.db.models.model_payment import ModelPaymentOrder
    from app.db.session import get_db

    if not out_trade_no:
        return None
    now = _utc_now()
    with get_db() as db:
        row = (
            db.query(ModelPaymentOrder)
            .filter(ModelPaymentOrder.out_trade_no == out_trade_no)
            .first()
        )
        if not row:
            return None
        row.status = status
        row.updated_at = now
        if extra:
            if extra.get("refund_amount"):
                row.raw_notify = {**(row.raw_notify or {}), **extra}
        db.commit()
        return row.to_snapshot()


def count_orders() -> int:
    from app.db.models.model_payment import ModelPaymentOrder
    from app.db.session import get_db

    with get_db() as db:
        return db.query(ModelPaymentOrder).count()
