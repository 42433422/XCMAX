"""站内通知 API。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/")
async def list_notifications(
    unread_only: bool = Query(False),
    kind: str = Query("", description="按类型筛选，空表示全部"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    k = (kind or "").strip()
    if k and k != "all":
        q = q.filter(Notification.kind == k)
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .count()
    )
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.kind,
                "title": n.title,
                "content": n.content,
                "data": json.loads(n.data_json or "{}"),
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else "",
            }
            for n in rows
        ],
        "unread_count": unread_count,
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if not notif:
        raise HTTPException(404, "通知不存在")
    notif.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(db: Session = Depends(get_db), user: User = Depends(_get_current_user)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"ok": True}
