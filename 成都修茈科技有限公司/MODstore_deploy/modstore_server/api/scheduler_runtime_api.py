"""运行时状态读取端点：一处回答「什么在跑 / 什么停了 / 各 job 上次成功何时」。"""

from __future__ import annotations

from fastapi import APIRouter

from modstore_server.scheduler_runtime import get_runtime_status

router = APIRouter(tags=["scheduler-runtime"])


@router.get("/api/scheduler/runtime")
def scheduler_runtime(stale_after_seconds: int | None = None) -> dict:
    """按 job 汇总的调度器运行时真相；``stale_after_seconds`` 可覆盖停摆阈值。"""
    runtime = get_runtime_status(stale_after_seconds=stale_after_seconds)
    try:
        from modstore_server.workflow_scheduler import list_employee_cron_jobs

        registered = list_employee_cron_jobs()
    except Exception:
        registered = []

    registered_ids = {
        str(item.get("employee_id") or "").strip()
        for item in registered
        if str(item.get("employee_id") or "").strip()
    }
    observed = {
        str(item.get("job_id") or "").removeprefix("employee_cron:"): item
        for item in runtime.get("jobs") or []
        if str(item.get("job_id") or "").startswith("employee_cron:")
    }
    observed_registered = registered_ids.intersection(observed)
    failing = {
        employee_id
        for employee_id in observed_registered
        if str(observed[employee_id].get("last_status") or "") == "failed"
    }
    runtime["employee_duty"] = {
        "registered_cron_count": len(registered_ids),
        "observed_cron_count": len(observed_registered),
        "last_success_count": len(observed_registered - failing),
        "failing_count": len(failing),
        "never_run_count": len(registered_ids - observed_registered),
        "unregistered_observed_count": len(set(observed) - registered_ids),
    }
    return runtime
