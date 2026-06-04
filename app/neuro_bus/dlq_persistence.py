"""
NeuroBus DLQ SQLite 持久化（对齐 MODstore cs_webhook_outbox 模式）。

进程重启后可从磁盘恢复条目；HTTP 管理端点见 fastapi_integration.add_neurobus_routes。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.neuro_bus.dead_letter_queue import DeadLetterEntry, DeadLetterQueue

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS neuro_dlq (
  entry_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  error_message TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  handler_name TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_neuro_dlq_status ON neuro_dlq(status);
"""


class DLQSqliteStore:
    """死信 SQLite 存储。"""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def save_entry(self, entry: DeadLetterEntry) -> None:
        payload = {
            "event_id": entry.original_event.metadata.event_id,
            "event_type": entry.original_event.event_type,
            "payload": entry.original_event.payload,
        }
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO neuro_dlq (
                  entry_id, event_type, payload_json, reason, error_message,
                  retry_count, handler_name, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                  error_message=excluded.error_message,
                  retry_count=excluded.retry_count,
                  updated_at=excluded.updated_at
                """,
                (
                    entry.entry_id,
                    entry.original_event.event_type,
                    json.dumps(payload, ensure_ascii=False),
                    entry.reason.value,
                    entry.error_message,
                    entry.retry_count,
                    entry.handler_name,
                    now,
                    now,
                ),
            )
            conn.commit()

    def mark_replayed(self, entry_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE neuro_dlq SET status='replayed', updated_at=? WHERE entry_id=? AND status='pending'",
                (now, entry_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT entry_id, event_type, reason, error_message, retry_count,
                       handler_name, status, created_at, updated_at
                FROM neuro_dlq
                WHERE status='pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def resolve_dlq_db_path() -> Path:
    raw = os.environ.get("XCAGI_NEURO_DLQ_DB", "").strip()
    if raw:
        return Path(raw).expanduser()
    data = os.environ.get("XCAGI_DATA_DIR", "").strip()
    if data:
        return Path(data).expanduser() / "neuro_dlq.sqlite3"
    return Path("data") / "neuro_dlq.sqlite3"


def attach_dlq_persistence(dlq: DeadLetterQueue) -> DLQSqliteStore:
    """挂载 enqueue 持久化钩子。"""
    store = DLQSqliteStore(resolve_dlq_db_path())

    def _on_enqueue(entry: DeadLetterEntry) -> None:
        try:
            store.save_entry(entry)
        except Exception as exc:
            logger.error("DLQ persist failed for %s: %s", entry.entry_id, exc)

    dlq.on_alert(_on_enqueue)
    dlq._sqlite_store = store  # type: ignore[attr-defined]
    logger.info("NeuroBus DLQ persistence enabled at %s", store._db_path)
    return store
