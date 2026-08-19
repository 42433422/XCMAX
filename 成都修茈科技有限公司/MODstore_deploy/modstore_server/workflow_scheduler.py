# ruff: noqa: E402, F401
"""工作流 cron 触发：从 DB 加载 APScheduler 任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from modstore_server import autonomy_scheduler, payment_orders
from modstore_server.models import WorkflowTrigger, get_session_factory
from modstore_server.scheduler_extensions import register_extensions as _register_extensions
from modstore_server.scheduler_timing import (
    cleanup_misfire_grace_time as _cleanup_misfire_grace_time,
)
from modstore_server.workflow_event_runner import run_workflow_for_trigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None
_scheduler_registration_complete = False
_scheduler_startup_probe_failures: list[dict[str, str]] = []
_scheduler_startup_recovery_deadlines: dict[str, datetime] = {}

_JOB_PREFIX = "wf_trigger_"
_LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS = 0.0
_LAST_TIME_RAIL_OBSERVABILITY_MISSING = -1

_REQUIRED_CORE_JOB_IDS = frozenset(
    {
        "auto_fix_event_bindings_refresh",
        "auto_merge_audit_sampling",
        "auto_version_bump_daily",
        "autonomy_metrics_snapshot",
        "autonomy_posthoc_audit",
        "capability_proposal_relay",
        "customer_value_reconciler",
        "daily_backup_job",
        "daily_ops_digest_email",
        "daily_orchestrator_job",
        "dead_letter_reconciler",
        "dr_recovery_probe_job",
        "duty_workforce_learning",
        "email_intake_poll",
        "employee_autonomy_dispatch_loop",
        "employee_evolution_scan_loop",
        "employee_health_scan_loop",
        "incident_collect_extended",
        "incident_collect_nginx",
        "incident_collect_pytest_cursor",
        "inbox_approval_poll",
        "kb_self_maintenance",
        "payment_orders_expire",
        "predictive_maintenance_forecast",
        "retention_janitor_daily",
        "scheduler_heartbeat",
        "self_evolution_metrics",
        "storage_pressure_self_heal",
        "telemetry_backlog_scan",
        "time_rail_observability_sync",
    }
)
_CRITICAL_RUNTIME_JOB_TO_SCHEDULER_ID = {
    "daily_digest": "daily_ops_digest_email",
    "boss_daily_im_report": "boss_daily_im_report",
    **autonomy_scheduler.CRITICAL_RUNTIME_JOBS,
}


from modstore_server.workflow_scheduler_part01 import (
    _env_int as _env_int,
    _env_bool as _env_bool,
    _business_misfire_grace_time as _business_misfire_grace_time,
    required_scheduler_job_ids as required_scheduler_job_ids,
    scheduler_integrity_status as scheduler_integrity_status,
    _run_scheduler_startup_probe as _run_scheduler_startup_probe,
    _startup_recovery_kwargs as _startup_recovery_kwargs,
    scheduler_runtime_health_status as scheduler_runtime_health_status,
    _daily_pipeline_lock_wait_seconds as _daily_pipeline_lock_wait_seconds,
    _run_daily_pipeline_stage as _run_daily_pipeline_stage,
    _run_tracked_scheduler_job as _run_tracked_scheduler_job,
    _require_customer_value_source_ready as _require_customer_value_source_ready,
    _run_authoritative_customer_value_job as _run_authoritative_customer_value_job,
    _trigger_self_maintenance_from_incident as _trigger_self_maintenance_from_incident,
    _run_collector_with_timeout as _run_collector_with_timeout,
)


from modstore_server.workflow_scheduler_startup_phase01 import _register_scheduler_phase_01
from modstore_server.workflow_scheduler_startup_phase02 import _register_scheduler_phase_02
from modstore_server.workflow_scheduler_startup_phase03 import _register_scheduler_phase_03
from modstore_server.workflow_scheduler_startup_phase04 import _register_scheduler_phase_04


def start_scheduler() -> None:
    global _scheduler, _scheduler_registration_complete, _scheduler_startup_probe_failures
    global _scheduler_startup_recovery_deadlines
    if _scheduler is not None:
        return
    _scheduler_registration_complete = False
    _scheduler_startup_probe_failures = []
    _scheduler_startup_recovery_deadlines = {}
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    _register_scheduler_phase_01()
    _register_scheduler_phase_02()
    _register_scheduler_phase_03()
    _register_scheduler_phase_04()
    _scheduler_registration_complete = True
    integrity = scheduler_integrity_status()
    if integrity["ok"]:
        logger.info(
            "workflow scheduler started: active=%s required=%s",
            integrity["active_job_count"],
            integrity["required_job_count"],
        )
    else:
        logger.error(
            "workflow scheduler registration incomplete: active=%s required=%s missing=%s",
            integrity["active_job_count"],
            integrity["required_job_count"],
            integrity["missing_required_jobs"],
        )


_EMPLOYEE_CRON_JOB_PREFIX = "emp_cron_"


from modstore_server.workflow_scheduler_part02 import (
    _employee_auto_cron_enabled as _employee_auto_cron_enabled,
    _employee_cron_job_id as _employee_cron_job_id,
    _extract_employee_schedule as _extract_employee_schedule,
    _employee_project_root as _employee_project_root,
    _register_employee_cron_jobs as _register_employee_cron_jobs,
    list_employee_cron_jobs as list_employee_cron_jobs,
    reload_employee_cron_jobs as reload_employee_cron_jobs,
    stop_scheduler as stop_scheduler,
    _job_id as _job_id,
    _load_triggers as _load_triggers,
    _register_cron_trigger as _register_cron_trigger,
    unregister_cron_trigger as unregister_cron_trigger,
    refresh_cron_trigger as refresh_cron_trigger,
    reload_all_cron_triggers as reload_all_cron_triggers,
)
