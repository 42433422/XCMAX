"""合同到期推送记录仓储。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.models.ai_business_evidence import ContractExpiryNotification
from app.db.session import get_db


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ContractExpiryNotificationRepository:
    def was_recently_notified(
        self,
        *,
        market_user_id: int,
        end_date: str,
        within_hours: int = 24,
    ) -> bool:
        cutoff = _utcnow() - timedelta(hours=max(1, within_hours))
        with get_db() as db:
            row = (
                db.query(ContractExpiryNotification)
                .filter(
                    ContractExpiryNotification.market_user_id == market_user_id,
                    ContractExpiryNotification.end_date == end_date,
                    ContractExpiryNotification.scheduled_at >= cutoff,
                    ContractExpiryNotification.push_status == "success",
                )
                .first()
            )
            return row is not None

    def insert_notification(
        self,
        *,
        market_user_id: int,
        end_date: str,
        push_status: str,
        push_channel: str | None = None,
        error_message: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> dict[str, Any]:
        row = ContractExpiryNotification(
            market_user_id=market_user_id,
            end_date=end_date,
            scheduled_at=scheduled_at or _utcnow(),
            push_status=push_status,
            push_channel=push_channel,
            error_message=(error_message or "")[:2000] or None,
        )
        with get_db() as db:
            db.add(row)
            db.flush()
            result = {
                "id": row.id,
                "market_user_id": row.market_user_id,
                "end_date": row.end_date,
                "push_status": row.push_status,
                "push_channel": row.push_channel,
            }
            db.commit()
        return result

    def count_by_status(self, *, month: str | None = None) -> dict[str, int]:
        counts: dict[str, int] = {"success": 0, "failed": 0, "skipped": 0, "total": 0}
        with get_db() as db:
            q = db.query(ContractExpiryNotification.push_status)
            if month:
                q = q.filter(ContractExpiryNotification.scheduled_at.like(f"{month}%"))
            for (push_status,) in q.all():
                key = str(push_status or "")
                if key in counts:
                    counts[key] += 1
                counts["total"] += 1
        return counts


_contract_expiry_notification_repository: ContractExpiryNotificationRepository | None = None


def get_contract_expiry_notification_repository() -> ContractExpiryNotificationRepository:
    global _contract_expiry_notification_repository
    if _contract_expiry_notification_repository is None:
        _contract_expiry_notification_repository = ContractExpiryNotificationRepository()
    return _contract_expiry_notification_repository
