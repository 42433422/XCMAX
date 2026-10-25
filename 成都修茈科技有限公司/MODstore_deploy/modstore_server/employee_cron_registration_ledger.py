"""Cross-process registration truth for scheduled employee duties."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

REGISTRATION_PREFIX = "employee_cron_registered:"
DEFERRED_STATUS = "deferred"
APPROVAL_REQUIRED_HIGH_RISK_CODE = "employee_cron_policy_deferred:approval_required_high_risk"


def defer_employee_cron_if_approval_required(
    employee_id: str,
    work_contract: dict[str, Any],
) -> bool:
    """Record reviewed high-risk duty as awaiting human approval."""
    risk_level = str(work_contract.get("risk_level") or "").strip().lower()
    if risk_level in {"", "low", "medium"}:
        return False
    record_employee_cron_registration(
        employee_id,
        status=DEFERRED_STATUS,
        error=APPROVAL_REQUIRED_HIGH_RISK_CODE,
    )
    return True


def record_employee_cron_registration(
    employee_id: str,
    *,
    status: str,
    error: str = "",
) -> None:
    """Persist scheduler-process registration truth for API-process readers."""
    from modstore_server.scheduler_runtime import record_job_run

    now = datetime.now(UTC)
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
    "APPROVAL_REQUIRED_HIGH_RISK_CODE",
    "DEFERRED_STATUS",
    "REGISTRATION_PREFIX",
    "defer_employee_cron_if_approval_required",
    "reconcile_employee_cron_registrations",
    "record_employee_cron_registration",
]
