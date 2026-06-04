"""XCMAX 同步冲突 inbox 的 sqlite 访问（从路由层迁出）。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def sync_db_connection() -> Iterator[sqlite3.Connection]:
    from app.db.xcmax_sync import _resolve_db_path

    conn = sqlite3.connect(str(_resolve_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
    finally:
        conn.close()


def list_sync_conflicts(*, limit: int = 50) -> list[dict[str, Any]]:
    with sync_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, entity_type, entity_id, operation, payload_json, conflict_note, received_at "
            "FROM sync_inbox WHERE status='conflict' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    data: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except Exception:
            d["payload"] = {}
        data.append(d)
    return data


def fetch_inbox_row(inbox_id: int) -> dict[str, Any] | None:
    with sync_db_connection() as conn:
        row = conn.execute(
            "SELECT entity_type, entity_id, operation, payload_json FROM sync_inbox WHERE id=?",
            (inbox_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "operation": row["operation"],
        "payload": json.loads(row["payload_json"] or "{}"),
    }


def mark_inbox_skipped(inbox_id: int) -> None:
    with sync_db_connection() as conn:
        conn.execute("UPDATE sync_inbox SET status='skipped' WHERE id=?", (inbox_id,))
        conn.commit()
