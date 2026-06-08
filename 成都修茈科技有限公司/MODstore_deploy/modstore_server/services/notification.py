"""Notification service port.

When the Notification domain becomes a separate process, callers will keep
using ``get_default_notification_client()`` and the implementation will
swap to an HTTP adapter. Until then the in-process client wraps the
:class:`NotificationApplicationService` directly. This is the same shape
as the existing employee / LLM / workflow ports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import Any, Optional

from modstore_server.domain.notification.types import NotificationType


class NotificationClient(ABC):
    @abstractmethod
    def notify(
        self,
        *,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        content: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]: ...


class InProcessNotificationClient(NotificationClient):
    """Default in-process adapter.

    Each call opens a short-lived SQLAlchemy session so callers do not need
    to know about the persistence layer. The realtime push is best-effort
    and never raises.
    """

    def notify(
        self,
        *,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        content: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        from modstore_server.application.notification import (
            NotificationApplicationService,
        )
        from modstore_server.infrastructure.notification_repository import (
            SqlNotificationRepository,
            WebsocketRealtimePusher,
        )
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            service = NotificationApplicationService(
                repository=SqlNotificationRepository(session),
                pusher=WebsocketRealtimePusher(),
            )
            notif = service.create(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                content=content,
                data=data,
            )
            session.commit()
        return {
            "id": notif.id,
            "user_id": notif.user_id,
            "type": notif.notification_type.value,
            "title": notif.title,
        }


_LOCK = Lock()
_default: NotificationClient | None = None


def get_default_notification_client() -> NotificationClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessNotificationClient()
        return _default


def set_default_notification_client(client: Optional[NotificationClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "InProcessNotificationClient",
    "NotificationClient",
    "get_default_notification_client",
    "set_default_notification_client",
]
