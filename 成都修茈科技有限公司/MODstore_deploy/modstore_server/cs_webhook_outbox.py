"""官网联系表单 → FHD 客服 webhook 出站队列（失败重试 + 人工重放）。"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _db_path() -> Path:
    root = Path(os.environ.get("MODSTORE_DATA_DIR", "/tmp/modstore_data")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "cs_webhook_outbox.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_outbox_schema() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cs_webhook_outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              target_url TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              headers_json TEXT NOT NULL DEFAULT '{}',
              attempts INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL DEFAULT 5,
              last_error TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              landing_contact_id INTEGER,
              market_user_id INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              next_retry_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_cs_webhook_outbox_status
              ON cs_webhook_outbox(status, next_retry_at);
            """
        )
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue_webhook(
    *,
    target_url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    max_attempts: int = 5,
) -> int:
    ensure_outbox_schema()
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO cs_webhook_outbox (
              target_url, payload_json, headers_json, attempts, max_attempts,
              status, landing_contact_id, market_user_id, created_at, updated_at, next_retry_at
            ) VALUES (?, ?, ?, 0, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                target_url,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(headers or {}, ensure_ascii=False),
                int(max_attempts),
                int(payload.get("landing_contact_id") or 0) or None,
                int(payload.get("market_user_id") or 0) or None,
                now,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _deliver_row(row: sqlite3.Row) -> tuple[bool, str]:
    payload = json.loads(row["payload_json"] or "{}")
    headers = json.loads(row["headers_json"] or "{}")
    try:
        resp = httpx.post(
            str(row["target_url"]),
            json=payload,
            headers=headers,
            timeout=12.0,
        )
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if isinstance(data, dict) and data.get("success") is False:
            return False, str(data.get("error") or "success=false")[:300]
        return True, ""
    except Exception as exc:
        return False, str(exc)[:500]


def deliver_webhook_with_retry(
    *,
    target_url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    inline_attempts: int = 3,
) -> bool:
    """立即投递；失败则写入 outbox 并由 process_pending 重试。"""
    hdrs = dict(headers or {})
    last_err = ""
    for i in range(max(1, inline_attempts)):
        try:
            resp = httpx.post(target_url, json=payload, headers=hdrs, timeout=12.0)
            if resp.status_code < 400:
                data = (
                    resp.json()
                    if "application/json" in resp.headers.get("content-type", "")
                    else {}
                )
                if not isinstance(data, dict) or data.get("success") is not False:
                    return True
                last_err = str(data.get("error") or "success=false")
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_err = str(exc)
        if i < inline_attempts - 1:
            time.sleep(0.5 * (2**i))
    enqueue_webhook(target_url=target_url, payload=payload, headers=hdrs)
    logger.warning("cs webhook queued after inline failures: %s", last_err[:200])
    return False


def process_pending_outbox(*, limit: int = 20) -> dict[str, int]:
    ensure_outbox_schema()
    stats = {"delivered": 0, "failed": 0, "skipped": 0}
    now = _now_iso()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM cs_webhook_outbox
            WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY id ASC LIMIT ?
            """,
            (now, int(limit)),
        ).fetchall()
        for row in rows:
            ok, err = _deliver_row(row)
            attempts = int(row["attempts"]) + 1
            max_a = int(row["max_attempts"])
            if ok:
                conn.execute(
                    "UPDATE cs_webhook_outbox SET status='delivered', attempts=?, updated_at=?, last_error='' WHERE id=?",
                    (attempts, _now_iso(), int(row["id"])),
                )
                stats["delivered"] += 1
            elif attempts >= max_a:
                conn.execute(
                    "UPDATE cs_webhook_outbox SET status='failed', attempts=?, last_error=?, updated_at=? WHERE id=?",
                    (attempts, err, _now_iso(), int(row["id"])),
                )
                stats["failed"] += 1
            else:
                delay_sec = min(3600, 30 * (2 ** (attempts - 1)))
                next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).isoformat()
                conn.execute(
                    """
                    UPDATE cs_webhook_outbox SET attempts=?, last_error=?, updated_at=?,
                      next_retry_at=?
                    WHERE id=?
                    """,
                    (attempts, err, _now_iso(), next_at, int(row["id"])),
                )
                stats["skipped"] += 1
        conn.commit()
    return stats


def replay_outbox_item(outbox_id: int) -> dict[str, Any]:
    ensure_outbox_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cs_webhook_outbox WHERE id = ?", (int(outbox_id),)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        ok, err = _deliver_row(row)
        status = "delivered" if ok else "pending"
        conn.execute(
            """
            UPDATE cs_webhook_outbox SET status=?, attempts=attempts+1, last_error=?, updated_at=?
            WHERE id=?
            """,
            (status, err, _now_iso(), int(outbox_id)),
        )
        conn.commit()
    return {"ok": ok, "error": err}


def replay_by_landing_contact_id(landing_contact_id: int) -> dict[str, Any]:
    ensure_outbox_schema()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM cs_webhook_outbox
            WHERE landing_contact_id = ? ORDER BY id DESC LIMIT 1
            """,
            (int(landing_contact_id),),
        ).fetchone()
    if not row:
        return {"ok": False, "error": "no_outbox_row"}
    return replay_outbox_item(int(row["id"]))
