"""Durable loop ledger, memory files, baseline and exclusive process lease."""

from __future__ import annotations

import json
import os
import socket
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server import self_maintenance_runtime_evidence
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config


def ledger_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_LEDGER")
    return Path(raw) if raw else config._runtime_dir() / config.DEFAULT_LEDGER_NAME


def loop_memory_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_MEMORY")
    return Path(raw) if raw else config._runtime_dir() / config.DEFAULT_MEMORY_NAME


def governance_audit_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT")
    return (
        Path(raw)
        if raw
        else config._runtime_dir() / config.DEFAULT_GOVERNANCE_AUDIT_NAME
    )


def clean_baseline_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_CLEAN_BASELINE")
    if raw:
        return Path(raw)
    kb_root = os.environ.get("XCMAX_SELF_EVOLUTION_KB_ROOT") or os.environ.get(
        "XCMAX_KB_ROOT"
    )
    if kb_root:
        return (
            Path(kb_root).expanduser() / "metrics" / config.DEFAULT_CLEAN_BASELINE_NAME
        )
    return config._runtime_dir() / config.DEFAULT_CLEAN_BASELINE_NAME


def _default_clean_baseline() -> Dict[str, Any]:
    return {
        "baseline_id": "initial-current-known-failures-2026-06-18",
        "created_at": "2026-06-18T23:37:10+00:00",
        "notes": "Initial clean baseline from the first real report-only QA pass. QA must fail only for new failures beyond this baseline and should refresh allowed_failure_nodeids when a clean full-test collection is available.",
        "openapi": {
            "allowed_error_count": 0,
            "allowed_info_count": 49,
            "allowed_warn_count": 1819,
            "allowed_patterns": ["routes=1076 ops=1028", "warn=1819", "info=49"],
        },
        "pytest": {
            "allowed_error_count": 32,
            "allowed_failure_count": 80,
            "allowed_error_nodeids": [],
            "allowed_failure_nodeids": [],
            "allowed_failure_patterns": [
                "PermissionError",
                "sidebar_menu_manager.py",
                "outside this workspace",
            ],
            "source_run_id": "84c3aaf5-d3ff-420f-a31b-4680451cebbd",
        },
        "ruff": {
            "allowed_error_count": 63,
            "allowed_patterns": ["ruff check app", "63 errors"],
        },
        "schema_version": 1,
    }


def load_clean_baseline() -> Dict[str, Any]:
    path = clean_baseline_path()
    if not path.exists():
        return _default_clean_baseline()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _default_clean_baseline()
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to read clean baseline")
        return _default_clean_baseline()


def ensure_clean_baseline() -> Dict[str, Any]:
    path = clean_baseline_path()
    if path.exists():
        return load_clean_baseline()
    baseline = _default_clean_baseline()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return baseline


def _clean_baseline_context() -> str:
    return json.dumps(load_clean_baseline(), ensure_ascii=False, sort_keys=True)[:4000]


def _append_ledger(record: Dict[str, Any]) -> None:
    record = dict(record)
    run_id = str(record.get("run_id") or "").strip()
    if run_id:
        record.setdefault("correlation_id", run_id)
    record.setdefault("ledger_schema_version", 2)
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        if hasattr(os, "fchmod"):
            os.fchmod(fh.fileno(), 0o600)
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_ledger(
    limit: int = 100,
) -> List[Dict[str, Any]]:
    path = ledger_path()
    if not path.exists():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=limit if limit > 0 else None)
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if (
                        isinstance(row, dict)
                        and row.get("phase") == "remediation_attempt"
                    ):
                        continue
                    rows.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        config.logger.exception("failed to read self-maintenance ledger")
        return []
    return list(rows)[-limit:]


def _ledger_row_timestamp(
    row: Dict[str, Any],
) -> Optional[datetime]:
    """Return a normalized timestamp for one append-only ledger row.

    Step records use ``timestamp`` while start/terminal records use one of the
    ``*_at`` fields.  Keeping that compatibility here prevents an otherwise
    valid step from becoming timeless when it is projected into runtime
    evidence.
    """
    for key in (
        "timestamp",
        "created_at",
        "completed_at",
        "updated_at",
        "started_at",
        "verified_at",
        "deployed_at",
        "at",
    ):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _select_recent_milestone_rows(
    rows: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    window_days: int = config.DEFAULT_EVIDENCE_WINDOW_DAYS,
    run_limit: int = config.DEFAULT_EVIDENCE_RUN_LIMIT,
    row_limit: int = config.DEFAULT_EVIDENCE_ROW_LIMIT,
) -> List[Dict[str, Any]]:
    """Select coherent, time-bounded work evidence immune to heartbeat churn.

    The live feed remains intentionally small, but proof of a recent completed
    work cycle must not disappear merely because the scheduler emitted many
    idle heartbeats or policy skips.  Rows without a parseable timestamp are
    excluded, and evidence expires after ``window_days`` so an old success can
    never prove current autonomy forever.
    """
    current = (now or config._utc_now()).astimezone(timezone.utc)
    bounded_days = max(
        1, min(int(window_days or config.DEFAULT_EVIDENCE_WINDOW_DAYS), 90)
    )
    bounded_runs = max(1, min(int(run_limit or config.DEFAULT_EVIDENCE_RUN_LIMIT), 64))
    bounded_rows = max(1, min(int(row_limit or config.DEFAULT_EVIDENCE_ROW_LIMIT), 512))
    cutoff = current - timedelta(days=bounded_days)
    future_tolerance = current + timedelta(minutes=5)
    excluded_phases = {"heartbeat", "skip", "kb_salvage"}
    eligible: List[Tuple[Dict[str, Any], datetime]] = []
    latest_by_run: Dict[str, datetime] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        phase = str(row.get("phase") or "").strip().lower()
        if phase in excluded_phases:
            continue
        if not phase and (not row.get("event")) and (not row.get("event_type")):
            continue
        observed_at = _ledger_row_timestamp(row)
        if (
            observed_at is None
            or observed_at < cutoff
            or observed_at > future_tolerance
        ):
            continue
        eligible.append((row, observed_at))
        run_id = str(row.get("run_id") or "").strip()
        if run_id and observed_at > latest_by_run.get(run_id, cutoff):
            latest_by_run[run_id] = observed_at
    selected_run_ids = {
        run_id
        for (run_id, _) in sorted(latest_by_run.items(), key=lambda item: item[1])[
            -bounded_runs:
        ]
    }
    return self_maintenance_runtime_evidence.retain_completed_merge_runs(
        eligible,
        latest_by_run=latest_by_run,
        recent_run_ids=selected_run_ids,
        cutoff=cutoff,
        row_limit=bounded_rows,
    )


def loop_lease_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_LEASE_FILE")
    return Path(raw) if raw else config._runtime_dir() / config.DEFAULT_LOOP_LEASE_NAME


@contextmanager
def _exclusive_loop_lease():
    """Hold one OS-backed lease for the complete maintenance transaction."""
    path = loop_lease_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError):
            acquired = False
        if acquired:
            fh.seek(0)
            fh.truncate()
            fh.write(
                json.dumps(
                    {
                        "acquired_at": config._iso(config._utc_now()),
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            fh.flush()
        yield acquired
    finally:
        if acquired:
            try:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        fh.close()


def _load_loop_memory() -> Dict[str, Any]:
    path = loop_memory_path()
    if not path.exists():
        return {
            "closed_items": [],
            "open_items": [],
            "recent_runs": [],
            "run_count": 0,
            "updated_at": None,
        }
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to read self-maintenance memory")
        return {}


def _read_governance_audit(
    limit: int = 10,
) -> List[Dict[str, Any]]:
    path = governance_audit_path()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        config.logger.exception("failed to read self-maintenance governance audit")
        return []
    return rows[-limit:]


def _append_governance_audit(
    record: Dict[str, Any],
) -> Path:
    path = governance_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _write_loop_memory(memory: Dict[str, Any]) -> None:
    path = loop_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(memory, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)
