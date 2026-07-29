"""运行时状态读取端点：一处回答「什么在跑 / 什么停了 / 各 job 上次成功何时」。"""

from __future__ import annotations

from fastapi import APIRouter

from modstore_server.employee_cron_registration_ledger import REGISTRATION_PREFIX
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
    runtime["employee_duty"] = {
        "registration_observable": bool(registrations),
        "registered_cron_count": len(registered_ids),
        "registration_failing_count": len(registration_failing),
        "observed_cron_count": len(observed_registered),
        "last_success_count": len(observed_registered - failing),
        "failing_count": len(failing),
        "never_run_count": len(registered_ids - observed_registered),
        "unregistered_observed_count": len(set(observed) - registered_ids),
    }
    return runtime
