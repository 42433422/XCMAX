"""XCMAX admin sync inbox 应用层（routes 入口）。"""

from __future__ import annotations

from typing import Any

from app.services.admin_sync_service import (
    fetch_inbox_row,
    list_sync_conflicts,
    mark_inbox_skipped,
)

__all__ = [
    "fetch_inbox_row",
    "list_sync_conflicts",
    "mark_inbox_skipped",
]


def list_admin_sync_conflicts(*, limit: int = 50) -> list[dict[str, Any]]:
    return list_sync_conflicts(limit=limit)


def fetch_admin_inbox_row(inbox_id: int) -> dict[str, Any] | None:
    return fetch_inbox_row(inbox_id)


def mark_admin_inbox_skipped(inbox_id: int) -> None:
    mark_inbox_skipped(inbox_id)
