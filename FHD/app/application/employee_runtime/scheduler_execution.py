"""Execution and outcome handling for employee scheduler jobs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.application.employee_runtime.scheduler import EmployeeCronJob
logger = logging.getLogger(__name__)


def _facade() -> Any:
    from app.application.employee_runtime import scheduler

    return scheduler


def _execute_job_task(
    job: EmployeeCronJob,
    *,
    task: str | None,
    input_data: dict[str, Any] | None,
    user_id: int,
    workspace_root: str | None,
    session_id: str | None,
    source: str,
) -> tuple[bool, dict[str, Any], str]:
    """执行单个 job 的任务，返回 (ok, result, error)。"""
    try:
        from app.application.employee_runtime.executor import execute_employee_task_local

        payload = dict(input_data or {})
        payload.setdefault("trigger", source)
        payload.setdefault("cron_job_id", job.job_id)
        payload.setdefault("approved_write", False)
        payload.setdefault("allow_write", False)
        result = execute_employee_task_local(
            job.employee_id,
            task or job.task,
            payload,
            user_id=user_id,
            workspace_root=workspace_root,
            session_id=session_id,
        )
        ok = bool(result.get("success"))
        error = "" if ok else _facade()._result_error(result)
        if not error:
            error = "employee task failed"
        return (ok, result, error)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("run employee cron job failed job_id=%s", job.job_id)
        return (False, {"success": False, "error": str(exc)[:800]}, str(exc)[:800])


def _apply_job_outcome(
    job: EmployeeCronJob, *, ok: bool, error: str, duration_ms: float, finished: datetime
) -> None:
    """根据执行结果更新 job 状态（含重试调度与告警）。必须在 _facade()._lock 内调用。"""
    job.running = False
    job.runs_total += 1
    job.last_run_at = finished
    job.last_duration_ms = duration_ms
    if ok:
        job.success_count += 1
        job.last_status = "success"
        job.last_error = ""
        job.retry_count = 0
        job.next_retry_at = None
        _facade()._last_error = ""
    else:
        job.failure_count += 1
        job.last_error = error or "employee task failed"
        _facade()._last_error = job.last_error
        if _facade()._is_non_retryable_configuration_error(job.last_error):
            job.last_status = "blocked_config"
            job.retry_count = 0
            job.next_retry_at = None
            logger.warning("employee cron job blocked by configuration job_id=%s", job.job_id)
            _facade()._invoke_alert_hook(job.job_id, job.last_error, job.to_dict())
        elif job.max_retries > 0 and job.retry_count < job.max_retries:
            job.retry_count += 1
            job.last_status = "retrying"
            backoff = _facade()._retry_backoff_seconds(job.retry_count)
            job.next_retry_at = finished + timedelta(seconds=backoff)
            logger.info(
                "employee cron job retry scheduled job_id=%s retry=%d/%d backoff=%.0fs",
                job.job_id,
                job.retry_count,
                job.max_retries,
                backoff,
            )
        else:
            job.last_status = "failed"
            job.retry_count = 0
            job.next_retry_at = None
            _facade()._invoke_alert_hook(job.job_id, job.last_error, job.to_dict())
    if job.enabled:
        try:
            tz = ZoneInfo(job.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        job.next_run_at = _facade()._next_daily_run(datetime.now(tz), job.hour, job.minute)


def run_employee_cron_job(
    job_id: str,
    *,
    task: str | None = None,
    input_data: dict[str, Any] | None = None,
    user_id: int = 0,
    workspace_root: str | None = None,
    session_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """Run a configured employee cron job immediately.

    失败时若 job.max_retries > 0 会自动调度指数退避重试（next_retry_at），
    重试由调度循环在到期后触发；手动调用本函数始终执行一次新尝试。
    """
    jid = str(job_id or "").strip()
    with _facade()._lock:
        _facade()._ensure_jobs_locked()
        job = _facade()._jobs.get(jid)
        if job is None:
            return {"success": False, "error": f"unknown employee cron job: {jid}"}
        if job.running:
            return {
                "success": False,
                "error": f"employee cron job already running: {jid}",
                "job": job.to_dict(),
            }
        job.running = True
        job.last_status = "running"
        if source == "manual":
            job.retry_count = 0
            job.next_retry_at = None
    started = datetime.now(UTC)
    (ok, result, error) = _facade()._execute_job_task(
        job,
        task=task,
        input_data=input_data,
        user_id=user_id,
        workspace_root=workspace_root,
        session_id=session_id,
        source=source,
    )
    finished = datetime.now(UTC)
    duration_ms = round((finished - started).total_seconds() * 1000, 1)
    with _facade()._lock:
        job = _facade()._jobs[jid]
        _facade()._apply_job_outcome(
            job, ok=ok, error=error, duration_ms=duration_ms, finished=finished
        )
        job_dict = job.to_dict()
    return {"success": ok, "job": job_dict, "result": result}
