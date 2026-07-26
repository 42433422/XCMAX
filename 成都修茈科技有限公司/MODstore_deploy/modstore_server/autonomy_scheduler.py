"""Scheduler extensions that keep autonomy evidence and remediation moving."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
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


def pending_automated_remediation() -> dict[str, Any] | None:
    """Return one executable remediation receipt without mutating loop memory."""
    from modstore_server.self_maintenance_loop_runner import (
        _automated_remediation_resume_plan,
        _load_loop_memory,
    )

    memory = _load_loop_memory()
    open_items = memory.get("open_items") if isinstance(memory, dict) else None
    if not isinstance(open_items, list):
        return None
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") != "automated_remediation":
            continue
        if item.get("escalated"):
            continue
        reason = str(item.get("reason") or "").strip()
        resumable = (
            reason == "para_ai_review_rejected"
            or reason in _SCORE_REMEDIATION_REASONS
            or _automated_remediation_resume_plan(reason) is not None
        )
        branch = str(item.get("branch") or "").strip()
        task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        if resumable and branch and task_id:
            return {
                "branch": branch,
                "reason": reason,
                "run_id": str(item.get("run_id") or "").strip(),
                "task_id": task_id,
            }
    return None


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
    )
    status = str(result.get("status") or "")
    if status == "failed":
        raise RuntimeError(
            f"automated self-maintenance remediation failed: {result.get('error') or 'unknown'}"
        )
    return result


def register_autonomy_jobs(scheduler: Any) -> None:
    """Register scorecard publication and active self-maintenance remediation."""
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
