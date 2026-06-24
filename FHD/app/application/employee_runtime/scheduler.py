# -*- coding: utf-8 -*-
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

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    last_status: str = "never"  # never/running/success/failed/retrying
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


# ---------------------------------------------------------------------------
# Job 发现
# ---------------------------------------------------------------------------


def _configured_jobs() -> dict[str, EmployeeCronJob]:
    """环境变量配置的 daily-orchestrator job（向后兼容）。"""
    tz = _timezone()
    now = datetime.now(tz)
    auto_enabled = _truthy(os.environ.get("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED"), default=True)
    daily_enabled = _truthy(os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_ENABLED"), default=True)
    hour = _int_env("MODSTORE_DAILY_ORCHESTRATOR_HOUR", 8, minimum=0, maximum=23)
    minute = _int_env("MODSTORE_DAILY_ORCHESTRATOR_MINUTE", 15, minimum=0, maximum=59)
    max_retries = _int_env("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", 0, minimum=0, maximum=5)
    task = str(
        os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_TASK")
        or "每日定时：在独立分支上做最小修复，并把写操作提交到审批队列。"
    )
    job = EmployeeCronJob(
        job_id="daily-orchestrator",
        employee_id="daily-orchestrator",
        task=task,
        schedule="daily",
        hour=hour,
        minute=minute,
        timezone=str(tz.key),
        enabled=auto_enabled and daily_enabled,
        max_retries=max_retries,
        source="env",
    )
    if job.enabled:
        job.next_run_at = _next_daily_run(now, hour, minute)
    return {job.job_id: job}


def _employees_root() -> Path | None:
    """定位 _employees 目录：优先环境变量，其次 mod_manager，最后常见路径。"""
    env_root = os.environ.get("MODSTORE_EMPLOYEES_ROOT", "").strip()
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p
    # lazy import infrastructure，避免 application 层硬依赖
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        roots: list[str] = []
        try:
            roots = list(mgr.all_mods_roots() or [])
        except RECOVERABLE_ERRORS:
            pass
        if not roots:
            primary = getattr(mgr, "mods_root", None)
            if primary:
                roots = [primary]
        for mods_root in roots:
            if not mods_root:
                continue
            cand = Path(mods_root) / "_employees"
            if cand.is_dir():
                return cand
    except RECOVERABLE_ERRORS:
        pass
    return None


def _parse_manifest_schedule(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """解析 manifest 的 employee_config_v2.metadata.schedule 声明。

    schedule 格式::
        {"enabled": true, "hour": 9, "minute": 0,
         "task": "...", "max_retries": 2}

    未声明 schedule 或 enabled=false 返回 None。
    """
    if not isinstance(manifest, dict):
        return None
    v2 = manifest.get("employee_config_v2")
    if not isinstance(v2, dict):
        return None
    metadata = v2.get("metadata")
    if not isinstance(metadata, dict):
        return None
    schedule = metadata.get("schedule")
    if not isinstance(schedule, dict):
        return None
    if not _truthy(schedule.get("enabled"), default=False):
        return None
    return schedule


def _job_from_manifest(
    employee_id: str,
    manifest: dict[str, Any],
    tz: ZoneInfo,
) -> EmployeeCronJob | None:
    """从 manifest 构造 EmployeeCronJob，无 schedule 声明返回 None。"""
    schedule = _parse_manifest_schedule(manifest)
    if schedule is None:
        return None
    hour = int(schedule.get("hour") or 8)
    minute = int(schedule.get("minute") or 0)
    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    task = str(schedule.get("task") or manifest.get("description") or f"每日定时执行 {employee_id}")
    max_retries = max(0, min(5, int(schedule.get("max_retries") or 0)))
    depends_on_raw = manifest.get("depends_on")
    depends_on = (
        [str(x).strip() for x in depends_on_raw if str(x).strip()]
        if isinstance(depends_on_raw, list)
        else []
    )
    now = datetime.now(tz)
    job = EmployeeCronJob(
        job_id=employee_id,
        employee_id=employee_id,
        task=task,
        schedule="daily",
        hour=hour,
        minute=minute,
        timezone=str(tz.key),
        enabled=True,
        max_retries=max_retries,
        source="manifest",
        depends_on=depends_on,
    )
    job.next_run_at = _next_daily_run(now, hour, minute)
    return job


def _discover_manifest_jobs() -> dict[str, EmployeeCronJob]:
    """扫描 _employees 目录，加载所有声明了 schedule 的员工 job。"""
    root = _employees_root()
    if root is None:
        return {}
    tz = _timezone()
    jobs: dict[str, EmployeeCronJob] = {}
    for child in root.iterdir():
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        employee_id = str(data.get("id") or child.name).strip()
        if not employee_id:
            continue
        # daily-orchestrator 由环境变量管理，manifest 声明跳过避免重复
        if employee_id == "daily-orchestrator":
            continue
        # 允许通过环境变量按员工禁用
        per_emp_flag = os.environ.get(
            f"MODSTORE_EMPLOYEE_CRON_{employee_id.upper().replace('-', '_')}_ENABLED"
        )
        if per_emp_flag is not None and not _truthy(per_emp_flag, default=True):
            continue
        job = _job_from_manifest(employee_id, data, tz)
        if job is not None:
            jobs[employee_id] = job
    return jobs


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
    try:
        while not _stop_event.wait(_seconds_until_next_due()):
            for job_id in _due_job_ids():
                try:
                    run_employee_cron_job(job_id, source="cron")
                except RECOVERABLE_ERRORS as exc:
                    logger.warning("employee cron job failed job_id=%s: %s", job_id, exc)
    except Exception as exc:
        logger.exception("employee scheduler loop crashed unexpectedly: %s", exc)
        raise
    finally:
        logger.info("employee scheduler loop stopped")


def start_employee_scheduler() -> dict[str, Any]:
    global _started, _thread, _last_error
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


# ---------------------------------------------------------------------------
# Job 执行
# ---------------------------------------------------------------------------


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
        error = "" if ok else str(result.get("error") or result.get("message") or "")[:800]
        return ok, result, error
    except RECOVERABLE_ERRORS as exc:
        logger.exception("run employee cron job failed job_id=%s", job.job_id)
        return False, {"success": False, "error": str(exc)[:800]}, str(exc)[:800]


def _apply_job_outcome(
    job: EmployeeCronJob,
    *,
    ok: bool,
    error: str,
    duration_ms: float,
    finished: datetime,
) -> bool:
    """根据执行结果更新 job 状态（含重试调度）。必须在 _lock 内调用。

    返回是否应触发失败告警（由调用方在释放 _lock 后调用告警钩子，避免持锁阻塞）。
    """
    global _last_error
    should_alert = False
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
        _last_error = ""
    else:
        job.failure_count += 1
        job.last_error = error or "employee task failed"
        _last_error = job.last_error
        # 判断是否还能重试
        if job.max_retries > 0 and job.retry_count < job.max_retries:
            job.retry_count += 1
            job.last_status = "retrying"
            backoff = _retry_backoff_seconds(job.retry_count)
            job.next_retry_at = finished + timedelta(seconds=backoff)
            logger.info(
                "employee cron job retry scheduled job_id=%s retry=%d/%d backoff=%.0fs",
                job.job_id,
                job.retry_count,
                job.max_retries,
                backoff,
            )
        else:
            # 重试耗尽或未启用重试：标记失败，等下一个每日周期
            job.last_status = "failed"
            job.retry_count = 0
            job.next_retry_at = None
            # 只在最终失败时告警（重试中不告警，避免噪音）；
            # 告警钩子由调用方在释放 _lock 后触发，避免持锁阻塞调度器。
            should_alert = True
    # 无论成功失败，都计算下一个每日运行时间（重试期间 next_run_at 仍推进）
    if job.enabled:
        try:
            tz = ZoneInfo(job.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        job.next_run_at = _next_daily_run(datetime.now(tz), job.hour, job.minute)
    return should_alert


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
    global _last_error
    jid = str(job_id or "").strip()
    with _lock:
        _ensure_jobs_locked()
        job = _jobs.get(jid)
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
        # 手动触发时清除待重试状态，立即执行一次新尝试
        if source == "manual":
            job.retry_count = 0
            job.next_retry_at = None

    started = datetime.now(UTC)
    result: dict[str, Any] = {"success": False}
    try:
        ok, result, error = _execute_job_task(
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
    except Exception as exc:
        # 捕获任何异常（包括不在 RECOVERABLE_ERRORS 中的类型），确保清理 running 标志
        finished = datetime.now(UTC)
        duration_ms = round((finished - started).total_seconds() * 1000, 1)
        ok = False
        result = {"success": False}
        error = str(exc)[:800]
        logger.exception("employee cron job execution failed job_id=%s", jid)
    finally:
        with _lock:
            job = _jobs[jid]
            should_alert = _apply_job_outcome(
                job,
                ok=ok,
                error=error,
                duration_ms=duration_ms,
                finished=finished,
            )
            job_dict = job.to_dict()
            alert_error = job.last_error

    # 在释放 _lock 后触发告警钩子，避免用户自定义钩子的阻塞操作持有全局锁
    if should_alert:
        _invoke_alert_hook(jid, alert_error, job_dict)

    return {"success": ok, "job": job_dict, "result": result}


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
