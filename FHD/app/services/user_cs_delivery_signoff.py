"""交付签收（SQLite 侧存储）。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.user_cs_pipeline import _pipeline_roots


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> Path:
    root = _pipeline_roots()[0].parent / "user_cs_signoffs"
    root.mkdir(parents=True, exist_ok=True)
    return root / "signoffs.db"


@contextmanager
def _connect():
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_signoff_schema() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_signoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_user_id INTEGER NOT NULL,
                username TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                signed_by TEXT,
                notes TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            )
            """
        )


def signoff_backend_info() -> dict[str, Any]:
    ensure_signoff_schema()
    return {
        "backend": "sqlite",
        "path": str(_db_path()),
        "note": "桌面本地签收库",
    }


def create_signoff_request(
    market_user_id: int,
    *,
    username: str = "",
    signed_by: str = "",
    notes: str = "",
) -> dict[str, Any]:
    ensure_signoff_schema()
    now = _now_iso()
    payload = {"market_user_id": int(market_user_id), "username": username}
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO delivery_signoffs
            (market_user_id, username, status, signed_by, notes, payload_json, created_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """,
            (int(market_user_id), username, signed_by, notes, json.dumps(payload), now),
        )
        sid = int(cur.lastrowid)
    return {"signoff_id": sid, "status": "pending", "created_at": now}


def confirm_signoff(
    signoff_id: int,
    *,
    market_user_id: int,
    username: str = "",
) -> dict[str, Any]:
    ensure_signoff_schema()
    now = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM delivery_signoffs WHERE id = ? AND market_user_id = ?",
            (int(signoff_id), int(market_user_id)),
        ).fetchone()
        if not row:
            raise ValueError("签收记录不存在")
        conn.execute(
            "UPDATE delivery_signoffs SET status = 'confirmed', confirmed_at = ?, username = ? WHERE id = ?",
            (now, username, int(signoff_id)),
        )
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline, set_pipeline_stage

    doc = load_pipeline(int(market_user_id), username=username)
    doc = set_pipeline_stage(int(market_user_id), "delivered", username=username, source="signoff")
    delivery = dict(doc.get("delivery") or {})
    delivery["signoff_id"] = int(signoff_id)
    delivery["signoff_confirmed_at"] = now
    doc["delivery"] = delivery
    save_pipeline(doc)
    return {"signoff_id": int(signoff_id), "status": "confirmed", "confirmed_at": now}
