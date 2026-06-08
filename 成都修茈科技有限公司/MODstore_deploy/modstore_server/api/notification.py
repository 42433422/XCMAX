"""HTTP layer for the notification bounded context.

The router consumes the :class:`NotificationApplicationService` only;
persistence and realtime push are wired through dependencies so a future
independent service can swap the SQLAlchemy adapter for a different
storage layer without touching this module.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user
from modstore_server.application.notification import NotificationApplicationService
from modstore_server.infrastructure.db import get_db
from modstore_server.infrastructure.notification_repository import (
    SqlNotificationRepository,
    WebsocketRealtimePusher,
)
from modstore_server.models import User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _service(db: Session = Depends(get_db)) -> NotificationApplicationService:
    return NotificationApplicationService(
        repository=SqlNotificationRepository(db),
        pusher=WebsocketRealtimePusher(),
    )


@router.get("/")
async def list_notifications(
    unread_only: bool = Query(False),
    kind: str = Query("", description="按类型筛选，空表示全部"),
    limit: int = Query(50, ge=1, le=200),
    service: NotificationApplicationService = Depends(_service),
    user: User = Depends(get_current_user),
):
    notifications = service.list_for_user(user.id, unread_only=unread_only, kind=kind, limit=limit)
    unread_count = service.count_unread(user.id)
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.notification_type.value,
                "title": n.title,
                "content": n.content,
                "data": n.data,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else "",
            }
            for n in notifications
        ],
        "unread_count": unread_count,
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    service: NotificationApplicationService = Depends(_service),
    user: User = Depends(get_current_user),
):
    if not service.mark_read(notification_id, user.id):
        raise HTTPException(404, "通知不存在")
    db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    db: Session = Depends(get_db),
    service: NotificationApplicationService = Depends(_service),
    user: User = Depends(get_current_user),
):
    updated = service.mark_all_read(user.id)
    db.commit()
    return {"ok": True, "updated": updated}


__all__ = ["router"]
