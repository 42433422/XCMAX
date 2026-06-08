"""发货单审单事件仓储。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.models.ai_business_evidence import ShipmentAuditEvent
from app.db.session import get_db


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ShipmentAuditRepository:
    def insert_event(
        self,
        *,
        decision: str,
        reason: str = "",
        shipment_id: int | None = None,
        ocr_confidence: float | None = None,
        source: str = "shipment",
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        row = ShipmentAuditEvent(
            created_at=created_at or _utcnow(),
            shipment_id=shipment_id,
            decision=decision,
            reason=(reason or "")[:512] or None,
            ocr_confidence=ocr_confidence,
            source=source,
        )
        with get_db() as db:
            db.add(row)
            db.flush()
            result = {
                "id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "shipment_id": row.shipment_id,
                "decision": row.decision,
                "reason": row.reason,
                "ocr_confidence": row.ocr_confidence,
                "source": row.source,
            }
            db.commit()
        return result

    def count_by_decision(self, *, month: str | None = None) -> dict[str, int]:
        counts: dict[str, int] = {"auto_approve": 0, "manual": 0, "ocr_failed": 0, "total": 0}
        with get_db() as db:
            q = db.query(ShipmentAuditEvent.decision)
            if month:
                q = q.filter(ShipmentAuditEvent.created_at.like(f"{month}%"))
            for (decision,) in q.all():
                key = str(decision or "")
                if key in counts:
                    counts[key] += 1
                counts["total"] += 1
        return counts


_shipment_audit_repository: ShipmentAuditRepository | None = None


def get_shipment_audit_repository() -> ShipmentAuditRepository:
    global _shipment_audit_repository
    if _shipment_audit_repository is None:
        _shipment_audit_repository = ShipmentAuditRepository()
    return _shipment_audit_repository
