"""Admin-only outbox / DLQ helpers (replay & discard)."""

from __future__ import annotations

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
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    assert_user_is_admin(user)
    rows = (
        db.query(OutboxDeadLetter)
        .order_by(OutboxDeadLetter.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return {
        "ok": True,
        "data": [
            {
                "id": r.id,
                "event_id": r.event_id,
                "event_name": r.event_name,
                "attempts": r.attempts,
                "last_error": r.last_error[:500] if r.last_error else "",
                "moved_at": r.moved_at.isoformat() if r.moved_at else "",
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
    db.delete(row)
    db.commit()
    return {"ok": True}
