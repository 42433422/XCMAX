"""Manifest discovery for employee scheduler jobs."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.application.employee_runtime.scheduler import EmployeeCronJob
logger = logging.getLogger(__name__)


def _facade() -> Any:
    from app.application.employee_runtime import scheduler

    return scheduler


def _configured_jobs() -> dict[str, EmployeeCronJob]:
    """环境变量配置的 daily-orchestrator job（向后兼容）。"""
    from app.mod_sdk.product_plane import automatic_employee_runtime_enabled

    if not automatic_employee_runtime_enabled():
        return {}
    tz = _facade()._timezone()
    now = datetime.now(tz)
    automation_enabled = automatic_employee_runtime_enabled()
    auto_enabled = automation_enabled and _facade()._truthy(
        os.environ.get("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED"), default=True
    )
    daily_enabled = automation_enabled and _facade()._truthy(
        os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_ENABLED"), default=True
    )
    hour = _facade()._int_env("MODSTORE_DAILY_ORCHESTRATOR_HOUR", 8, minimum=0, maximum=23)
    minute = _facade()._int_env("MODSTORE_DAILY_ORCHESTRATOR_MINUTE", 15, minimum=0, maximum=59)
    max_retries = _facade()._int_env("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", 0, minimum=0, maximum=5)
    task = str(
        os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_TASK")
        or "每日定时：在独立分支上做最小修复，并把写操作提交到审批队列。"
    )
    job = _facade().EmployeeCronJob(
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
        job.next_run_at = _facade()._next_daily_run(now, hour, minute)
    return {job.job_id: job}


def _employees_root() -> Path | None:
    """定位 _employees 目录：优先环境变量，其次 mod_manager，最后常见路径。"""
    env_root = os.environ.get("MODSTORE_EMPLOYEES_ROOT", "").strip()
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p
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
    if not _facade()._truthy(schedule.get("enabled"), default=False):
        return None
    return schedule


def _job_from_manifest(
    employee_id: str, manifest: dict[str, Any], tz: ZoneInfo
) -> EmployeeCronJob | None:
    """从 manifest 构造 EmployeeCronJob，无 schedule 声明返回 None。"""
    schedule = _facade()._parse_manifest_schedule(manifest)
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
    job = _facade().EmployeeCronJob(
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
    job.next_run_at = _facade()._next_daily_run(now, hour, minute)
    return cast("EmployeeCronJob", job)


def _discover_manifest_jobs() -> dict[str, EmployeeCronJob]:
    """扫描 _employees 目录，加载所有声明了 schedule 的员工 job。"""
    from app.mod_sdk.product_plane import automatic_employee_runtime_enabled

    if not automatic_employee_runtime_enabled():
        return {}
    root = _facade()._employees_root()
    if root is None:
        return {}
    tz = _facade()._timezone()
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
        if employee_id == "daily-orchestrator":
            continue
        per_emp_flag = os.environ.get(
            f"MODSTORE_EMPLOYEE_CRON_{employee_id.upper().replace('-', '_')}_ENABLED"
        )
        if per_emp_flag is not None and (not _facade()._truthy(per_emp_flag, default=True)):
            continue
        job = _facade()._job_from_manifest(employee_id, data, tz)
        if job is not None:
            jobs[employee_id] = job
    return jobs
