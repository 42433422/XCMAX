"""Auth-related persistence adapters (PAT 等)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from modstore_server.models import DeveloperToken


class SqlPatRepository:
    """DeveloperToken 表的轻量封装（与 :class:`AuthApplicationService` 并存）。"""

    def __init__(self, session: Session):
        self._session = session

    def revoke(self, *, user_id: int, token_id: int) -> bool:
        row = (
            self._session.query(DeveloperToken)
            .filter(DeveloperToken.id == token_id, DeveloperToken.user_id == user_id)
            .first()
        )
        if not row:
            return False
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
        return True


class InMemoryPatRepository:
    """测试用内存 PAT 吊销表。"""

    def __init__(self) -> None:
        self.revoked: set[tuple[int, int]] = set()

    def revoke(self, *, user_id: int, token_id: int) -> bool:
        self.revoked.add((user_id, token_id))
        return True


__all__ = ["InMemoryPatRepository", "SqlPatRepository"]
