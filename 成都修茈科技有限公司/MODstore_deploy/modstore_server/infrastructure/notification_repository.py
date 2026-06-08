"""SQLAlchemy adapter implementing
:class:`modstore_server.domain.notification.ports.NotificationRepository`.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from modstore_server.domain.notification.types import Notification as DomainNotification
from modstore_server.domain.notification.types import (
    NotificationType,
    OutboundNotification,
)
from modstore_server.models import Notification as NotificationRow


def _row_to_domain(row: NotificationRow) -> DomainNotification:
    try:
        data = json.loads(row.data_json or "{}")
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    try:
        notif_type = NotificationType(row.kind)
    except ValueError:
        notif_type = NotificationType.SYSTEM
    return DomainNotification(
        id=int(row.id),
        user_id=int(row.user_id),
        notification_type=notif_type,
        title=str(row.title or ""),
        content=str(row.content or ""),
        data=data,
        is_read=bool(row.is_read),
        created_at=row.created_at,
    )


class SqlNotificationRepository:
    """Single SQLAlchemy session-scoped repository.

    Tests can substitute :class:`InMemoryNotificationRepository` (or any
    other adapter) without dragging the rest of the FastAPI stack.
    """

    def __init__(self, session: Session):
        self._session = session

    def add(self, outbound: OutboundNotification) -> DomainNotification:
        row = NotificationRow(
            user_id=outbound.user_id,
            kind=outbound.notification_type.value,
            title=outbound.title,
            content=outbound.content,
            data_json=json.dumps(outbound.data or {}, ensure_ascii=False),
            is_read=False,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _row_to_domain(row)

    def list_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[DomainNotification]:
        q = self._session.query(NotificationRow).filter(NotificationRow.user_id == user_id)
        if unread_only:
            q = q.filter(NotificationRow.is_read.is_(False))
        normalised_kind = (kind or "").strip()
        if normalised_kind and normalised_kind != "all":
            q = q.filter(NotificationRow.kind == normalised_kind)
        rows = q.order_by(NotificationRow.created_at.desc()).limit(limit).all()
        return [_row_to_domain(r) for r in rows]

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        row = (
            self._session.query(NotificationRow)
            .filter(
                NotificationRow.id == notification_id,
                NotificationRow.user_id == user_id,
            )
            .first()
        )
        if not row:
            return False
        row.is_read = True
        return True

    def mark_all_read(self, user_id: int) -> int:
        result = self._session.execute(
            update(NotificationRow)
            .where(
                NotificationRow.user_id == user_id,
                NotificationRow.is_read.is_(False),
            )
            .values(is_read=True)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    def count_unread(self, user_id: int) -> int:
        return (
            self._session.query(NotificationRow)
            .filter(
                NotificationRow.user_id == user_id,
                NotificationRow.is_read.is_(False),
            )
            .count()
        )


class InMemoryNotificationRepository:
    """Test double — keeps notifications in process memory.

    Behaves like the SQLAlchemy adapter for the documented contract; the
    notification service tests use it to keep the unit tests synchronous
    and DB-free.
    """

    def __init__(self) -> None:
        self._rows: list[DomainNotification] = []
        self._next_id = 1

    def add(self, outbound: OutboundNotification) -> DomainNotification:
        from datetime import datetime, timezone

        notif = DomainNotification(
            id=self._next_id,
            user_id=outbound.user_id,
            notification_type=outbound.notification_type,
            title=outbound.title,
            content=outbound.content,
            data=dict(outbound.data),
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
        self._next_id += 1
        self._rows.append(notif)
        return notif

    def list_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[DomainNotification]:
        rows = [r for r in self._rows if r.user_id == user_id]
        if unread_only:
            rows = [r for r in rows if not r.is_read]
        normalised_kind = (kind or "").strip()
        if normalised_kind and normalised_kind != "all":
            rows = [r for r in rows if r.notification_type.value == normalised_kind]
        rows.sort(key=lambda r: r.created_at or 0, reverse=True)
        return rows[:limit]

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        for idx, row in enumerate(self._rows):
            if row.id == notification_id and row.user_id == user_id:
                self._rows[idx] = DomainNotification(
                    id=row.id,
                    user_id=row.user_id,
                    notification_type=row.notification_type,
                    title=row.title,
                    content=row.content,
                    data=row.data,
                    is_read=True,
                    created_at=row.created_at,
                )
                return True
        return False

    def mark_all_read(self, user_id: int) -> int:
        count = 0
        for idx, row in enumerate(self._rows):
            if row.user_id == user_id and not row.is_read:
                self._rows[idx] = DomainNotification(
                    id=row.id,
                    user_id=row.user_id,
                    notification_type=row.notification_type,
                    title=row.title,
                    content=row.content,
                    data=row.data,
                    is_read=True,
                    created_at=row.created_at,
                )
                count += 1
        return count

    def count_unread(self, user_id: int) -> int:
        return sum(1 for r in self._rows if r.user_id == user_id and not r.is_read)


class NoopRealtimePusher:
    def push(self, user_id: int, payload: dict[str, Any]) -> None:  # pragma: no cover
        return None


class WebsocketRealtimePusher:
    """Adapter that bridges to ``realtime_ws.schedule_push_to_user``.

    Lives here so the application service does not depend on FastAPI / asyncio
    directly. If realtime_ws is unavailable (e.g. the notification service
    runs as its own process without the WebSocket listener), the push is
    silently skipped.
    """

    def push(self, user_id: int, payload: dict[str, Any]) -> None:
        try:
            from modstore_server.realtime_ws import schedule_push_to_user
        except Exception:
            return
        try:
            schedule_push_to_user(user_id, payload)
        except Exception:
            return


__all__ = [
    "InMemoryNotificationRepository",
    "NoopRealtimePusher",
    "SqlNotificationRepository",
    "WebsocketRealtimePusher",
]
