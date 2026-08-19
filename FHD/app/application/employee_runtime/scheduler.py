"""Lightweight local scheduler for AI employee packs.

This is intentionally process-local: it gives the desktop/admin runtime a real
"daily" trigger without adding a new service dependency. Production multi-pod
deployments can keep the same HTTP surface and replace this with external cron.

支持两类 job 来源：
1. 环境变量配置的 ``daily-orchestrator``（向后兼容，默认 8:15 Asia/Shanghai）
2. ``_employees/<id>/manifest.json`` 中 ``employee_config_v2.metadata.schedule``
   声明的定时员工（未声明的员工不加入调度）

失败处理：
- 失败后按指数退避自动重试（``max_retries`` 控制，默认 0=不重试）
- 重试耗尽后等下一个每日周期
- 可通过 ``set_alert_hook`` 注入失败告警回调
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 告警钩子签名：(job_id, error_message, job_dict) -> None
AlertHook = Callable[[str, str, dict[str, Any]], None]

# 重试退避基数（秒），实际退避 = _RETRY_BASE_SECONDS * (2 ** retry_count)
_RETRY_BASE_SECONDS = 60


def _truthy(raw: Any, *, default: bool) -> bool:
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "y", "on", "enabled"}


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _timezone() -> ZoneInfo:
    name = (
        os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_TZ") or os.environ.get("TZ") or "Asia/Shanghai"
    )
    try:
        return ZoneInfo(str(name))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _next_daily_run(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _retry_backoff_seconds(retry_count: int) -> float:
    """指数退避：第 1 次重试 60s，第 2 次 120s，第 3 次 240s ..."""
    return float(_RETRY_BASE_SECONDS * (2 ** max(0, retry_count)))


def _result_error(value: Any) -> str:
    """Extract a nested executor error without serializing potentially large output."""
    if not isinstance(value, dict):
        return ""
    for key in ("error", "cognition_error", "message"):
        text = str(value.get(key) or "").strip()
        if text:
            return text[:800]
    nested = value.get("result")
    if isinstance(nested, dict):
        text = _result_error(nested)
        if text:
            return text
    outputs = value.get("outputs")
    if isinstance(outputs, list):
        for output in outputs:
            text = _result_error(output)
            if text:
                return text
    return ""


def _is_non_retryable_configuration_error(error: str) -> bool:
    text = str(error or "").casefold()
    if not text:
        return False
    return (
        "employee_llm_not_configured" in text
        or "未配置 llm" in text
        or "未配置 openai_api_key" in text
        or "online 模式下无法调用云端大模型" in text
        or "宿主未配置" in text
    )


@dataclass
class EmployeeCronJob:
    job_id: str
    employee_id: str
    task: str
    schedule: str
    hour: int
    minute: int
    timezone: str
    enabled: bool
    next_run_at: datetime | None = None
    running: bool = False
    runs_total: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_run_at: datetime | None = None
    last_status: str = "never"  # never/running/success/failed/retrying/blocked_config
    last_error: str = ""
    last_duration_ms: float | None = None
    # 失败重试
    max_retries: int = 0
    retry_count: int = 0
    next_retry_at: datetime | None = None
    # 来源标记（env / manifest）
    source: str = "env"
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        next_run = self.next_run_at.isoformat() if self.next_run_at else None
        last_run = self.last_run_at.isoformat() if self.last_run_at else None
        next_retry = self.next_retry_at.isoformat() if self.next_retry_at else None
        if not self.enabled:
            state = "disabled"
        elif self.running:
            state = "running"
        elif self.last_status == "blocked_config":
            state = "blocked_config"
        elif self.next_retry_at is not None:
            state = "retrying"
        elif self.next_run_at:
            state = "scheduled"
        else:
            state = "stopped"
        return {
            "job_id": self.job_id,
            "id": self.job_id,
            "employee_id": self.employee_id,
            "task": self.task,
            "schedule": self.schedule,
            "hour": self.hour,
            "minute": self.minute,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "running": self.running,
            "state": state,
            "next_run_at": next_run,
            "next_run_time": next_run,
            "last_run_at": last_run,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_duration_ms": self.last_duration_ms,
            "runs_total": self.runs_total,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "next_retry_at": next_retry,
            "source": self.source,
            "depends_on": list(self.depends_on),
        }


_lock = threading.RLock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None
_jobs: dict[str, EmployeeCronJob] = {}
_started = False
_last_error = ""
_alert_hook: AlertHook | None = None


from app.application.employee_runtime.scheduler_discovery import (
    _configured_jobs as _configured_jobs,
)
from app.application.employee_runtime.scheduler_discovery import (
    _discover_manifest_jobs as _discover_manifest_jobs,
)
from app.application.employee_runtime.scheduler_discovery import _employees_root as _employees_root
from app.application.employee_runtime.scheduler_discovery import (
    _job_from_manifest as _job_from_manifest,
)
from app.application.employee_runtime.scheduler_discovery import (
    _parse_manifest_schedule as _parse_manifest_schedule,
)
from app.application.employee_runtime.scheduler_execution import (
    _apply_job_outcome as _apply_job_outcome,
)
from app.application.employee_runtime.scheduler_execution import (
    _execute_job_task as _execute_job_task,
)
from app.application.employee_runtime.scheduler_execution import (
    run_employee_cron_job as run_employee_cron_job,
)

# ---------------------------------------------------------------------------
# 调度状态管理
# ---------------------------------------------------------------------------


def refresh_employee_scheduler_jobs() -> dict[str, Any]:
    """Rebuild local employee cron jobs from env flags + manifest discovery."""
    with _lock:
        old = _jobs
        _jobs.clear()
        # daily-orchestrator 始终第一个（向后兼容 jobs[0]）
        for job_id, job in _configured_jobs().items():
            previous = old.get(job_id)
            if previous:
                _inherit_job_state(job, previous)
            _jobs[job_id] = job
        # manifest 发现的额外 job
        for job_id, job in _discover_manifest_jobs().items():
            if job_id in _jobs:
                continue
            previous = old.get(job_id)
            if previous:
                _inherit_job_state(job, previous)
            _jobs[job_id] = job
    return get_employee_scheduler_status()


def _inherit_job_state(job: EmployeeCronJob, previous: EmployeeCronJob) -> None:
    """refresh 时保留运行统计与重试状态。"""
    job.runs_total = previous.runs_total
    job.success_count = previous.success_count
    job.failure_count = previous.failure_count
    job.last_run_at = previous.last_run_at
    job.last_status = previous.last_status
    job.last_error = previous.last_error
    job.last_duration_ms = previous.last_duration_ms
    job.running = previous.running
    job.retry_count = previous.retry_count
    job.next_retry_at = previous.next_retry_at


def _ensure_jobs_locked() -> None:
    if not _jobs:
        for job_id, job in _configured_jobs().items():
            _jobs[job_id] = job
        for job_id, job in _discover_manifest_jobs().items():
            if job_id not in _jobs:
                _jobs[job_id] = job


def get_employee_cron_jobs() -> list[dict[str, Any]]:
    with _lock:
        _ensure_jobs_locked()
        return [job.to_dict() for job in sorted(_jobs.values(), key=lambda item: item.job_id)]


def get_employee_scheduler_status() -> dict[str, Any]:
    with _lock:
        _ensure_jobs_locked()
        return {
            "enabled": any(job.enabled for job in _jobs.values()),
            "running": bool(_started and _thread and _thread.is_alive()),
            "last_error": _last_error,
            "jobs": [job.to_dict() for job in sorted(_jobs.values(), key=lambda item: item.job_id)],
        }


# ---------------------------------------------------------------------------
# 调度循环
# ---------------------------------------------------------------------------


def _job_next_due(job: EmployeeCronJob) -> datetime | None:
    """返回 job 的下一个到期时间（取 next_retry_at 和 next_run_at 的较小值）。"""
    candidates: list[datetime] = []
    if job.next_retry_at is not None:
        candidates.append(job.next_retry_at)
    if job.next_run_at is not None:
        candidates.append(job.next_run_at)
    return min(candidates) if candidates else None


def _seconds_until_next_due() -> float:
    with _lock:
        _ensure_jobs_locked()
        due_times: list[datetime] = []
        for job in _jobs.values():
            if not job.enabled or job.running:
                continue
            nxt = _job_next_due(job)
            if nxt is not None:
                due_times.append(nxt)
    if not due_times:
        return 60.0
    now = datetime.now(due_times[0].tzinfo or UTC)
    return max(1.0, min(60.0, (min(due_times) - now).total_seconds()))


def _due_job_ids() -> list[str]:
    with _lock:
        _ensure_jobs_locked()
        now_by_tz: dict[str, datetime] = {}
        due: list[str] = []
        for job in _jobs.values():
            if not job.enabled or job.running:
                continue
            tz_name = job.timezone or "UTC"
            now = now_by_tz.get(tz_name)
            if now is None:
                try:
                    now = datetime.now(ZoneInfo(tz_name))
                except ZoneInfoNotFoundError:
                    now = datetime.now(UTC)
                now_by_tz[tz_name] = now
            nxt = _job_next_due(job)
            if nxt is not None and nxt <= now:
                due.append(job.job_id)
        return due


def _scheduler_loop() -> None:
    logger.info("employee scheduler loop started")
    while not _stop_event.wait(_seconds_until_next_due()):
        for job_id in _due_job_ids():
            try:
                run_employee_cron_job(job_id, source="cron")
            except RECOVERABLE_ERRORS as exc:
                logger.warning("employee cron job failed job_id=%s: %s", job_id, exc)
    logger.info("employee scheduler loop stopped")


def start_employee_scheduler() -> dict[str, Any]:
    global _started, _thread, _last_error
    # 桌面默认关掉 cron 风暴（可用 XCAGI_EMPLOYEE_SCHEDULER=1 显式打开）
    import os

    flag = (os.environ.get("XCAGI_EMPLOYEE_SCHEDULER") or "").strip().lower()
    desktop = (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if flag in {"0", "false", "no", "off"} or (desktop and flag not in {"1", "true", "yes", "on"}):
        logger.info("employee scheduler skipped (desktop or XCAGI_EMPLOYEE_SCHEDULER off)")
        _started = False
        return {**get_employee_scheduler_status(), "skipped": True}
    with _lock:
        _ensure_jobs_locked()
        if _thread and _thread.is_alive():
            _started = True
            return get_employee_scheduler_status()
        if not any(job.enabled for job in _jobs.values()):
            _started = False
            return get_employee_scheduler_status()
        _last_error = ""
        _stop_event.clear()
        _thread = threading.Thread(
            target=_scheduler_loop,
            name="employee-runtime-scheduler",
            daemon=True,
        )
        _started = True
        _thread.start()
    return get_employee_scheduler_status()


def stop_employee_scheduler(timeout: float = 3.0) -> dict[str, Any]:
    global _started
    thread: threading.Thread | None
    with _lock:
        thread = _thread
        _started = False
        _stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=timeout)
    return get_employee_scheduler_status()


# ---------------------------------------------------------------------------
# 告警钩子
# ---------------------------------------------------------------------------


def set_alert_hook(hook: AlertHook | None) -> None:
    """注册失败告警回调。传入 None 清除钩子。

    回调签名：(job_id, error_message, job_dict) -> None
    回调抛出的异常会被捕获并记录，不影响调度循环。
    """
    global _alert_hook
    with _lock:
        _alert_hook = hook


def _invoke_alert_hook(job_id: str, error: str, job_dict: dict[str, Any]) -> None:
    hook = _alert_hook
    if hook is None:
        return
    try:
        hook(job_id, error, job_dict)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("employee cron alert hook failed job_id=%s: %s", job_id, exc)




__all__ = [
    "AlertHook",
    "get_employee_cron_jobs",
    "get_employee_scheduler_status",
    "refresh_employee_scheduler_jobs",
    "run_employee_cron_job",
    "set_alert_hook",
    "start_employee_scheduler",
    "stop_employee_scheduler",
]
