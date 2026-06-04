"""签收记录 PostgreSQL 仓储。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.models.cs_delivery_signoff import CsDeliverySignoff


def ensure_schema() -> None:
    """PostgreSQL 表由 Alembic 管理；运行时仅校验可连库。"""
    from app.db.session import get_db

    with get_db() as db:
        db.query(CsDeliverySignoff).limit(1).all()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def insert_pending(
    *,
    opportunity_id: int,
    market_user_id: int,
    signed_by: str,
    notes: str,
    created_at: datetime | None = None,
) -> int:
    from app.db.session import get_db

    now = created_at or _utc_now()
    with get_db() as db:
        row = CsDeliverySignoff(
            opportunity_id=int(opportunity_id),
            market_user_id=int(market_user_id),
            status="pending",
            signed_by=(signed_by or "")[:128],
            signed_role="customer",
            notes=(notes or "")[:8000],
            attachment_url="",
            created_at=now,
            signed_at=None,
        )
        db.add(row)
        db.flush()
        return int(row.id)


def confirm_row(
    *,
    signoff_id: int,
    market_user_id: int,
    attachment_url: str,
    signed_at: datetime | None = None,
) -> bool:
    from app.db.session import get_db

    now = signed_at or _utc_now()
    with get_db() as db:
        row = (
            db.query(CsDeliverySignoff)
            .filter(
                CsDeliverySignoff.id == int(signoff_id),
                CsDeliverySignoff.market_user_id == int(market_user_id),
            )
            .first()
        )
        if not row:
            return False
        row.status = "signed"
        row.signed_at = now
        row.attachment_url = (attachment_url or "")[:512]
        db.flush()
        return True


def count_rows() -> int:
    from app.db.session import get_db

    with get_db() as db:
        return db.query(CsDeliverySignoff).count()


def list_for_market_user(market_user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    from app.db.session import get_db

    with get_db() as db:
        rows = (
            db.query(CsDeliverySignoff)
            .filter(CsDeliverySignoff.market_user_id == int(market_user_id))
            .order_by(CsDeliverySignoff.id.desc())
            .limit(limit)
            .all()
        )
        return [r.to_dict() for r in rows]
