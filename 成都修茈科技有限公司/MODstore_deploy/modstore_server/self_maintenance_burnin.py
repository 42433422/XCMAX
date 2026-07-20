"""7-day unattended burn-in framework for the self-maintenance loop.

Tracks 4 metrics over a 7-day rolling window against progressive phase
thresholds. When a threshold is breached, an incident is opened via
``incident_bus.publish``; if the same metric breaches on consecutive days,
``notify_sms`` is set so downstream subscribers can dispatch SMS alerts.

The burn-in state machine is intentionally file-backed (no DB) so it stays
independent of the loop runner's SQLite/PG state and can be reset by ops
without touching the ledger.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Path constants (per design spec). ``DEFAULT_RUNTIME_DIR`` is captured at
# import time; runtime reads go through ``_runtime_dir()`` so tests can
# monkeypatch ``MODSTORE_RUNTIME_DIR`` after import.
DEFAULT_RUNTIME_DIR = Path(
    os.environ.get("MODSTORE_RUNTIME_DIR", os.path.expanduser("~/.xcmax/modstore-daily"))
)
BURNIN_STATE_PATH = DEFAULT_RUNTIME_DIR / "burnin_state.json"
BURNIN_HISTORY_PATH = DEFAULT_RUNTIME_DIR / "burnin_metrics.jsonl"
LOOP_LEDGER_PATH = DEFAULT_RUNTIME_DIR / "self_maintenance_loop_memory.json"
GOVERNANCE_AUDIT_PATH = DEFAULT_RUNTIME_DIR / "governance_audit.jsonl"

# Actual file names used at runtime. They match the names written by
# ``self_maintenance_loop_runner`` so we read the real ledger/audit data.
DEFAULT_LEDGER_NAME = "self_maintenance_loop_runs.jsonl"
DEFAULT_GOVERNANCE_AUDIT_NAME = "self_maintenance_governance_actions.jsonl"
DEFAULT_BURNIN_STATE_NAME = "burnin_state.json"
DEFAULT_BURNIN_HISTORY_NAME = "burnin_metrics.jsonl"

TOTAL_BURNIN_DAYS = 7

# Event type used when publishing burn-in threshold breaches. Kept as a
# module-level constant so tests and downstream subscribers can reference it.
BURNIN_EVENT_TYPE = "ops.burnin.threshold_breached"


@dataclass(frozen=True)
class PhaseThreshold:
    """Progressive threshold for one phase of the burn-in window.

    Fields (in order):
    - label: human-readable phase label (e.g. "Day 1-2")
    - completed_merged_min: minimum acceptable completed_merged_rate
    - waiting_human_max: maximum acceptable waiting_human_rate
    - health_min: minimum acceptable health
    - manual_max: maximum acceptable manual_intervention_count
    """

    label: str
    completed_merged_min: float
    waiting_human_max: float
    health_min: float
    manual_max: int


PHASE_THRESHOLDS: List[PhaseThreshold] = [
    PhaseThreshold("Day 1-2", 0.30, 0.70, 0.50, 5),
    PhaseThreshold("Day 3-4", 0.50, 0.50, 0.70, 3),
    PhaseThreshold("Day 5-7", 0.90, 0.10, 0.95, 1),
]


@dataclass(frozen=True)
class ThresholdBreach:
    """A single metric that crossed its phase threshold."""

    metric: str
    actual: float
    threshold: float
    direction: str  # "below_min" or "above_max"
    day_range: str


def _runtime_dir() -> Path:
    env_val = os.environ.get("MODSTORE_RUNTIME_DIR")
    if env_val:
        return Path(env_val)
    return DEFAULT_RUNTIME_DIR


def _burnin_state_path() -> Path:
    return _runtime_dir() / DEFAULT_BURNIN_STATE_NAME


def _burnin_history_path() -> Path:
    return _runtime_dir() / DEFAULT_BURNIN_HISTORY_NAME


def _loop_ledger_path() -> Path:
    return _runtime_dir() / DEFAULT_LEDGER_NAME


def _governance_audit_path() -> Path:
    return _runtime_dir() / DEFAULT_GOVERNANCE_AUDIT_NAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(text: Any) -> Optional[datetime]:
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    try:
        # ``datetime.fromisoformat`` accepts ``+00:00`` since 3.7 but not
        # trailing ``Z`` until 3.11; normalize both.
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _load_jsonl(path: Path, limit: int = 1000) -> List[Dict[str, Any]]:
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
        logger.exception("burnin: failed to read jsonl %s", path)
        return []
    return rows[-limit:]


def _load_burnin_state() -> Dict[str, Any]:
    path = _burnin_state_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.exception("burnin: failed to read state file %s", path)
        return {}


def _save_burnin_state(state: Dict[str, Any]) -> None:
    path = _burnin_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)


def _append_burnin_history(record: Dict[str, Any]) -> None:
    path = _burnin_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _load_burnin_history(limit: int = 100) -> List[Dict[str, Any]]:
    return _load_jsonl(_burnin_history_path(), limit=limit)


def _filter_rows_in_window(
    rows: List[Dict[str, Any]],
    *,
    field: str,
    window_start: datetime,
    window_end: datetime,
) -> List[Dict[str, Any]]:
    """Keep rows whose ``field`` timestamp falls within (window_start, window_end]."""

    out: List[Dict[str, Any]] = []
    for row in rows:
        ts_str = row.get(field) or row.get("created_at") or row.get("completed_at")
        ts = _parse_iso(ts_str)
        if ts is None:
            continue
        if ts < window_start or ts > window_end:
            continue
        out.append(row)
    return out


def get_burnin_start_at() -> Optional[datetime]:
    state = _load_burnin_state()
    started_at = state.get("started_at")
    if not started_at:
        return None
    return _parse_iso(started_at)


def set_burnin_start_at(*, started_by: str = "admin") -> datetime:
    """Set the burn-in start time. Raises ``ValueError`` if already started."""

    existing = get_burnin_start_at()
    if existing is not None:
        raise ValueError(f"burnin already started at {existing.isoformat()}")
    now = _utc_now()
    state = _load_burnin_state()
    state["started_at"] = _iso(now)
    state["started_by"] = str(started_by or "admin")
    state.setdefault("reset_history", [])
    _save_burnin_state(state)
    return now


def get_burnin_day_index(now: Optional[datetime] = None) -> int:
    """Return 1-indexed day number. Returns 0 if not started.

    Day 1 = the first 24 hours since start. Day N = days since start + 1.
    """

    start = get_burnin_start_at()
    if start is None:
        return 0
    current = now or _utc_now()
    delta = current - start
    if delta.total_seconds() < 0:
        # Clock skew or future-dated start: treat as day 1.
        return 1
    return delta.days + 1


def get_current_phase_threshold(
    now: Optional[datetime] = None,
) -> Optional[PhaseThreshold]:
    """Return the current phase threshold, or ``None`` if not started / expired."""

    day = get_burnin_day_index(now)
    if day < 1:
        return None
    if day > TOTAL_BURNIN_DAYS:
        return None
    if day <= 2:
        return PHASE_THRESHOLDS[0]
    if day <= 4:
        return PHASE_THRESHOLDS[1]
    return PHASE_THRESHOLDS[2]


def compute_burnin_metrics(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Compute the 4 burn-in metrics over the 7-day rolling window.

    Returns a dict with:
    - total_complete_runs: count of phase=complete records in window
    - completed_merged: count where status=completed_merged
    - completed_merged_rate: completed_merged / total_complete_runs (0.0 if no runs)
    - waiting_human: count where status=completed_waiting_human_strategy
    - waiting_human_rate: waiting_human / total_complete_runs (0.0 if no runs)
    - failed: count where status=failed
    - abandoned_stale: count where status=abandoned_stale
    - health: 1.0 - ((failed + abandoned_stale) / total_complete_runs) (1.0 if no runs)
    - manual_intervention_count: manual runs + governance_audit reviews in window
    - manual_runs: subset count of manual-triggered runs
    - governance_reviews: subset count of governance_audit reviews
    - window_start, window_end: ISO8601 strings
    """

    current = now or _utc_now()
    window_end = current
    window_start = current - timedelta(days=TOTAL_BURNIN_DAYS)

    all_rows = _load_jsonl(_loop_ledger_path(), limit=5000)

    complete_rows = [row for row in all_rows if str(row.get("phase") or "") == "complete"]
    complete_in_window = _filter_rows_in_window(
        complete_rows,
        field="completed_at",
        window_start=window_start,
        window_end=window_end,
    )

    total_complete_runs = len(complete_in_window)
    completed_merged = sum(
        1 for row in complete_in_window if str(row.get("status") or "") == "completed_merged"
    )
    waiting_human = sum(
        1
        for row in complete_in_window
        if str(row.get("status") or "") == "completed_waiting_human_strategy"
    )
    failed = sum(1 for row in complete_in_window if str(row.get("status") or "") == "failed")
    abandoned_stale = sum(
        1 for row in complete_in_window if str(row.get("status") or "") == "abandoned_stale"
    )

    completed_merged_rate = (
        completed_merged / total_complete_runs if total_complete_runs > 0 else 0.0
    )
    waiting_human_rate = waiting_human / total_complete_runs if total_complete_runs > 0 else 0.0
    health = (
        1.0 - (float(failed + abandoned_stale) / total_complete_runs)
        if total_complete_runs > 0
        else 1.0
    )

    start_rows = [row for row in all_rows if str(row.get("phase") or "") == "start"]
    start_in_window = _filter_rows_in_window(
        start_rows,
        field="created_at",
        window_start=window_start,
        window_end=window_end,
    )
    manual_runs = sum(
        1 for row in start_in_window if str(row.get("triggered_by") or "") == "manual"
    )

    governance_rows = _load_jsonl(_governance_audit_path(), limit=2000)
    governance_in_window = _filter_rows_in_window(
        governance_rows,
        field="created_at",
        window_start=window_start,
        window_end=window_end,
    )
    governance_reviews = sum(
        1
        for row in governance_in_window
        if str(row.get("action") or "") == "review_governance_audit"
    )

    manual_intervention_count = manual_runs + governance_reviews

    return {
        "total_complete_runs": total_complete_runs,
        "completed_merged": completed_merged,
        "completed_merged_rate": completed_merged_rate,
        "waiting_human": waiting_human,
        "waiting_human_rate": waiting_human_rate,
        "failed": failed,
        "abandoned_stale": abandoned_stale,
        "health": health,
        "manual_intervention_count": manual_intervention_count,
        "manual_runs": manual_runs,
        "governance_reviews": governance_reviews,
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
    }


def _incident_fingerprint(breach: ThresholdBreach, day_range: str) -> str:
    """Deterministic fingerprint by metric + day_range.

    ``actual`` is intentionally excluded so multiple occurrences of the same
    metric breach within the same phase share a fingerprint for dedup.
    """

    raw = json.dumps(
        {"metric": breach.metric, "day_range": day_range},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _should_notify_sms(
    breaches: List[ThresholdBreach],
    threshold: PhaseThreshold,  # noqa: ARG001 - kept for API symmetry / future use
) -> bool:
    """Return True only if the same metric breached on the immediately previous day.

    Rules:
    - No breaches → False
    - Burn-in not started / day 1 → False (no prior day to compare)
    - No history entry for ``current_day - 1`` → False
    - Intersection of current breach metrics and prior-day breach metrics non-empty → True
    """

    if not breaches:
        return False
    current_day = get_burnin_day_index()
    if current_day <= 1:
        return False
    target_day = current_day - 1

    history = _load_burnin_history(limit=200)
    prior_entry: Optional[Dict[str, Any]] = None
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        if int(entry.get("burnin_day") or 0) == target_day:
            prior_entry = entry
            break
    if not prior_entry:
        return False

    prior_breaches = prior_entry.get("breaches") or []
    if not isinstance(prior_breaches, list):
        return False
    prior_metrics = {
        str(b.get("metric") or "")
        for b in prior_breaches
        if isinstance(b, dict) and b.get("metric")
    }
    current_metrics = {b.metric for b in breaches}
    return bool(current_metrics & prior_metrics)


def check_burnin_thresholds(
    now: Optional[datetime] = None,
) -> Tuple[List[ThresholdBreach], bool]:
    """Check current metrics against the current phase threshold.

    Returns ``(breaches, notify_sms)``. Returns ``([], False)`` if the burn-in
    is not started or has expired (no threshold to compare against).
    """

    threshold = get_current_phase_threshold(now)
    if threshold is None:
        return [], False

    metrics = compute_burnin_metrics(now)
    breaches: List[ThresholdBreach] = []

    if float(metrics["completed_merged_rate"]) < threshold.completed_merged_min:
        breaches.append(
            ThresholdBreach(
                metric="completed_merged_rate",
                actual=float(metrics["completed_merged_rate"]),
                threshold=float(threshold.completed_merged_min),
                direction="below_min",
                day_range=threshold.label,
            )
        )
    if float(metrics["waiting_human_rate"]) > threshold.waiting_human_max:
        breaches.append(
            ThresholdBreach(
                metric="waiting_human_rate",
                actual=float(metrics["waiting_human_rate"]),
                threshold=float(threshold.waiting_human_max),
                direction="above_max",
                day_range=threshold.label,
            )
        )
    if float(metrics["health"]) < threshold.health_min:
        breaches.append(
            ThresholdBreach(
                metric="health",
                actual=float(metrics["health"]),
                threshold=float(threshold.health_min),
                direction="below_min",
                day_range=threshold.label,
            )
        )
    if int(metrics["manual_intervention_count"]) > int(threshold.manual_max):
        breaches.append(
            ThresholdBreach(
                metric="manual_intervention_count",
                actual=float(metrics["manual_intervention_count"]),
                threshold=float(threshold.manual_max),
                direction="above_max",
                day_range=threshold.label,
            )
        )

    notify_sms = _should_notify_sms(breaches, threshold)
    return breaches, notify_sms


def open_burnin_incident(
    breach: ThresholdBreach,
    day_range: str,
    notify_sms: bool,
) -> bool:
    """Publish a burn-in incident via ``incident_bus.publish``.

    Fail-open: any error (missing module, publish crash) is logged and
    ``False`` is returned. The burn-in check itself must never block on
    incident dispatch failures.
    """

    try:
        from modstore_server.incident_bus import publish
    except Exception:
        logger.exception("burnin: incident_bus module not available")
        return False

    fingerprint = _incident_fingerprint(breach, day_range)
    payload = {
        "metric": breach.metric,
        "actual": breach.actual,
        "threshold": breach.threshold,
        "direction": breach.direction,
        "day_range": day_range,
        "notify_sms": bool(notify_sms),
        "burnin_day": get_burnin_day_index(),
        "source_module": "self_maintenance_burnin",
    }

    try:
        result = publish(
            event_type=BURNIN_EVENT_TYPE,
            payload=payload,
            source="self_maintenance_burnin",
            fingerprint=fingerprint,
        )
        return bool(result)
    except Exception:
        logger.exception("burnin: failed to publish incident for %s", breach.metric)
        return False


def start_burnin(*, started_by: str = "admin") -> Dict[str, Any]:
    """Start the 7-day burn-in window. Idempotent-safe: returns error if active."""

    try:
        started_at = set_burnin_start_at(started_by=started_by)
    except ValueError as exc:
        return {
            "ok": False,
            "active": True,
            "error": str(exc),
            "started_at": None,
        }
    return {
        "ok": True,
        "active": True,
        "started_at": _iso(started_at),
        "started_by": started_by,
        "burnin_day": 1,
        "phase": PHASE_THRESHOLDS[0].label,
        "total_burnin_days": TOTAL_BURNIN_DAYS,
    }


def reset_burnin(*, reset_by: str = "admin") -> Dict[str, Any]:
    """Reset burn-in state, preserving ``reset_history`` of prior runs."""

    state = _load_burnin_state()
    reset_history = state.get("reset_history") or []
    if not isinstance(reset_history, list):
        reset_history = []
    prior = {
        "started_at": state.get("started_at"),
        "started_by": state.get("started_by"),
        "reset_at": _iso(_utc_now()),
        "reset_by": reset_by,
    }
    reset_history.append(prior)
    new_state: Dict[str, Any] = {
        "started_at": None,
        "started_by": None,
        "reset_history": reset_history,
    }
    _save_burnin_state(new_state)
    return {
        "ok": True,
        "active": False,
        "reset_history": reset_history,
    }


def get_burnin_status() -> Dict[str, Any]:
    """Return the current burn-in status (does not check thresholds)."""

    start = get_burnin_start_at()
    if start is None:
        return {
            "active": False,
            "expired": False,
            "started_at": None,
            "burnin_day": 0,
            "phase": None,
            "remaining_days": 0,
            "total_burnin_days": TOTAL_BURNIN_DAYS,
        }

    day = get_burnin_day_index()
    threshold = get_current_phase_threshold()
    expired = day > TOTAL_BURNIN_DAYS
    remaining = max(0, TOTAL_BURNIN_DAYS - day + 1) if not expired else 0

    return {
        "active": not expired,
        "expired": expired,
        "started_at": _iso(start),
        "burnin_day": day,
        "phase": threshold.label if threshold else None,
        "remaining_days": remaining,
        "total_burnin_days": TOTAL_BURNIN_DAYS,
    }


def _breach_to_dict(breach: ThresholdBreach) -> Dict[str, Any]:
    return asdict(breach)


def run_burnin_check(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Main entrypoint for the scheduled burn-in job.

    - Not started → ``{"ok": False, "active": False, "reason": "not_started"}``
    - Expired (day > 7) → ``{"ok": True, "expired": True, "burnin_day": N, ...}``
    - Otherwise → checks thresholds, opens incidents for each breach, writes
      history. Returns ``{"ok": len(breaches)==0, "burnin_day": N, "phase": ...,
      "breaches": [...], "notify_sms": bool, "metrics": {...}}``.
    """

    start = get_burnin_start_at()
    if start is None:
        return {"ok": False, "active": False, "reason": "not_started"}

    current = now or _utc_now()
    day = get_burnin_day_index(current)
    threshold = get_current_phase_threshold(current)

    if threshold is None or day > TOTAL_BURNIN_DAYS:
        return {
            "ok": True,
            "active": False,
            "expired": True,
            "burnin_day": day,
            "started_at": _iso(start),
            "total_burnin_days": TOTAL_BURNIN_DAYS,
        }

    breaches, notify_sms = check_burnin_thresholds(current)
    metrics = compute_burnin_metrics(current)

    incidents_opened = 0
    for breach in breaches:
        if open_burnin_incident(breach, threshold.label, notify_sms):
            incidents_opened += 1

    history_entry = {
        "timestamp": _iso(current),
        "burnin_day": day,
        "phase": threshold.label,
        "metrics": metrics,
        "breaches": [_breach_to_dict(b) for b in breaches],
        "notify_sms": notify_sms,
    }
    try:
        _append_burnin_history(history_entry)
    except Exception:
        logger.exception("burnin: failed to append history")

    return {
        "ok": len(breaches) == 0,
        "active": True,
        "expired": False,
        "burnin_day": day,
        "phase": threshold.label,
        "breaches": history_entry["breaches"],
        "notify_sms": notify_sms,
        "metrics": metrics,
        "incidents_opened": incidents_opened,
        "started_at": _iso(start),
        "total_burnin_days": TOTAL_BURNIN_DAYS,
    }


__all__ = [
    "BURNIN_EVENT_TYPE",
    "BURNIN_HISTORY_PATH",
    "BURNIN_STATE_PATH",
    "DEFAULT_RUNTIME_DIR",
    "GOVERNANCE_AUDIT_PATH",
    "LOOP_LEDGER_PATH",
    "PHASE_THRESHOLDS",
    "PhaseThreshold",
    "TOTAL_BURNIN_DAYS",
    "ThresholdBreach",
    "check_burnin_thresholds",
    "compute_burnin_metrics",
    "get_burnin_day_index",
    "get_burnin_start_at",
    "get_burnin_status",
    "get_current_phase_threshold",
    "open_burnin_incident",
    "reset_burnin",
    "run_burnin_check",
    "set_burnin_start_at",
    "start_burnin",
]
