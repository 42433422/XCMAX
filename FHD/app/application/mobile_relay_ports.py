"""Narrow call contracts for device pairing and the authenticated relay task queue."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

Payload = dict[str, Any]
Database = Callable[[], AbstractContextManager[Session]]
Schema = Callable[[Session], None]
Projection = Callable[[Payload], Payload]


class DesktopAuthentication(Protocol):
    def __call__(self, db: Session, *, relay_id: str, desktop_token: str) -> Payload | None: ...


class DesktopOwnership(Protocol):
    def __call__(self, *, user_id: int, relay_id: str) -> bool: ...


class TaskReader(Protocol):
    def __call__(self, *, user_id: int, task_id: str) -> Payload | None: ...


@dataclass(frozen=True)
class PairingPorts:
    database: Database
    ensure_tables: Schema
    fresh_pairing_code: Callable[[Session], str]
    desktop_for_token: DesktopAuthentication
    public_desktop: Projection


@dataclass(frozen=True)
class TaskPorts:
    database: Database
    ensure_tables: Schema
    desktop_belongs_to_user: DesktopOwnership
    desktop_for_token: DesktopAuthentication
    public_desktop: Projection
    notify_task_creator: Callable[[Payload], None]
    get_task: TaskReader
