"""Domain-owned append-only persistence and reporting for autonomy decisions.

The SQLite table is the query SSOT.  A JSONL mirror is kept for operators and
for the MODstore daily digest, whose runtime may not share the FHD DB session.
Neither API exposes update/delete operations and SQLite triggers reject them.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = _FHD_ROOT / "metrics" / "autonomy-audit.sqlite3"
_DEFAULT_JSONL_PATH = _FHD_ROOT / "metrics" / "autonomy-audit-log.jsonl"
_LOCK = threading.RLock()
UTC = timezone.utc  # noqa: UP017 - shared module must import on Python 3.10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS autonomy_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL,
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    decision TEXT NOT NULL,
    approver TEXT,
    timestamp TEXT NOT NULL,
    outcome TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'decision',
    policy TEXT,
    rollback_path TEXT,
    source TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_autonomy_audit_timestamp
    ON autonomy_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_autonomy_audit_action_id
    ON autonomy_audit_log(action_id);
CREATE TRIGGER IF NOT EXISTS autonomy_audit_log_no_update
BEFORE UPDATE ON autonomy_audit_log
BEGIN
    SELECT RAISE(ABORT, 'autonomy_audit_log is append-only');
END;
CREATE TRIGGER IF NOT EXISTS autonomy_audit_log_no_delete
BEFORE DELETE ON autonomy_audit_log
BEGIN
    SELECT RAISE(ABORT, 'autonomy_audit_log is append-only');
END;
"""

_VETO_DECISIONS = frozenset(
    {
        "require_human",
        "pending_approval",
        "approval_requested",
        "rejected",
        "blocked",
        "prohibited",
        "cooldown",
    }
)

_SYNTHETIC_COHORT_SQL = """
(
    action_id LIKE 'e2e-%'
    OR action_id LIKE 'test-%'
    OR COALESCE(source, '') IN ('test', 'pytest')
    OR COALESCE(source, '') LIKE 'test.%'
)
"""


def _runtime_dir() -> Path:
    explicit = (os.environ.get("XCAGI_AUTONOMY_DATA_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    data_root = (os.environ.get("XCAGI_DATA_DIR") or "").strip()
    if data_root:
        return Path(data_root).expanduser() / "autonomy"
    return _FHD_ROOT / "metrics"


def _db_path() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_AUDIT_DB_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / _DEFAULT_DB_PATH.name


def _jsonl_path() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_AUDIT_LOG_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / _DEFAULT_JSONL_PATH.name


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def append_autonomy_audit(record: dict[str, Any]) -> dict[str, Any]:
    """Append one immutable audit event to SQLite and its JSONL mirror."""

    row: dict[str, Any] = {
        "action_id": str(record.get("action_id") or "system"),
        "action": str(record.get("action") or "unknown"),
        "risk_level": str(record.get("risk_level") or "BLOCKED").upper(),
        "decision": str(record.get("decision") or "blocked"),
        "approver": str(record.get("approver") or "") or None,
        "timestamp": str(record.get("timestamp") or _iso_now()),
        "outcome": str(record.get("outcome") or "decision_recorded"),
        "event_type": str(record.get("event_type") or "decision"),
        "policy": str(record.get("policy") or "") or None,
        "rollback_path": str(record.get("rollback_path") or "") or None,
        "source": str(record.get("source") or "") or None,
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
    }
    with _LOCK:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO autonomy_audit_log
                (action_id, action, risk_level, decision, approver, timestamp, outcome,
                 event_type, policy, rollback_path, source, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["action_id"],
                    row["action"],
                    row["risk_level"],
                    row["decision"],
                    row["approver"],
                    row["timestamp"],
                    row["outcome"],
                    row["event_type"],
                    row["policy"],
                    row["rollback_path"],
                    row["source"],
                    json.dumps(row["metadata"], ensure_ascii=False, default=str),
                ),
            )
            row["id"] = int(cur.lastrowid or 0)

        mirror = _jsonl_path()
        mirror.parent.mkdir(parents=True, exist_ok=True)
        with mirror.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    row["highlighted"] = row["decision"] in _VETO_DECISIONS
    return row


def list_autonomy_audit(
    *,
    limit: int = 100,
    risk_level: str | None = None,
    decision: str | None = None,
    veto_only: bool = False,
    since: str | None = None,
    action_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if risk_level:
        clauses.append("risk_level = ?")
        params.append(str(risk_level).upper())
    if decision:
        clauses.append("decision = ?")
        params.append(str(decision))
    if veto_only:
        marks = ",".join("?" for _ in _VETO_DECISIONS)
        clauses.append(f"decision IN ({marks})")
        params.extend(sorted(_VETO_DECISIONS))
    if since:
        clauses.append("timestamp >= ?")
        params.append(str(since))
    if action_id:
        clauses.append("action_id = ?")
        params.append(str(action_id))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit), 1000)))
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM autonomy_audit_log"
            + where
            + " ORDER BY timestamp DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    result: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            item["metadata"] = {}
            item.pop("metadata_json", None)
        item["highlighted"] = item.get("decision") in _VETO_DECISIONS
        result.append(item)
    return result


def latest_action_event(action: str, *, decisions: set[str] | None = None) -> dict[str, Any] | None:
    clauses = ["action = ?"]
    params: list[Any] = [str(action)]
    if decisions:
        marks = ",".join("?" for _ in decisions)
        clauses.append(f"decision IN ({marks})")
        params.extend(sorted(decisions))
    with _LOCK, _connect() as conn:
        raw = conn.execute(
            "SELECT * FROM autonomy_audit_log WHERE "
            + " AND ".join(clauses)
            + " ORDER BY timestamp DESC, id DESC LIMIT 1",
            params,
        ).fetchone()
    if raw is None:
        return None
    item = dict(raw)
    try:
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        item["metadata"] = {}
        item.pop("metadata_json", None)
    return item


def summarize_autonomy_audit(*, days: int = 1, include_synthetic: bool = False) -> dict[str, Any]:
    bounded_days = max(1, min(int(days), 3650))
    since = (datetime.now(UTC) - timedelta(days=bounded_days)).isoformat()
    cohort_sql = "1 = 1" if include_synthetic else f"NOT {_SYNTHETIC_COHORT_SQL}"
    with _LOCK, _connect() as conn:
        grouped = conn.execute(
            f"""
            SELECT decision, COUNT(*) AS n
            FROM autonomy_audit_log
            WHERE timestamp >= ? AND event_type IN ('decision', 'approval')
              AND {cohort_sql}
            GROUP BY decision
            """,
            (since,),
        ).fetchall()
        risks = conn.execute(
            f"""
            SELECT risk_level, COUNT(*) AS n
            FROM autonomy_audit_log
            WHERE timestamp >= ? AND event_type IN ('decision', 'approval')
              AND {cohort_sql}
            GROUP BY risk_level
            """,
            (since,),
        ).fetchall()
        unique_total = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT action_id)
                FROM autonomy_audit_log
                WHERE timestamp >= ? AND event_type = 'decision' AND action != '__configuration__'
                  AND {cohort_sql}
                """,
                (since,),
            ).fetchone()[0]
            or 0
        )
        marks = ",".join("?" for _ in _VETO_DECISIONS)
        unique_veto_query = (
            "SELECT COUNT(DISTINCT action_id) "
            "FROM autonomy_audit_log "
            "WHERE timestamp >= ? AND event_type IN ('decision', 'approval') "
            "AND "
            + cohort_sql
            + " AND (decision IN ("
            + marks
            + ") OR (decision = 'approved' AND risk_level IN ('MEDIUM', 'HIGH', 'BLOCKED') "
            "AND COALESCE(approver, '') != ''))"
        )
        unique_veto = int(
            conn.execute(
                unique_veto_query,
                (since, *sorted(_VETO_DECISIONS)),
            ).fetchone()[0]
            or 0
        )
        bounds = conn.execute(
            f"""
            SELECT MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts
            FROM autonomy_audit_log
            WHERE event_type = 'decision' AND action != '__configuration__'
              AND {cohort_sql}
            """
        ).fetchone()
        prohibited_miss_count = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT action_id)
                FROM autonomy_audit_log
                WHERE timestamp >= ? AND risk_level = 'BLOCKED'
                  AND {cohort_sql}
                  AND (
                    decision IN ('allow', 'auto_approve', 'approved', 'executed')
                    OR outcome IN ('allowed', 'executed')
                  )
                """,
                (since,),
            ).fetchone()[0]
            or 0
        )
        human_approval_count = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT action_id)
                FROM autonomy_audit_log
                WHERE timestamp >= ? AND event_type IN ('decision', 'approval')
                  AND {cohort_sql}
                  AND decision = 'approved'
                  AND risk_level IN ('MEDIUM', 'HIGH', 'BLOCKED')
                  AND COALESCE(approver, '') != ''
                """,
                (since,),
            ).fetchone()[0]
            or 0
        )
        prohibited_event_count = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT action_id)
                FROM autonomy_audit_log
                WHERE timestamp >= ? AND {cohort_sql}
                  AND risk_level = 'BLOCKED'
                  AND decision IN ('blocked', 'prohibited')
                """,
                (since,),
            ).fetchone()[0]
            or 0
        )
        synthetic_probe_count = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT action_id)
                FROM autonomy_audit_log
                WHERE timestamp >= ? AND {_SYNTHETIC_COHORT_SQL}
                  AND action != '__configuration__'
                """,
                (since,),
            ).fetchone()[0]
            or 0
        )
        synthetic_prohibited_event_count = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT action_id)
                FROM autonomy_audit_log
                WHERE timestamp >= ? AND {_SYNTHETIC_COHORT_SQL}
                  AND risk_level = 'BLOCKED'
                  AND decision IN ('blocked', 'prohibited')
                """,
                (since,),
            ).fetchone()[0]
            or 0
        )
    by_decision = {str(row["decision"]): int(row["n"]) for row in grouped}
    by_risk = {str(row["risk_level"]): int(row["n"]) for row in risks}
    total = unique_total
    veto_count = min(unique_veto, total)
    auto_pass_count = max(total - veto_count, 0)
    first_ts = str(bounds["first_ts"] or "") if bounds else ""
    last_ts = str(bounds["last_ts"] or "") if bounds else ""
    observed_days = 0.0
    if first_ts:
        try:
            observed_days = round(
                (datetime.now(UTC) - datetime.fromisoformat(first_ts)).total_seconds() / 86400,
                2,
            )
        except ValueError:
            observed_days = 0.0
    return {
        "window_days": bounded_days,
        "since": since,
        "total": total,
        "auto_pass_count": auto_pass_count,
        "veto_count": veto_count,
        "veto_rate": round((veto_count / total) * 100, 2) if total else 0.0,
        "auto_pass_rate": round((auto_pass_count / total) * 100, 2) if total else 0.0,
        "cohort": "all" if include_synthetic else "operational",
        "counting_rule": (
            "unique operational action_id; veto if any decision required human, was rejected, "
            "blocked, prohibited, cooldown, or records a non-LOW human approval; e2e/test probes "
            "are reported separately"
        ),
        "first_decision_at": first_ts or None,
        "last_decision_at": last_ts or None,
        "observed_days": observed_days,
        "by_decision": by_decision,
        "by_risk_level": by_risk,
        "target_veto_rate": {"min": 1.0, "max": 5.0},
        "human_approval_count": human_approval_count,
        "prohibited_event_count": prohibited_event_count,
        "prohibited_miss_count": prohibited_miss_count,
        "has_prohibited_miss": prohibited_miss_count > 0,
        "synthetic_probe_count": synthetic_probe_count,
        "synthetic_prohibited_event_count": synthetic_prohibited_event_count,
    }


def autonomy_daily_digest_html(*, days: int = 1) -> str:
    from app.domain.autonomy.operating_metrics import (
        autonomy_boundary_review_status,
        evaluate_autonomy_window,
    )

    summary = summarize_autonomy_audit(days=days)
    windows = [evaluate_autonomy_window(window) for window in (30, 90)]
    attention = {"failed", "needs_review", "needs_tuning"}
    tone = (
        "#b91c1c"
        if summary["veto_count"] or any(item.get("status") in attention for item in windows)
        else "#047857"
    )
    window_rows = "".join(
        '<div style="margin-top:4px;font-size:12px;color:#475569">'
        f"{item['window_days']}天 · {item['status']} · "
        f"已观察 {item['observed_days']}/{item['window_days']} 天 · "
        f"veto {item['veto_rate']}%"
        "</div>"
        for item in windows
    )
    boundary = windows[-1]["boundary_review"] if windows else autonomy_boundary_review_status()
    return (
        '<div style="padding:12px 16px;border:1px solid #e2e8f0;border-radius:10px">'
        "<strong>Autonomy 决策</strong>"
        f'<span style="margin-left:10px;color:{tone}">'
        f"{summary['total']} 次 · veto {summary['veto_rate']}% · "
        f"自动通过 {summary['auto_pass_rate']}%</span>"
        f"{window_rows}"
        '<div style="margin-top:4px;font-size:12px;color:#475569">'
        f"边界复盘 revision {boundary['boundary_revision']} · "
        f"下次 {boundary['next_review_at'] or 'unknown'} · {boundary['status']}"
        "</div></div>"
    )


__all__ = [
    "append_autonomy_audit",
    "autonomy_daily_digest_html",
    "latest_action_event",
    "list_autonomy_audit",
    "summarize_autonomy_audit",
]
