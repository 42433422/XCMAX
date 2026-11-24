"""Durable loop ledger, memory files, baseline and exclusive process lease."""

from __future__ import annotations

import json
import os
import socket
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

from modstore_server import self_maintenance_runtime_evidence
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config


def _json_fallback(value: Any) -> Any:
    """Keep a ledger write alive when a value is not JSON.

    Modules are recorded by import name only. Other exotic objects become a
    type token. Raw ``repr`` is intentionally not used: exception messages and
    module paths can carry secrets or host layout.
    """

    if isinstance(value, ModuleType):
        name = str(getattr(value, "__name__", "") or "")
        if name and all(part.isidentifier() for part in name.split(".")):
            return f"module:{name}"
        return "module:redacted"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return list(value)
    if isinstance(value, (bytes, bytearray)):
        return f"bytes:{len(value)}"
    if isinstance(value, BaseException):
        return f"exception:{type(value).__name__}"
    type_name = type(value).__name__
    if type_name.isidentifier():
        return f"non_json:{type_name}"
    return "non_json:value"


def _dumps_ledger(payload: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=indent,
        default=_json_fallback,
    )


def ledger_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_LEDGER")
    return Path(raw) if raw else config._runtime_dir() / config.DEFAULT_LEDGER_NAME


def loop_memory_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_MEMORY")
    return Path(raw) if raw else config._runtime_dir() / config.DEFAULT_MEMORY_NAME


def governance_audit_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT")
    return Path(raw) if raw else config._runtime_dir() / config.DEFAULT_GOVERNANCE_AUDIT_NAME


def clean_baseline_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_CLEAN_BASELINE")
    if raw:
        return Path(raw)
    kb_root = os.environ.get("XCMAX_SELF_EVOLUTION_KB_ROOT") or os.environ.get("XCMAX_KB_ROOT")
    if kb_root:
        return Path(kb_root).expanduser() / "metrics" / config.DEFAULT_CLEAN_BASELINE_NAME
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
    durable_outcome = record.get("phase") == "complete" and isinstance(
        record.get("policy_decision"), dict
    )
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        if hasattr(os, "fchmod"):
            os.fchmod(fh.fileno(), 0o600)
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(_dumps_ledger(record) + "\n")
        if durable_outcome or record.get("event") in {
            "deploy_dispatch_intent",
            "deploy_dispatch_bound",
            "post_deploy_verified",
            "merge_feedback_reconciled",
            "delivery_reconciled",
        }:
            fh.flush()
            os.fsync(fh.fileno())
    if (
        durable_outcome
        or record.get("event")
        in {
            "deploy_dispatch_intent",
            "post_deploy_verified",
            "merge_feedback_reconciled",
            "delivery_reconciled",
        }
    ) and os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


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
                    if isinstance(row, dict) and row.get("phase") == "remediation_attempt":
                        continue
                    rows.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        config.logger.exception("failed to read self-maintenance ledger")
        return []
    return list(rows)[-limit:]


def _has_recorded_outcome(final: Dict[str, Any]) -> bool:
    """Read a lost append acknowledgement without double-counting completion."""
    path = ledger_path()
    if not path.exists():
        return False
    expected = json.loads(_dumps_ledger(final))
    found = False
    with path.open("r", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        except ImportError:
            pass
        while raw := handle.readline(2 * 1024 * 1024 + 1):
            if len(raw) > 2 * 1024 * 1024 or not raw.endswith("\n"):
                raise ValueError("outcome_ledger_incomplete")
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("outcome_ledger_invalid")
            if row.get("phase") != "complete" or row.get("run_id") != final.get("run_id"):
                continue
            observed = {
                key: value
                for key, value in row.items()
                if key not in {"correlation_id", "ledger_schema_version"}
            }
            if observed != expected:
                raise ValueError("outcome_ledger_identity_conflict")
            found = True
    return found


DELIVERY_RECOVERY_ROWS = 256
DELIVERY_RECOVERY_BYTES = 2 * 1024 * 1024
DELIVERY_RECOVERY_RUNS = 20
_DELIVERY_BINDING = ("run_id", "para_task_id", "branch", "branch_head_sha")


def _read_delivery_row(handle: Any, end: int, budget: dict[str, int]) -> dict[str, Any] | None:
    """Read one complete snapshot row without unbounded line or page allocation."""
    if not budget["rows"] or not budget["bytes"] or handle.tell() >= end:
        return None
    start = handle.tell()
    raw = handle.readline(min(end - start, budget["bytes"]))
    if not raw.endswith(b"\n"):
        handle.seek(start)
        if len(raw) == budget["bytes"] and budget["bytes"] < DELIVERY_RECOVERY_BYTES:
            budget["bytes"] = 0
            return None
        raise ValueError("delivery recovery ledger has an incomplete or oversized row")
    budget["rows"] -= 1
    budget["bytes"] -= len(raw)
    row = json.loads(raw)
    if not isinstance(row, dict):
        raise TypeError("delivery recovery ledger row is not an object")
    return row


def _pending_delivery_page(
    cursor: Any = None, *, recent_runs: Any = None, include_terminal: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Discover and verify a bounded page against the original append-only ledger.

    Verification has its own durable cursor; it never rescans an entire ledger
    in one tick. Only a page checked through the current EOF becomes actionable.
    Every finished page advances discovery even when its tasks remain unknown.
    """
    recent = list(
        {
            str(run["run_id"]): run
            for run in recent_runs or []
            if isinstance(run, dict)
            and run.get("run_id")
            and run.get("status")
            in {"completed_merge_requested", "completed_merged", "completed_merge_failed"}
        }.values()
    )[-DELIVERY_RECOVERY_RUNS:]
    path = ledger_path()
    if not path.exists():
        return [dict(run) for run in recent], {}
    with path.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        identity = [stat.st_dev, stat.st_ino]
        state = deepcopy(cursor) if isinstance(cursor, dict) else {}
        if state.get("file") != identity or stat.st_size < max(
            int(state.get(key) or 0) for key in ("end", "offset", "verify_offset")
        ):
            state = {"file": identity, "offset": 0, "end": stat.st_size}
        if not state.get("end"):
            state["end"] = stat.st_size
        if state["end"]:
            handle.seek(state["end"] - 1)
            if handle.read(1) != b"\n":
                # A snapshot taken mid-append must resume at the completed row,
                # not remain pinned to the old partial-line boundary forever.
                state["end"] = stat.st_size
        budget = {"rows": DELIVERY_RECOVERY_ROWS, "bytes": DELIVERY_RECOVERY_BYTES}
        candidates = state.get("candidates") or []
        if not state.get("recent_checked") and not candidates:
            # A UI projection cannot bypass terminal verification while a page
            # is still scanning. Check it once per discovery cycle, then advance
            # through history even if the first projected tasks remain unknown.
            state["recent_checked"] = True
            candidates = [
                {
                    **{key: str(run.get(key) or "").strip() for key in _DELIVERY_BINDING},
                    "projected": True,
                }
                for run in recent
            ]
            if candidates:
                state.update(candidates=candidates, verify_offset=0, projected_page=True)
        if not candidates:
            handle.seek(int(state.get("offset") or 0))
            while len(candidates) < DELIVERY_RECOVERY_RUNS:
                row = _read_delivery_row(handle, state["end"], budget)
                if row is None:
                    break
                feedback = _merge_feedback_row(None, row)
                terminal = feedback and feedback.get("status") in {
                    "completed_merged",
                    "completed_merge_failed",
                }
                if (
                    (
                        (
                            row.get("event") == "merge_requested"
                            and row.get("ok") is True
                            and row.get("status") == "pending"
                            and all(
                                str(row.get(key) or "").strip() for key in _DELIVERY_BINDING[:3]
                            )
                        )
                        or terminal
                    )
                    and row.get("run_id")
                    and not any(item["run_id"] == row["run_id"] for item in candidates)
                ):
                    candidates.append(
                        {
                            **{key: str(row.get(key) or "").strip() for key in _DELIVERY_BINDING},
                            **(
                                {"deployment_scope": row["deployment_scope"]}
                                if isinstance(row.get("deployment_scope"), dict)
                                else {}
                            ),
                        }
                    )
            state["offset"] = handle.tell()
            if not candidates:
                if state["offset"] >= state["end"]:
                    return [], {}
                return [], state
            state.update(candidates=candidates, verify_offset=0)
        by_run = {item["run_id"]: item for item in candidates}
        handle.seek(state["verify_offset"])
        end = os.fstat(handle.fileno()).st_size
        while budget["rows"] and budget["bytes"]:
            row = _read_delivery_row(handle, end, budget)
            if row is None:
                break
            item = by_run.get(str(row.get("run_id") or "").strip())
            if item is None:
                feedback = _merge_feedback_row(None, row)
                if state.get("projected_page") and feedback:
                    state["other_requests"] = True
                continue
            event = row.get("event")
            policy = row.get("policy_decision") or {}
            scope = row.get("deployment_scope") or (
                policy.get("deployment_scope") if isinstance(policy, dict) else None
            )
            if (
                (row.get("phase") == "complete" or event == "merge_requested")
                and isinstance(scope, dict)
                and all(
                    str(row.get(key) or "").strip() == item[key] for key in _DELIVERY_BINDING[:3]
                )
            ):
                item["conflict"] = item.get("conflict") or (
                    "deployment_scope" in item and item["deployment_scope"] != scope
                )
                item["deployment_scope"] = scope
            if event == "merge_requested":
                if item.get("projected") and not item.get("seen"):
                    for key in _DELIVERY_BINDING:
                        if not item[key]:
                            item[key] = str(row.get(key) or "").strip()
                matches = all(
                    str(row.get(key) or "").strip() == item[key] for key in _DELIVERY_BINDING
                )
                item["seen"] = item.get("seen") or matches
                item["conflict"] = item.get("conflict") or not matches
            feedback = _merge_feedback_row(item.get("feedback"), row)
            if feedback:
                item["feedback"] = feedback
                item["terminal"] = feedback.get("status") in {
                    "completed_merged",
                    "completed_merge_failed",
                }
                item["conflict"] = item.get("conflict") or any(
                    str(feedback.get(key) or "").strip() != item[key]
                    for key in _DELIVERY_BINDING[:3]
                )
            sha = str(row.get("merge_sha") or "").strip()
            if row.get("phase") == "deployment" and sha:
                item["conflict"] = item.get("conflict") or bool(
                    item.get("merge_sha") and item["merge_sha"] != sha
                )
                item["merge_sha"] = sha
        state["verify_offset"] = handle.tell()
        if state["verify_offset"] < os.fstat(handle.fileno()).st_size:
            return [], state
        ready = [
            {
                **{key: item[key] for key in _DELIVERY_BINDING},
                "status": "completed_merge_requested",
                **(item.get("feedback") or {}),
                "delivery_merge_sha": item.get("merge_sha", ""),
                **(
                    {"deployment_scope": item["deployment_scope"]}
                    if "deployment_scope" in item
                    else {}
                ),
            }
            for item in candidates
            if (item.get("seen") or item.get("projected") or item.get("terminal"))
            and (include_terminal or not item.get("terminal"))
            and not item.get("conflict")
        ]
        state.pop("candidates")
        state.pop("verify_offset")
        if state.pop("projected_page", False) and not state.pop("other_requests", False):
            state["offset"] = state["end"]
        if state["offset"] >= state["end"]:
            state = {}
        return ready, state


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
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _merge_feedback_row(
    previous: Dict[str, Any] | None, row: Dict[str, Any]
) -> Dict[str, Any] | None:
    """One reducer shared by full readback and bounded recovery; terminals never regress."""
    if previous and previous.get("status") in {
        "completed_merged",
        "completed_merge_failed",
    }:
        return previous
    event, status = row.get("event"), row.get("status")
    if event == "merge_requested" and status == "pending":
        return {**row, "status": "completed_merge_requested"}
    if (
        event == "merge_feedback_reconciled"
        or (
            event in {"merge_completed", "delivery_reconciled"}
            and row.get("ok") is True
            and status == "completed_merged"
        )
        or (row.get("phase") == "complete" and status == "completed_merge_requested")
    ):
        return dict(row)
    return previous


def merge_feedback_runs() -> List[Dict[str, Any]]:
    """Reduce durable delivery state, retaining terminal records as replay fences."""
    runs: Dict[str, Dict[str, Any]] = {}
    for row in _read_ledger(limit=0):
        if not isinstance(row, dict) or not (run_id := str(row.get("run_id") or "")):
            continue
        if reduced := _merge_feedback_row(runs.get(run_id), row):
            runs[run_id] = reduced
    return list(runs.values())


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
    current = (now or config._utc_now()).astimezone(UTC)
    bounded_days = max(1, min(int(window_days or config.DEFAULT_EVIDENCE_WINDOW_DAYS), 90))
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
        if observed_at is None or observed_at < cutoff or observed_at > future_tolerance:
            continue
        eligible.append((row, observed_at))
        run_id = str(row.get("run_id") or "").strip()
        if run_id and observed_at > latest_by_run.get(run_id, cutoff):
            latest_by_run[run_id] = observed_at
    selected_run_ids = {
        run_id
        for (run_id, _) in sorted(latest_by_run.items(), key=lambda item: item[1])[-bounded_runs:]
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
        return data if isinstance(data, dict) else {"execution_state_unavailable": True}
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to read self-maintenance memory")
        return {"execution_state_unavailable": True}


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
        fh.write(_dumps_ledger(record) + "\n")
    return path


def _write_loop_memory(memory: Dict[str, Any]) -> None:
    path = loop_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(_dumps_ledger(memory, indent=2))
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
