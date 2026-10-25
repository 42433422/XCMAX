# mypy: disable-error-code="assignment"
"""Admin-only outbox / DLQ helpers (replay & discard)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.eventing.db_outbox import drain
from modstore_server.infrastructure.db import get_db
from modstore_server.models import OutboxDeadLetter, OutboxEvent, User

router = APIRouter(prefix="/api/admin/events", tags=["admin-events"])


def assert_user_is_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")


@router.post("/replay")
def admin_replay_outbox(
    *,
    event_id: Optional[str] = None,
    event_name: Optional[str] = None,
    since_id: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """将匹配条件的 ``event_outbox`` 行重新标记为 pending 以便 dispatcher 重放。"""

    assert_user_is_admin(user)
    q = db.query(OutboxEvent)
    if event_id:
        q = q.filter(OutboxEvent.event_id == event_id.strip())
    if event_name:
        q = q.filter(OutboxEvent.event_name == event_name.strip())
    if since_id > 0:
        q = q.filter(OutboxEvent.id >= since_id)
    rows = q.order_by(OutboxEvent.id.asc()).limit(max(1, min(limit, 200))).all()
    n = 0
    for row in rows:
        row.status = "pending"
        row.last_error = ""
        n += 1
    db.commit()
    drain(limit=max(1, min(limit, 200)))
    return {"ok": True, "reset": n}


@router.get("/dlq")
def admin_list_dlq(
    *,
    limit: int = 50,
    include_resolved: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    assert_user_is_admin(user)
    query = db.query(OutboxDeadLetter)
    if not include_resolved:
        query = query.filter(OutboxDeadLetter.resolved_at.is_(None))
    rows = query.order_by(OutboxDeadLetter.id.desc()).limit(max(1, min(limit, 200))).all()
    unresolved_count = int(
        db.query(OutboxDeadLetter).filter(OutboxDeadLetter.resolved_at.is_(None)).count()
    )
    resolved_count = int(
        db.query(OutboxDeadLetter).filter(OutboxDeadLetter.resolved_at.is_not(None)).count()
    )
    return {
        "ok": True,
        "unresolved_count": unresolved_count,
        "resolved_count": resolved_count,
        "data": [
            {
                "id": r.id,
                "event_id": r.event_id,
                "event_name": r.event_name,
                "attempts": r.attempts,
                "last_error": r.last_error[:500] if r.last_error else "",
                "moved_at": r.moved_at.isoformat() if r.moved_at else "",
                "resolution_status": str(r.resolution_status or ""),
                "resolution_action": str(r.resolution_action or ""),
                "resolution_note": str(r.resolution_note or "")[:500],
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else "",
                "replay_outbox_id": r.replay_outbox_id,
            }
            for r in rows
        ],
    }


@router.post("/dlq/{row_id}/discard")
def admin_discard_dlq(
    row_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    assert_user_is_admin(user)
    row = db.query(OutboxDeadLetter).filter(OutboxDeadLetter.id == row_id).first()
    if not row:
        raise HTTPException(404, "DLQ 行不存在")
    # Keep the original row as immutable incident evidence.  "Discard" means
    # resolve without replay, not erase the audit record.
    row.resolution_status = "discarded"
    row.resolution_action = "admin_no_replay"
    row.resolution_note = "explicit administrator discard; audit row retained"
    row.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    row.last_reconciled_at = row.resolved_at
    db.commit()
    return {"ok": True, "retained": True, "resolution_status": "discarded"}


@router.post("/dlq/reconcile")
def admin_reconcile_dlq(
    *,
    limit: int = 200,
    user: User = Depends(_get_current_user),
):
    """Run the same audited reconciliation used by the 7x24 scheduler."""

    assert_user_is_admin(user)
    from modstore_server.dead_letter_reconciler import reconcile_dead_letters

    return reconcile_dead_letters(limit=max(1, min(limit, 1000)))


@router.get("/dlq/health")
def admin_dlq_health(user: User = Depends(_get_current_user)):
    assert_user_is_admin(user)
    from modstore_server.dead_letter_reconciler import dead_letter_health

    return dead_letter_health()
