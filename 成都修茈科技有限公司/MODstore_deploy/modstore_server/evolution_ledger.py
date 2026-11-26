# 成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_ledger.py
"""演化决策 ledger：append-only JSONL。

每个演化事件（signal_detected / proposal_generated / issue_opened / ... / pack_listed）
都写一行。owner 用 audit_evolution.py 查询。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

LEDGER_FILENAME = "evolution_decisions.jsonl"
_LEDGER_LOCK = threading.Lock()


def _ledger_path() -> Path:
    env_val = os.environ.get("MODSTORE_EVOLUTION_LEDGER_PATH", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root

    return (
        Path(_repo_root())
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "modstore_server"
        / "data"
        / LEDGER_FILENAME
    )


_AUDIT_EVENT_TYPE = "owner_audit_recorded"
_AUDIT_VERDICTS = frozenset({"approved", "rejected", "needs-review"})


def _journal_lock(path: Path) -> FileLock:
    """Serialize local processes on a stable sidecar, never the appended inode."""
    return FileLock(str(path.with_name(path.name + ".lock")), timeout=30)


def _read_records(path: Path) -> List[Dict[str, Any]]:
    """Read existing events without modifying historical lines."""
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _append_line(path: Path, record: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def append_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Append a decision. Event time is not a trusted arrival timestamp.

    event_id and recorded_at always come from this process; owner audit state
    cannot be supplied by a proposer. Human audit records have a separate API.
    """
    if not isinstance(event, dict) or event.get("event_type") == _AUDIT_EVENT_TYPE:
        raise ValueError("invalid_evolution_event")
    now = datetime.now(UTC).isoformat()
    record: Dict[str, Any] = dict(event)
    record["event_id"] = str(uuid.uuid4())
    record.setdefault("timestamp", now)  # Legacy callers may provide event time.
    record["recorded_at"] = now
    record["owner_audit"] = {"audited": False, "audited_at": None, "verdict": None}

    path = _ledger_path().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_LOCK, _journal_lock(path):
        _append_line(path, record)
    return record


def list_events(
    *,
    event_type: Optional[str] = None,
    final_status: Optional[str] = None,
    since_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Project owner audit revisions from the append-only journal.

    This is a local decision journal, NOT an independent business-growth proof.
    The underlying historical event bytes remain intact after an audit.
    """
    path = _ledger_path().resolve()
    if not path.is_file():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=since_days) if since_days is not None else None
    audit_by_target: Dict[str, Dict[str, Any]] = {}
    original_events = []
    with _LEDGER_LOCK, _journal_lock(path):
        records = _read_records(path)
    for row in records:
        if row.get("event_type") == _AUDIT_EVENT_TYPE:
            target = row.get("audit_target_event_id")
            verdict = row.get("audit_verdict")
            audited_at = row.get("audited_at")
            if (
                isinstance(target, str)
                and target
                and verdict in _AUDIT_VERDICTS
                and isinstance(audited_at, str)
                and audited_at
            ):
                audit_by_target[target] = {
                    "audited": True,
                    "audited_at": audited_at,
                    "verdict": verdict,
                }
            continue
        original_events.append(row)

    out: List[Dict[str, Any]] = []
    for row in original_events:
        if event_type and row.get("event_type") != event_type:
            continue
        if final_status and row.get("final_status") != final_status:
            continue
        if cutoff:
            try:
                ts = datetime.fromisoformat(row.get("timestamp", "").replace("Z", "+00:00"))
                if ts.tzinfo is None or ts < cutoff:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
        current = dict(row)
        event_id = row.get("event_id")
        audit = audit_by_target.get(event_id) if isinstance(event_id, str) else None
        if audit is not None:
            current["owner_audit"] = audit
        out.append(current)
    return out


def mark_audited(event_id: str, verdict: str) -> bool:
    """Append an audit decision, never rewrite the decision or a previous audit.

    Repeating the same decision is idempotent; a changed decision creates a new
    auditable revision. This API does not itself establish independent approval.
    """
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("invalid_evolution_event_id")
    if verdict not in _AUDIT_VERDICTS:
        raise ValueError("invalid_evolution_audit_verdict")
    path = _ledger_path().resolve()
    if not path.is_file():
        return False
    with _LEDGER_LOCK, _journal_lock(path):
        rows = _read_records(path)
        if not any(
            row.get("event_id") == event_id and row.get("event_type") != _AUDIT_EVENT_TYPE
            for row in rows
        ):
            return False
        previous = next(
            (
                row
                for row in reversed(rows)
                if row.get("event_type") == _AUDIT_EVENT_TYPE
                and row.get("audit_target_event_id") == event_id
            ),
            None,
        )
        if previous and previous.get("audit_verdict") == verdict:
            return True
        now = datetime.now(UTC).isoformat()
        audit = {
            "event_id": str(uuid.uuid4()),
            "event_type": _AUDIT_EVENT_TYPE,
            "timestamp": now,
            "recorded_at": now,
            "audit_target_event_id": event_id,
            "audit_verdict": verdict,
            "audited_at": now,
            "previous_audit_event_id": previous.get("event_id") if previous else None,
        }
        _append_line(path, audit)
    return True
