"""Scheduler extensions that keep autonomy evidence and remediation moving."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from modstore_server.founder_scorecard_publisher import register_founder_scorecard_job

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
        built_at = built_at.replace(tzinfo=timezone.utc)
    grace_seconds = min(
        4 * 3600,
        _int_env("MODSTORE_AUTONOMY_ROLLOUT_GRACE_SECONDS", 90 * 60, minimum=300),
    )
    deadline = built_at.astimezone(timezone.utc) + timedelta(seconds=grace_seconds)
    return deadline if deadline > datetime.now(timezone.utc) else None


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
    except Exception:
        logger.exception("failed to reconcile verified self-maintenance merge receipts")


def _remediation_lineage_by_run_id() -> dict[str, dict[str, str]]:
    """Recover the original autonomous trigger for resumable ledger runs."""
    from modstore_server.self_maintenance_loop_runner import _read_ledger

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
    from modstore_server.self_maintenance_loop_runner import (
        _automated_remediation_resume_plan,
        _load_loop_memory,
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
            try:
                retry_count = int(item.get("retry_count") or 1)
            except (TypeError, ValueError):
                continue
            max_retries = _int_env(
                "MODSTORE_SELF_MAINTENANCE_MAX_RETRIES",
                3,
                minimum=1,
            )
            if steps and retry_count < max_retries and branch and task_id:
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
        reason = str(item.get("reason") or "").strip()
        resumable = (
            reason == "para_ai_review_rejected"
            or reason in _SCORE_REMEDIATION_REASONS
            or _automated_remediation_resume_plan(reason) is not None
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


def run_pending_automated_remediation() -> dict[str, Any]:
    """Resume a vetoed repair only when the loop has executable stored context."""
    pending = pending_automated_remediation()
    if pending is None:
        return {"ok": True, "status": "skipped_no_pending_remediation"}

    from modstore_server.self_maintenance_loop_runner import run_self_maintenance_loop

    result = run_self_maintenance_loop(
        triggered_by="automated_remediation",
        force=False,
        reason=f"resume:{pending['reason']}",
        remediation_context=pending,
    )
    status = str(result.get("status") or "")
    if status == "failed":
        raise RuntimeError(
            f"automated self-maintenance remediation failed: {result.get('error') or 'unknown'}"
        )
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

    from modstore_server.scheduler_runtime import track_job_run

    def _remediate() -> None:
        try:
            with track_job_run("self_maintenance_remediation_loop"):
                result = run_pending_automated_remediation()
            logger.info(
                "self-maintenance remediation scheduler status=%s reason=%s",
                result.get("status"),
                result.get("reason") or (result.get("gate") or {}).get("reason"),
            )
        except Exception:
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
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
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
