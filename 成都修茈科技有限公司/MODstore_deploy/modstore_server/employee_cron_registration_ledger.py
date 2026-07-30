"""Cross-process registration truth for scheduled employee duties."""

from __future__ import annotations

from datetime import datetime, timezone

REGISTRATION_PREFIX = "employee_cron_registered:"


def record_employee_cron_registration(
    employee_id: str,
    *,
    status: str,
    error: str = "",
) -> None:
    """Persist scheduler-process registration truth for API-process readers."""
    from modstore_server.scheduler_runtime import record_job_run

    now = datetime.now(timezone.utc)
    record_job_run(
        job_id=f"{REGISTRATION_PREFIX}{employee_id}",
        status=status,
        started_at=now,
        finished_at=now,
        error=error,
    )


def reconcile_employee_cron_registrations(registered_ids: set[str]) -> None:
    """Fail closed for duties no longer registered in the current generation."""
    from modstore_server.scheduler_runtime import get_runtime_status

    previous_ids = {
        str(item.get("job_id") or "").removeprefix(REGISTRATION_PREFIX)
        for item in get_runtime_status(scan_limit=10000).get("jobs") or []
        if str(item.get("job_id") or "").startswith(REGISTRATION_PREFIX)
    }
    for employee_id in previous_ids - registered_ids:
        record_employee_cron_registration(
            employee_id,
            status="failed",
            error="not registered in current scheduler generation",
        )


__all__ = [
    "REGISTRATION_PREFIX",
    "reconcile_employee_cron_registrations",
    "record_employee_cron_registration",
]
