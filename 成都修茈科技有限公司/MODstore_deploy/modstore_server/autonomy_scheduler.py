# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Scheduler extensions that keep autonomy evidence and remediation moving."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from apscheduler.triggers.interval import IntervalTrigger

from modstore_server.founder_scorecard_publisher import register_founder_scorecard_job
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

REQUIRED_JOB_IDS = frozenset(
    {
        "founder_scorecard_refresh",
        "self_maintenance_heartbeat",
        "self_maintenance_loop_daily",
        "self_maintenance_remediation_loop",
    }
)
CRITICAL_RUNTIME_JOBS = {
    "founder_scorecard_refresh": "founder_scorecard_refresh",
    "self_maintenance_loop_daily": "self_maintenance_loop_daily",
    "self_maintenance_remediation_loop": "self_maintenance_remediation_loop",
}
_SCORE_REMEDIATION_REASONS = frozenset(
    {
        "auto_merge_safety_score_v2_too_low",
        "auto_merge_safety_score_v3_too_low",
        "risk_score_v3_below_threshold_or_blocked",
    }
)
_DEFERRED_REMEDIATION_ERRORS = frozenset(
    {
        "retort_clarification_pending",
        "retort_clarification_expired",
        "retort_clarification_cancelled",
    }
)


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _rollout_recovery_deadline() -> datetime | None:
    """Anchor cross-stack startup grace to the immutable release, not process restarts."""
    if str(os.environ.get("MODSTORE_DEPLOY_TIER") or "").strip().lower() != "production":
        return None
    configured = str(os.environ.get("MODSTORE_RELEASE_MANIFEST") or "").strip()
    manifest_path = (
        Path(configured) if configured else Path("/opt/xcmax/current/.xcmax-release.json")
    )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        built_at = datetime.fromisoformat(str(payload["built_at"]).replace("Z", "+00:00"))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if built_at.tzinfo is None:
        built_at = built_at.replace(tzinfo=UTC)
    grace_seconds = min(
        4 * 3600,
        _int_env("MODSTORE_AUTONOMY_ROLLOUT_GRACE_SECONDS", 90 * 60, minimum=300),
    )
    deadline = built_at.astimezone(UTC) + timedelta(seconds=grace_seconds)
    return deadline if deadline > datetime.now(UTC) else None


def self_maintenance_cooldown_minutes(triggered_by: str) -> int:
    """Use a bounded repair cooldown without weakening manual or daily gates."""
    if triggered_by == "automated_remediation":
        return _int_env(
            "MODSTORE_SELF_MAINTENANCE_REMEDIATION_COOLDOWN_MINUTES",
            60,
            minimum=15,
        )
    if triggered_by == "incident_event":
        return _int_env(
            "MODSTORE_SELF_MAINTENANCE_INCIDENT_COOLDOWN_MINUTES",
            60,
            minimum=0,
        )
    return _int_env("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", 360, minimum=0)


def _reconcile_completed_loop_memory_safely() -> None:
    """Best-effort settlement must never prevent the next scheduler decision."""
    try:
        from modstore_server.self_maintenance_memory_reconciliation import (
            reconcile_completed_loop_memory_from_ledger,
        )

        reconcile_completed_loop_memory_from_ledger()
    except RECOVERABLE_ERRORS:
        logger.exception("failed to reconcile verified self-maintenance merge receipts")


def _remediation_lineage_by_run_id() -> dict[str, dict[str, str]]:
    """Recover the original autonomous trigger for resumable ledger runs."""
    from modstore_server.maintenance_loop.store import _read_ledger

    lineage: dict[str, dict[str, str]] = {}
    for row in _read_ledger(limit=5000):
        if not isinstance(row, dict) or str(row.get("phase") or "") != "start":
            continue
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        triggered_by = str(row.get("triggered_by") or "").strip()
        origin_triggered_by = str(row.get("origin_triggered_by") or "").strip()
        if not origin_triggered_by and triggered_by != "automated_remediation":
            origin_triggered_by = triggered_by
        if not origin_triggered_by:
            continue
        lineage[run_id] = {
            "origin_run_id": str(row.get("origin_run_id") or run_id).strip(),
            "origin_triggered_by": origin_triggered_by,
            "origin_reason": str(row.get("origin_reason") or row.get("reason") or "").strip(),
        }
    return lineage


def _with_remediation_lineage(
    candidate: dict[str, Any],
    item: dict[str, Any],
    lineage_by_run_id: dict[str, dict[str, str]],
) -> dict[str, Any]:
    run_id = str(candidate.get("run_id") or "").strip()
    lineage = {
        "origin_run_id": str(item.get("origin_run_id") or "").strip(),
        "origin_triggered_by": str(item.get("origin_triggered_by") or "").strip(),
        "origin_reason": str(item.get("origin_reason") or "").strip(),
    }
    stored = lineage_by_run_id.get(run_id) or {}
    for key in ("origin_run_id", "origin_triggered_by", "origin_reason"):
        if not lineage[key]:
            lineage[key] = str(stored.get(key) or "").strip()
        if lineage[key]:
            candidate[key] = lineage[key]
    return candidate


def _remediation_priority(candidate: dict[str, Any], item_index: int) -> tuple[int, int]:
    """Prioritize safety recovery while preserving newest-first behavior per class."""
    origin = str(candidate.get("origin_triggered_by") or "").strip()
    origin_priority = {
        "incident_event": 30,
        "proactive_signal": 20,
    }.get(origin, 10)
    return origin_priority, item_index


def pending_automated_remediation() -> dict[str, Any] | None:
    """Settle verified receipts, then return one executable unattended repair."""
    from modstore_server.maintenance_loop.store import _load_loop_memory
    from modstore_server.self_maintenance_remediation_lineage import (
        automated_remediation_resume_plan,
        normalize_automated_remediation_reason,
    )

    _reconcile_completed_loop_memory_safely()
    memory = _load_loop_memory()
    open_items = memory.get("open_items") if isinstance(memory, dict) else None
    if not isinstance(open_items, list):
        return None
    lineage_by_run_id = _remediation_lineage_by_run_id()
    candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for item_index, item in enumerate(open_items):
        if not isinstance(item, dict):
            continue
        if item.get("escalated"):
            continue
        kind = str(item.get("kind") or "").strip()
        branch = str(item.get("branch") or "").strip()
        task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        if kind == "failed_steps":
            raw_steps = item.get("steps")
            steps = (
                [str(step) for step in raw_steps if str(step) in {"code", "review", "qa"}]
                if isinstance(raw_steps, list)
                else []
            )
            if steps and branch and task_id:
                candidate = _with_remediation_lineage(
                    {
                        "branch": branch,
                        "reason": f"failed_steps:{','.join(steps)}",
                        "run_id": str(item.get("run_id") or "").strip(),
                        "steps": steps,
                        "task_id": task_id,
                    },
                    item,
                    lineage_by_run_id,
                )
                candidates.append((_remediation_priority(candidate, item_index), candidate))
            continue
        if kind != "automated_remediation":
            continue
        reason = normalize_automated_remediation_reason(memory, item)
        resumable = (
            reason == "para_ai_review_rejected"
            or reason in _SCORE_REMEDIATION_REASONS
            or automated_remediation_resume_plan(reason) is not None
        )
        if resumable and branch and task_id:
            candidate = _with_remediation_lineage(
                {
                    "branch": branch,
                    "reason": reason,
                    "run_id": str(item.get("run_id") or "").strip(),
                    "task_id": task_id,
                },
                item,
                lineage_by_run_id,
            )
            candidates.append((_remediation_priority(candidate, item_index), candidate))
    return max(candidates, key=lambda entry: entry[0])[1] if candidates else None


class RemediationBlocked(RuntimeError):
    """Unresolved work remains unhealthy even when dispatch is intentionally stopped."""

    def __init__(self, reason: str, attempts: int, retry_at: str | None = None):
        self.receipt = {
            "status": "blocked",
            "reason": reason,
            "attempts": attempts,
            "retry_at": retry_at,
            "scheduler_status": "failed",
        }
        super().__init__(f"remediation_blocked:{reason}")


def _remediation_key(item: dict[str, Any]) -> list[str]:
    return [
        str(item.get("branch") or "").strip(),
        str(item.get("task_id") or item.get("para_task_id") or "").strip(),
    ]


def _reserve_remediation_attempt(pending: dict[str, Any]) -> set[tuple[str, ...]]:
    """Reserve before dispatch; a crash consumes its attempt, never silently resets it.

    Reuse the existing append-only ledger and its flock protocol. Scan all guard
    receipts so history truncation in runtime views cannot reset the budget.
    Missing task attribution is never inferred from branch alone.
    """
    import fcntl

    from modstore_server.maintenance_loop.store import _load_loop_memory, ledger_path

    key = _remediation_key(pending)
    if not all(key[:2]):
        raise RemediationBlocked("missing_identity", 0)
    items = _load_loop_memory().get("open_items", [])
    counts = [int(pending.get("retry_count") or 0)]
    counts.extend(
        int(item.get("retry_count") or 0)
        for item in items
        if isinstance(item, dict) and _remediation_key(item) == key
    )
    if any(count < 0 for count in counts):
        raise RemediationBlocked("invalid_attempt_count", 0)
    limit = _int_env("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", 3, minimum=1)
    active = {
        tuple(_remediation_key(item))
        for item in items
        if isinstance(item, dict) and item.get("kind") in {"automated_remediation", "failed_steps"}
    }
    blocked = {
        tuple(_remediation_key(item))
        for item in items
        if isinstance(item, dict)
        and tuple(_remediation_key(item)) in active
        and int(item.get("retry_count") or 0) >= limit
    }
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        attempts = max(counts)
        last_attempt = 0
        last_at = None
        for item in items:
            if not isinstance(item, dict) or _remediation_key(item) != key:
                continue
            count = int(item.get("retry_count") or 0)
            if count != attempts or count < 1:
                continue
            stamp = item.get("last_attempted_at") or (
                item.get("created_at") if count == 1 else None
            )
            if stamp:
                at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if at.tzinfo is None:
                    raise RemediationBlocked("invalid_attempt_timestamp", attempts)
                if last_at is None or at > last_at:
                    last_attempt, last_at = count, at
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("phase") != "remediation_attempt":
                continue
            row_key = tuple(row["remediation_key"])
            count = int(row["attempt"])
            if row_key in active and count >= limit:
                blocked.add(row_key)
            if row_key != tuple(key):
                continue
            at = datetime.fromisoformat(row["timestamp"])
            if count < 1 or at.tzinfo is None:
                raise RemediationBlocked("invalid_attempt_record", attempts)
            attempts = max(attempts, count)
            if count > last_attempt or (
                count == last_attempt and (last_at is None or at > last_at)
            ):
                last_attempt, last_at = count, at
        if attempts >= limit:
            raise RemediationBlocked("retry_limit", attempts)
        if attempts and last_at is None:
            raise RemediationBlocked("retry_history_timestamp_missing", attempts)
        now = datetime.now(UTC)
        if last_at is not None:
            delay = min(
                86400,
                self_maintenance_cooldown_minutes("automated_remediation")
                * 60
                * 2 ** min(attempts - 1, 10),
            )
            due = last_at + timedelta(seconds=delay)
            if now < due:
                raise RemediationBlocked("backoff", attempts, due.isoformat())
        fh.seek(0, os.SEEK_END)
        fh.write(
            json.dumps(
                {
                    "ledger_schema_version": 2,
                    "phase": "remediation_attempt",
                    "run_id": uuid4().hex,
                    "remediation_key": key,
                    "attempt": attempts + 1,
                    "timestamp": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        fh.flush()
        os.fsync(fh.fileno())
    return blocked - {tuple(key)}


def run_pending_automated_remediation() -> dict[str, Any]:
    """Resume a vetoed repair only when the loop has executable stored context."""
    pending = pending_automated_remediation()
    if pending is None:
        return {"ok": True, "status": "skipped_no_pending_remediation"}

    from modstore_server.maintenance_loop.coordinator import run_self_maintenance_loop

    blocked = _reserve_remediation_attempt(pending)
    result = run_self_maintenance_loop(
        triggered_by="automated_remediation",
        force=False,
        reason=f"resume:{pending['reason']}",
        remediation_context=pending,
    )
    status = str(result.get("status") or "")
    if status in {"failed", "blocked"}:
        error = str(result.get("error") or "unknown")
        if error in _DEFERRED_REMEDIATION_ERRORS:
            result = {
                **result,
                "scheduler_reason": error,
                "scheduler_status": "deferred",
            }
        else:
            raise RuntimeError(f"automated self-maintenance remediation failed: {error}")
    if blocked:
        from modstore_server.maintenance_loop.store import _load_loop_memory

        remaining = _load_loop_memory().get("open_items", [])
        if any(
            isinstance(item, dict) and tuple(_remediation_key(item)) in blocked
            for item in remaining
        ):
            raise RemediationBlocked("other_retry_limit", 0)
    return result


def register_autonomy_jobs(
    scheduler: Any,
    recovery_deadlines: dict[str, datetime] | None = None,
) -> None:
    """Register scorecard publication and active self-maintenance remediation."""
    deadline = _rollout_recovery_deadline()
    if deadline is not None and recovery_deadlines is not None:
        recovery_deadlines["founder_scorecard_refresh"] = deadline
        recovery_deadlines["self_maintenance_remediation_loop"] = deadline
    register_founder_scorecard_job(scheduler)

    from modstore_server.scheduler_runtime import DeferredJobRun, track_job_run

    def _remediate() -> None:
        try:
            with track_job_run("self_maintenance_remediation_loop"):
                result = run_pending_automated_remediation()
                if result.get("scheduler_status") == "deferred":
                    raise DeferredJobRun(str(result.get("scheduler_reason") or "policy_hold"))
            logger.info(
                "self-maintenance remediation scheduler status=%s runtime_status=%s reason=%s",
                result.get("status"),
                result.get("scheduler_status") or "success",
                result.get("reason") or (result.get("gate") or {}).get("reason"),
            )
        except RECOVERABLE_ERRORS:
            logger.exception("self-maintenance remediation scheduler failed")

    scheduler.add_job(
        _remediate,
        IntervalTrigger(
            minutes=_int_env(
                "MODSTORE_SELF_MAINTENANCE_REMEDIATION_INTERVAL_MINUTES",
                30,
                minimum=15,
            )
        ),
        id="self_maintenance_remediation_loop",
        replace_existing=True,
        next_run_time=datetime.now(UTC) + timedelta(seconds=90),
        misfire_grace_time=_int_env(
            "MODSTORE_SCHEDULER_BUSINESS_MISFIRE_GRACE_SECONDS",
            3600,
            minimum=60,
        ),
        coalesce=True,
        max_instances=1,
    )


__all__ = [
    "CRITICAL_RUNTIME_JOBS",
    "REQUIRED_JOB_IDS",
    "pending_automated_remediation",
    "register_autonomy_jobs",
    "run_pending_automated_remediation",
    "self_maintenance_cooldown_minutes",
]
