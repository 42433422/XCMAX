"""Ports (abstract interfaces) for the notification domain."""

from __future__ import annotations

from typing import Any, Iterable, Protocol

from .types import Notification, OutboundNotification


class NotificationRepository(Protocol):
    """Persistence port. Concrete impl lives in
    :mod:`modstore_server.infrastructure.notification`.
    """

    def add(self, outbound: OutboundNotification) -> Notification: ...

    def list_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[Notification]: ...

    def mark_read(self, notification_id: int, user_id: int) -> bool: ...

    def mark_all_read(self, user_id: int) -> int: ...

    def count_unread(self, user_id: int) -> int: ...


class RealtimePusher(Protocol):
    """Outbound port for realtime delivery (WebSocket / SSE / push)."""

    def push(self, user_id: int, payload: dict[str, Any]) -> None: ...


__all__ = ["NotificationRepository", "RealtimePusher"]


# ``Iterable`` only kept for re-export from this module if a future port needs it.
_ = Iterable  # noqa: F841 - intentional re-export hook
