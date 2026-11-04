# mypy: disable-error-code="arg-type"
"""官网联系表单 → FHD 客服 webhook 出站队列（失败重试 + 人工重放）。"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OUTBOX_FILENAME = "cs_webhook_outbox.sqlite3"
_LEGACY_OUTBOX_PATH = Path("/tmp/modstore_data") / _OUTBOX_FILENAME
_LEGACY_MIGRATION_BATCH_SIZE = 100
_MAX_STATUS_BUCKETS = 32


def _db_path() -> Path:
    """Resolve a durable outbox path when the runtime supplies one.

    ``/tmp`` remains a deliberately explicit development fallback only.  The
    scheduler process in production already owns ``MODSTORE_RUNTIME_DIR``;
    using it prevents customer leads from disappearing with tmp cleanup or a
    host restart.
    """

    explicit = (os.environ.get("MODSTORE_CS_WEBHOOK_OUTBOX_PATH") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
    else:
        root = (
            os.environ.get("MODSTORE_RUNTIME_DIR")
            or os.environ.get("MODSTORE_DATA_DIR")
            or "/tmp/modstore_data"
        )
        path = Path(root).expanduser() / _OUTBOX_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_db_path() -> Path:
    """Allow a one-time migration from the former tmp-backed outbox."""

    return Path(
        os.environ.get("MODSTORE_LEGACY_CS_WEBHOOK_OUTBOX_PATH", str(_LEGACY_OUTBOX_PATH))
    ).expanduser()


def _legacy_migration_enabled() -> bool:
    value = os.environ.get("MODSTORE_MIGRATE_LEGACY_CS_WEBHOOK_OUTBOX", "1")
    return value.strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def ensure_outbox_schema() -> None:
    with _connect() as conn:
        conn.executescript("""
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
            CREATE TABLE IF NOT EXISTS cs_webhook_outbox_migrations (
              source_path TEXT PRIMARY KEY,
              migrated_at TEXT NOT NULL,
              migrated_row_count INTEGER NOT NULL DEFAULT 0
            );
            """)
        conn.commit()
        _migrate_legacy_outbox(conn)
        conn.commit()


def _migrate_legacy_outbox(conn: sqlite3.Connection) -> None:
    """Preserve tmp-era rows in durable storage without replaying customer data.

    Imported pending rows are deliberately marked ``recovery_pending`` rather
    than ``pending``.  An operator must explicitly choose to replay them; the
    automatic retry job only handles newly-created ``pending`` deliveries.
    """

    target = _db_path()
    legacy = _legacy_db_path()
    if not _legacy_migration_enabled() or not legacy.exists():
        return
    try:
        if target.resolve() == legacy.resolve():
            return
    except OSError:
        return

    source_path = str(legacy.resolve())
    legacy_conn: sqlite3.Connection | None = None
    try:
        # The API process and the dedicated scheduler may start concurrently.
        # Serialize the marker check and copy so rows cannot be imported twice.
        conn.execute("BEGIN IMMEDIATE")
        already_migrated = conn.execute(
            "SELECT 1 FROM cs_webhook_outbox_migrations WHERE source_path = ?",
            (source_path,),
        ).fetchone()
        if already_migrated:
            conn.rollback()
            return
        legacy_conn = sqlite3.connect(f"file:{legacy.resolve()}?mode=ro", uri=True)
        table = legacy_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cs_webhook_outbox'"
        ).fetchone()
        if not table:
            return
        legacy_rows = legacy_conn.execute("""
            SELECT target_url, payload_json, headers_json, attempts, max_attempts,
                   last_error, status, landing_contact_id, market_user_id,
                   created_at, updated_at, next_retry_at
            FROM cs_webhook_outbox ORDER BY id ASC
            """)
        migrated = 0
        while batch := legacy_rows.fetchmany(_LEGACY_MIGRATION_BATCH_SIZE):
            for row in batch:
                source_status = str(row[6] or "pending")
                status = "recovery_pending" if source_status == "pending" else source_status
                conn.execute(
                    """
                    INSERT INTO cs_webhook_outbox (
                      target_url, payload_json, headers_json, attempts, max_attempts,
                      last_error, status, landing_contact_id, market_user_id,
                      created_at, updated_at, next_retry_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*row[:6], status, *row[7:]),
                )
                migrated += 1
        conn.execute(
            """
            INSERT INTO cs_webhook_outbox_migrations (
              source_path, migrated_at, migrated_row_count
            ) VALUES (?, ?, ?)
            """,
            (source_path, _now_iso(), migrated),
        )
        logger.warning(
            "migrated cs webhook outbox rows into durable storage: rows=%s status=recovery_pending",
            migrated,
        )
    except sqlite3.Error:
        conn.rollback()
        logger.exception("legacy cs webhook outbox migration failed")
    finally:
        if legacy_conn is not None:
            legacy_conn.close()


def outbox_status_summary() -> dict[str, Any]:
    """Return non-PII queue health suitable for a read-only admin endpoint."""

    ensure_outbox_schema()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM cs_webhook_outbox GROUP BY status LIMIT ?",
            (_MAX_STATUS_BUCKETS,),
        ).fetchall()
        oldest = conn.execute(
            "SELECT MIN(created_at) FROM cs_webhook_outbox WHERE status = 'pending'"
        ).fetchone()
    counts = {str(row[0]): int(row[1]) for row in rows}
    path = _db_path()
    return {
        "storage": "tmp_fallback" if path.parent == Path("/tmp/modstore_data") else "configured",
        "counts": counts,
        "pending_count": counts.get("pending", 0),
        "recovery_pending_count": counts.get("recovery_pending", 0),
        "delivery_unknown_count": counts.get("delivery_unknown", 0),
        "sending_count": counts.get("sending", 0),
        "oldest_pending_at": str(oldest[0] or ""),
    }


def retry_interval_seconds() -> int:
    try:
        configured = int(os.environ.get("MODSTORE_CS_WEBHOOK_OUTBOX_RETRY_SECONDS", "60"))
    except ValueError:
        configured = 60
    return max(30, min(configured, 3600))


def register_retry_job(scheduler: Any, *, track_job: Any | None = None) -> bool:
    """Register the autonomous retry loop on the process-wide scheduler."""

    enabled = os.environ.get("MODSTORE_CS_WEBHOOK_OUTBOX_RETRY_ENABLED", "1")
    if enabled.strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("cs webhook outbox retry disabled by configuration")
        return False

    from apscheduler.triggers.interval import IntervalTrigger

    def _run() -> dict[str, int]:
        result = process_pending_outbox(limit=20)
        if result["delivered"] or result["failed"] or result["skipped"]:
            logger.info("cs webhook outbox retry: %s", result)
        return result

    def _job() -> None:
        if track_job is None:
            _run()
        else:
            track_job("cs_webhook_outbox_retry", _run)

    scheduler.add_job(
        _job,
        IntervalTrigger(seconds=retry_interval_seconds()),
        id="cs_webhook_outbox_retry",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    return True


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
    """Require an explicit channel receipt; a redirect is not delivery."""
    try:
        payload = json.loads(row["payload_json"] or "{}")
        headers = json.loads(row["headers_json"] or "{}")
        resp = httpx.post(
            str(row["target_url"]),
            json=payload,
            headers=headers,
            timeout=12.0,
            follow_redirects=False,
        )
        if not 200 <= resp.status_code < 300:
            prefix = "delivery_outcome_unknown: " if resp.status_code >= 500 else ""
            return False, f"{prefix}HTTP {resp.status_code}"
        if "application/json" not in resp.headers.get("content-type", "").lower():
            return False, "delivery_outcome_unknown: missing JSON receipt"
        try:
            data = resp.json()
        except ValueError:
            return False, "delivery_outcome_unknown: invalid JSON receipt"
        if not isinstance(data, dict):
            return False, "delivery_outcome_unknown: invalid receipt shape"
        if data.get("success") is False or data.get("ok") is False:
            return False, "channel rejected delivery"
        if data.get("success") is True or data.get("ok") is True:
            return True, ""
        return False, "delivery_outcome_unknown: missing affirmative receipt"
    except (httpx.HTTPError, OSError):
        # The peer may have committed before the response was lost. Automatic
        # redelivery is unsafe without a verified idempotent receiver.
        return False, "delivery_outcome_unknown: transport interrupted"
    except (TypeError, ValueError):
        return False, "invalid persisted webhook payload"


def _expire_claims() -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE cs_webhook_outbox SET status='delivery_unknown',
               last_error='delivery_outcome_unknown: worker lease expired'
               WHERE status='sending' AND next_retry_at <= ?""",
            (_now_iso(),),
        )


def _claim_outbox_item(
    outbox_id: int, *, manual: bool = False, ignore_due: bool = False
) -> tuple[sqlite3.Row | None, str]:
    """Commit an exclusive attempt before network IO; never hold a DB lock in IO."""
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM cs_webhook_outbox WHERE id=?", (int(outbox_id),)
        ).fetchone()
        if row is None:
            return None, "not_found"
        status = str(row["status"])
        allowed = {"pending", "failed", "recovery_pending"} if manual else {"pending"}
        if status not in allowed:
            return None, status
        if not manual and int(row["attempts"]) >= int(row["max_attempts"]):
            conn.execute("UPDATE cs_webhook_outbox SET status='failed' WHERE id=?", (outbox_id,))
            return None, "failed"
        if not manual and not ignore_due and row["next_retry_at"] and row["next_retry_at"] > now:
            return None, "not_due"
        try:
            headers = json.loads(row["headers_json"] or "{}")
            if not isinstance(headers, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in headers.items()
            ):
                raise ValueError("invalid persisted headers")
        except (TypeError, ValueError):
            conn.execute(
                "UPDATE cs_webhook_outbox SET status='failed', last_error='invalid persisted headers' WHERE id=?",
                (int(outbox_id),),
            )
            return None, "failed"
        if not any(key.lower() == "idempotency-key" for key in headers):
            headers["Idempotency-Key"] = "xcagi-cs-" + uuid.uuid4().hex
        lease_until = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
        conn.execute(
            """UPDATE cs_webhook_outbox SET status='sending', attempts=attempts+1,
               headers_json=?, updated_at=?, next_retry_at=?, last_error='' WHERE id=?""",
            (json.dumps(headers, ensure_ascii=False), now, lease_until, int(outbox_id)),
        )
        claimed = conn.execute(
            "SELECT * FROM cs_webhook_outbox WHERE id=?", (int(outbox_id),)
        ).fetchone()
        conn.commit()
        return claimed, "sending"


def _attempt_delivery(
    outbox_id: int, *, manual: bool = False, ignore_due: bool = False
) -> dict[str, Any]:
    row, status = _claim_outbox_item(outbox_id, manual=manual, ignore_due=ignore_due)
    if row is None:
        return {
            "ok": status == "delivered",
            "error": "" if status == "delivered" else status,
            "status": status,
            "attempted": False,
        }
    ok, error = _deliver_row(row)
    attempts = int(row["attempts"])
    if ok:
        status = "delivered"
    elif error.startswith("delivery_outcome_unknown:"):
        status = "delivery_unknown"
    elif attempts >= int(row["max_attempts"]):
        status = "failed"
    else:
        status = "pending"
    delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
    retry_at = (
        (datetime.now(UTC) + timedelta(seconds=delay)).isoformat() if status == "pending" else None
    )
    with _connect() as conn:
        changed = conn.execute(
            """UPDATE cs_webhook_outbox SET status=?, last_error=?, updated_at=?, next_retry_at=?
               WHERE id=? AND status='sending' AND attempts=? AND updated_at=?""",
            (
                status,
                error,
                _now_iso(),
                retry_at,
                int(outbox_id),
                attempts,
                row["updated_at"],
            ),
        ).rowcount
    if changed != 1:
        return {
            "ok": False,
            "error": "delivery_outcome_unknown: claim lost",
            "status": "delivery_unknown",
            "attempted": True,
        }
    return {"ok": ok, "error": error, "status": status, "attempted": True}


def deliver_webhook_with_retry(
    *,
    target_url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    inline_attempts: int = 3,
) -> bool:
    """Persist before the first send; inline and background attempts share one key."""
    outbox_id = enqueue_webhook(target_url=target_url, payload=payload, headers=headers)
    attempts = max(1, min(int(inline_attempts), 5))
    for index in range(attempts):
        result = _attempt_delivery(outbox_id, ignore_due=True)
        if result["ok"]:
            return True
        if result["status"] != "pending":
            break
        if index < attempts - 1:
            time.sleep(0.5 * (2**index))
    logger.warning("cs webhook not confirmed; persisted outbox_id=%s", outbox_id)
    return False


def process_pending_outbox(*, limit: int = 20) -> dict[str, int]:
    ensure_outbox_schema()
    _expire_claims()
    stats = {"delivered": 0, "failed": 0, "skipped": 0}
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id FROM cs_webhook_outbox WHERE status='pending'
               AND (next_retry_at IS NULL OR next_retry_at <= ?) ORDER BY id ASC LIMIT ?""",
            (_now_iso(), max(0, int(limit))),
        ).fetchall()
    for row in rows:
        result = _attempt_delivery(int(row["id"]))
        if not result["attempted"]:
            stats["skipped"] += 1
            continue
        bucket = (
            "delivered"
            if result["ok"]
            else ("failed" if result["status"] in {"failed", "delivery_unknown"} else "skipped")
        )
        stats[bucket] += 1
    return stats


def replay_outbox_item(outbox_id: int) -> dict[str, Any]:
    """Replay a known failed attempt, not an in-flight or unknown delivery.

    Unknown outcomes require channel reconciliation; a second send cannot be
    made safe merely by choosing a new worker or by adding an HTTP header.
    """
    ensure_outbox_schema()
    _expire_claims()
    result = _attempt_delivery(int(outbox_id), manual=True)
    return {"ok": result["ok"], "error": result["error"]}


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
