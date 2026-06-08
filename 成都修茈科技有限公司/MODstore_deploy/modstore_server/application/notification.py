"""Notification application service.

Use cases the rest of the system can call. The service depends on the
domain ports, not on SQLAlchemy or FastAPI; the FastAPI router and the
:mod:`eventing.subscribers` module wire concrete adapters into it.
"""

from __future__ import annotations

import logging
from typing import Any

from modstore_server.domain.notification.ports import (
    NotificationRepository,
    RealtimePusher,
)
from modstore_server.domain.notification.types import (
    Notification,
    NotificationType,
    OutboundNotification,
)

logger = logging.getLogger(__name__)


class NotificationApplicationService:
    """Application boundary owning notification use cases.

    The service swallows realtime-push failures because the persisted row
    is the source of truth — a missed websocket frame must never roll back
    a user-visible notification.
    """

    def __init__(self, repository: NotificationRepository, pusher: RealtimePusher):
        self._repo = repository
        self._pusher = pusher

    # — Commands —

    def create(
        self,
        *,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        content: str,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        outbound = OutboundNotification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            content=content,
            data=dict(data or {}),
        )
        notif = self._repo.add(outbound)
        try:
            self._pusher.push(
                user_id,
                {
                    "type": "notification",
                    "id": notif.id,
                    "kind": notif.notification_type.value,
                    "title": notif.title,
                },
            )
        except Exception:
            logger.warning(
                "realtime push failed for notification id=%s user=%s",
                notif.id,
                user_id,
                exc_info=True,
            )
        return notif

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        return self._repo.mark_read(notification_id, user_id)

    def mark_all_read(self, user_id: int) -> int:
        return self._repo.mark_all_read(user_id)

    # — Queries —

    def list_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[Notification]:
        return self._repo.list_for_user(user_id, unread_only=unread_only, kind=kind, limit=limit)

    def count_unread(self, user_id: int) -> int:
        return self._repo.count_unread(user_id)


__all__ = ["NotificationApplicationService"]
