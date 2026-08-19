"""Scheduler adapter for the storage-pressure self-healing operation."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


def require_successful_storage_self_heal(result: Dict[str, Any]) -> Dict[str, Any]:
    """Make unresolved pressure visible as a failed scheduler job."""
    if result.get("ok") is not True:
        raise RuntimeError(f"storage_self_heal_unresolved:{result.get('status') or 'unknown'}")
    return result


def register_storage_pressure_job(
    scheduler: Any,
    *,
    track_job: Callable[[str, Callable[[], Dict[str, Any]]], Dict[str, Any]],
    startup_probe: Callable[[str, Callable[[], Any]], bool],
    misfire_grace_time: int,
    interval_minutes: int,
    run_self_heal: Callable[[], Dict[str, Any]],
    require_success: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> None:
    """Register the recurring guard with injected runtime callbacks."""

    def _job() -> Dict[str, Any]:
        result = track_job(
            "storage_pressure_self_heal",
            lambda: require_success(run_self_heal()),
        )
        logger.info(
            "storage pressure guard: status=%s action=%s before_free=%s after_free=%s",
            result.get("status"),
            bool(result.get("action_taken")),
            int((result.get("before") or {}).get("free_bytes") or 0),
            int((result.get("after") or {}).get("free_bytes") or 0),
        )
        return result

    scheduler.add_job(
        _job,
        IntervalTrigger(minutes=interval_minutes),
        id="storage_pressure_self_heal",
        replace_existing=True,
        misfire_grace_time=max(60, int(misfire_grace_time)),
        coalesce=True,
        max_instances=1,
    )
    startup_probe("storage_pressure_self_heal", _job)
