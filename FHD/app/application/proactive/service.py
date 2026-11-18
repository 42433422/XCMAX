"""Tenant-scoped event storage and optional channel delivery.

SQLite supplies durable transactions; the existing process lock serializes
channel attempts. A stored row is not an in-app notification receipt. Failed
channels can retry; interrupted attempts stay uncertain until reconciled.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.utils.operational_errors import BOUNDARY_ERRORS
from app.utils.process_lock import exclusive_file_lock

__all__ = [
    "ProactiveEvent",
    "ProactiveService",
    "apprise_sender",
    "in_app_sender",
    "proactive_root",
]

logger = logging.getLogger(__name__)
DEDUPE_WINDOW_SECONDS = 24 * 60 * 60
Sender = Callable[["ProactiveEvent"], bool | None]


@dataclass(frozen=True)
class ProactiveEvent:
    kind: str
    title: str
    detail: str = ""
    fingerprint: str = ""
    user_ids: tuple[int, ...] = ()
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "user_ids": list(self.user_ids),
            "created_at": self.created_at,
        }


def proactive_root() -> Path:
    base = os.environ.get("MODSTORE_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "proactive"


def in_app_sender(event: ProactiveEvent) -> bool:
    """Report an actual socket send to online recipients in this process only."""
    if not event.user_ids:
        return False
    from app.infrastructure.im.ws_hub import im_ws_hub
    from app.utils.async_runtime import run_coroutine_sync

    return bool(
        run_coroutine_sync(
            im_ws_hub.broadcast_members(
                list(event.user_ids), {"type": "proactive", **event.as_dict()}
            )
        )
    )


def apprise_sender(urls: list[str] | None = None) -> Sender:
    """Deliver only to explicitly configured Apprise targets; False means skipped."""

    def send(event: ProactiveEvent) -> bool:
        configured = urls
        if configured is None:
            raw = str(os.environ.get("PROACTIVE_APPRISE_URLS") or "")
            configured = [item.strip() for item in raw.split(",") if item.strip()]
        if not configured:
            return False
        apprise = importlib.import_module("apprise")
        client = apprise.Apprise()
        for url in configured:
            if not client.add(url):
                raise ValueError("Apprise 渠道配置无效")
        if not client.notify(body=event.detail or event.title, title=event.title):
            raise RuntimeError("Apprise 投递失败")
        return True

    return send


class ProactiveService:
    def __init__(
        self,
        root: Path | None = None,
        *,
        tenant_id: str,
        senders: list[Sender] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("主动提醒需要明确租户")
        self._root = (root or proactive_root()) / hashlib.sha256(
            tenant_id.strip().encode()
        ).hexdigest()
        self._senders = list(senders) if senders is not None else []
        self._clock = clock

    def publish(self, event: ProactiveEvent) -> dict[str, Any]:
        """Persist once per recipient scope, then retry only unfinished channels."""
        if any(type(user_id) is not int or user_id < 1 for user_id in event.user_ids):
            raise ValueError("接收人必须为有效账号编号")
        fingerprint = event.fingerprint or json.dumps([event.kind, event.title, event.detail])
        key = hashlib.sha256(
            json.dumps([sorted(set(event.user_ids)), fingerprint]).encode()
        ).hexdigest()
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with exclusive_file_lock(
            self._root / ".publish.lock", blocking=True, timeout=30, reject_symlink=True
        ):
            with closing(sqlite3.connect(self._root / "outbox.sqlite3")) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, fingerprint TEXT, at REAL, payload TEXT)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS deliveries (event_id TEXT, channel TEXT, status TEXT, PRIMARY KEY(event_id, channel))"
                )
                row = db.execute(
                    "SELECT id, payload FROM events WHERE fingerprint=? AND at>? ORDER BY at DESC LIMIT 1",
                    (key, self._clock() - DEDUPE_WINDOW_SECONDS),
                ).fetchone()
                deduped = row is not None
                if row:
                    event = ProactiveEvent(**json.loads(row[1]), fingerprint=fingerprint)
                else:
                    db.execute(
                        "INSERT INTO events VALUES (?, ?, ?, ?)",
                        (
                            event.event_id,
                            key,
                            self._clock(),
                            json.dumps(event.as_dict(), ensure_ascii=False),
                        ),
                    )
                    db.commit()
                delivered: list[str] = []
                skipped: list[str] = []
                errors: list[str] = []
                for index, sender in enumerate(self._senders):
                    name = getattr(sender, "__name__", "channel")
                    channel = f"{index}:{name}"
                    previous = db.execute(
                        "SELECT status FROM deliveries WHERE event_id=? AND channel=?",
                        (event.event_id, channel),
                    ).fetchone()
                    if previous and previous[0] == "delivered":
                        delivered.append(name)
                        continue
                    if previous and previous[0] == "inflight":
                        errors.append(f"{name}: 上次投递结果未知，需核对后重试")
                        continue
                    self._record_delivery(db, event.event_id, channel, "inflight")
                    try:
                        status = "skipped" if sender(event) is False else "delivered"
                        (skipped if status == "skipped" else delivered).append(name)
                    except BOUNDARY_ERRORS as exc:
                        logger.warning("Proactive channel delivery failed", exc_info=True)
                        status = "failed"
                        errors.append(f"{name}: {type(exc).__name__}")
                    self._record_delivery(db, event.event_id, channel, status)
                return {
                    "ok": not errors,
                    "stored": True,
                    "deduped": deduped,
                    "fingerprint": fingerprint,
                    "event_id": event.event_id,
                    "delivered": delivered,
                    "skipped": skipped,
                    "errors": errors,
                }

    @staticmethod
    def _record_delivery(db: sqlite3.Connection, event_id: str, channel: str, status: str) -> None:
        db.execute(
            "INSERT OR REPLACE INTO deliveries VALUES (?, ?, ?)", (event_id, channel, status)
        )
        db.commit()

    def recent(self, limit: int = 20, *, user_id: int | None = None) -> list[dict[str, Any]]:
        """Read bounded records in this tenant; targeted rows require their recipient."""
        path = self._root / "outbox.sqlite3"
        if not path.exists():
            return []
        limit = min(100, max(1, int(limit)))
        with closing(sqlite3.connect(path)) as db:
            rows = db.execute(
                "SELECT payload FROM events WHERE json_array_length(json_extract(payload, '$.user_ids')) = 0 OR EXISTS (SELECT 1 FROM json_each(events.payload, '$.user_ids') WHERE value=?) ORDER BY at DESC, rowid DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]
