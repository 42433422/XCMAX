"""运行时状态读取端点：一处回答「什么在跑 / 什么停了 / 各 job 上次成功何时」。"""

from __future__ import annotations

from fastapi import APIRouter

from modstore_server.employee_cron_registration_ledger import DEFERRED_STATUS, REGISTRATION_PREFIX
from modstore_server.scheduler_runtime import get_runtime_status

router = APIRouter(tags=["scheduler-runtime"])

_EXECUTION_PREFIX = "employee_cron:"


@router.get("/api/scheduler/runtime")
def scheduler_runtime(stale_after_seconds: int | None = None) -> dict:
    """按 job 汇总的调度器运行时真相；``stale_after_seconds`` 可覆盖停摆阈值。"""
    runtime = get_runtime_status(stale_after_seconds=stale_after_seconds)
    registrations = {
        str(item.get("job_id") or "").removeprefix(REGISTRATION_PREFIX): item
        for item in runtime.get("jobs") or []
        if str(item.get("job_id") or "").startswith(REGISTRATION_PREFIX)
    }
    registered_ids = {
        employee_id
        for employee_id, item in registrations.items()
        if str(item.get("last_status") or "") == "success"
    }
    registration_failing = {
        employee_id
        for employee_id, item in registrations.items()
        if str(item.get("last_status") or "") == "failed"
    }
    approval_required = {
        employee_id
        for employee_id, item in registrations.items()
        if str(item.get("last_status") or "") == DEFERRED_STATUS
    }
    observed = {
        str(item.get("job_id") or "").removeprefix(_EXECUTION_PREFIX): item
        for item in runtime.get("jobs") or []
        if str(item.get("job_id") or "").startswith(_EXECUTION_PREFIX)
    }
    observed_registered = registered_ids.intersection(observed)
    failing = {
        employee_id
        for employee_id in observed_registered
        if str(observed[employee_id].get("last_status") or "") == "failed"
    }
    failure_code_counts: dict[str, int] = {}
    for employee_id in failing:
        code = str(observed[employee_id].get("last_error_code") or "").strip()
        if code:
            failure_code_counts[code] = failure_code_counts.get(code, 0) + 1
    deferred_observed = approval_required.intersection(observed)
    policy_held_failed_execution_ids = {
        f"{_EXECUTION_PREFIX}{employee_id}"
        for employee_id in deferred_observed
        if str(observed[employee_id].get("last_status") or "") == "failed"
    }

    # Keep the raw scheduler ledger summary intact: a historical failed run is
    # still evidence. Expose its current policy context separately so callers
    # can alert only on failures that are actionable without human approval.
    jobs = runtime.get("jobs") or []
    actionable_failing_count = sum(
        1
        for item in jobs
        if isinstance(item, dict)
        and str(item.get("state") or "") == "failing"
        and str(item.get("job_id") or "") not in policy_held_failed_execution_ids
    )
    summary = runtime.get("summary")
    if isinstance(summary, dict):
        summary["policy_held_failures"] = len(policy_held_failed_execution_ids)
        summary["actionable_failing"] = actionable_failing_count

    runtime["employee_duty"] = {
        "registration_observable": bool(registrations),
        "registered_cron_count": len(registered_ids),
        "registration_failing_count": len(registration_failing),
        "approval_required_count": len(approval_required),
        "observed_cron_count": len(observed_registered),
        "last_success_count": len(observed_registered - failing),
        "failing_count": len(failing),
        "failure_code_counts": dict(sorted(failure_code_counts.items())),
        "never_run_count": len(registered_ids - observed_registered),
        "approval_required_observed_execution_count": len(deferred_observed),
        "policy_held_observed_failure_count": len(policy_held_failed_execution_ids),
        "unregistered_observed_count": len(set(observed) - registered_ids - approval_required),
    }
    try:
        from modstore_server.storage_pressure_self_heal import get_storage_pressure_status

        runtime["storage_pressure"] = get_storage_pressure_status(limit=20)
    except Exception as exc:  # pragma: no cover - observability must remain failure-safe.
        runtime["storage_pressure"] = {
            "ok": False,
            "reason": "storage_pressure_status_unavailable",
            "error": type(exc).__name__,
        }
    return runtime
