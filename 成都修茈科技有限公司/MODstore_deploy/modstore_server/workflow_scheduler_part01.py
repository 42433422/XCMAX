# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_scheduler")


def _env_int(name: str, default: int) -> int:
    try:
        return int(_facade().os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _facade().os.environ.get(name)
    return default if raw is None else str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _business_misfire_grace_time() -> int:
    return max(
        60,
        _facade()._env_int("MODSTORE_SCHEDULER_BUSINESS_MISFIRE_GRACE_SECONDS", 3600),
    )


def required_scheduler_job_ids() -> tuple[str, ...]:
    required = set(_facade()._REQUIRED_CORE_JOB_IDS) | set(
        _facade().autonomy_scheduler.REQUIRED_JOB_IDS
    )
    if _facade()._env_bool("MODSTORE_EMPLOYEE_BURN_IN_SCHEDULER_ENABLED", True):
        required.add("duty_workforce_burnin")
    if _facade()._env_bool("MODSTORE_CS_WEBHOOK_OUTBOX_RETRY_ENABLED", True):
        required.add("cs_webhook_outbox_retry")
    if _facade()._env_bool("MODSTORE_BOSS_IM_REPORT_ENABLED", True):
        required.add("boss_daily_im_report")
    if _facade()._env_bool("MODSTORE_LLM_AUTOPILOT_ENABLED", False):
        required.add("llm_route_autopilot")
    if _facade()._env_bool("MODSTORE_DAILY_CHAIN_CRON_FALLBACK_ENABLED", False):
        required.update({"daily_release_train_orchestrator_job", "daily_vibe_line_execute_job"})
    if _facade()._env_bool("MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED", False):
        required.add("post_deploy_smoke_interval")
    return tuple(sorted(required))


def scheduler_integrity_status() -> dict[str, _facade().Any]:
    """Report scheduler engine and registration completeness separately."""
    required = _facade().required_scheduler_job_ids()
    active: set[str] = set()
    engine_running = False
    if _facade()._scheduler is not None:
        engine_running = bool(getattr(_facade()._scheduler, "running", False))
        try:
            active = {str(job.id) for job in _facade()._scheduler.get_jobs()}
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("scheduler integrity: get_jobs failed")
    missing = sorted(set(required) - active)
    complete = bool(_facade()._scheduler_registration_complete)
    return {
        "ok": engine_running and complete and (not missing),
        "engine_running": engine_running,
        "registration_complete": complete,
        "required_job_count": len(required),
        "active_job_count": len(active),
        "missing_required_jobs": missing,
        "startup_probe_failures": list(_facade()._scheduler_startup_probe_failures),
    }


def _run_scheduler_startup_probe(stage: str, fn: _facade().Callable[[], _facade().Any]) -> bool:
    """Run an eager probe without allowing one dependency to truncate registration."""
    try:
        fn()
        return True
    except RECOVERABLE_ERRORS as exc:
        failure = {
            "stage": stage,
            "error_type": type(exc).__name__,
            "message": str(exc)[:240],
        }
        _facade()._scheduler_startup_probe_failures.append(failure)
        _facade().logger.warning(
            "scheduler startup probe failed; registration continues: stage=%s error=%s",
            stage,
            failure["message"],
        )
        return False


def _startup_recovery_kwargs(job_id: str, *, delay_seconds: int) -> dict[str, _facade().datetime]:
    """Schedule one catch-up run when a critical daily job is missing or stale."""
    if not _facade()._env_bool("MODSTORE_SCHEDULER_STARTUP_RECOVERY_ENABLED", True):
        return {}
    stale_after = max(
        3600,
        _facade()._env_int("MODSTORE_SCHEDULER_STARTUP_RECOVERY_STALE_SECONDS", 26 * 3600),
    )
    due = True
    state = "missing"
    try:
        from modstore_server.scheduler_runtime import get_runtime_status

        runtime = get_runtime_status(stale_after_seconds=stale_after)
        row = next(
            (item for item in runtime.get("jobs") or [] if item.get("job_id") == job_id),
            None,
        )
        state = str((row or {}).get("state") or "missing")
        due = not runtime.get("ok") or row is None or state in {"stale", "failing"}
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("scheduler startup recovery status failed: job_id=%s", job_id)
    if not due:
        return {}
    now = _facade().datetime.now(_facade().timezone.utc)
    recovery_at = now + _facade().timedelta(seconds=max(1, delay_seconds))
    grace_seconds = max(
        300,
        _facade()._env_int("MODSTORE_SCHEDULER_STARTUP_RECOVERY_GRACE_SECONDS", 3600),
    )
    _facade()._scheduler_startup_recovery_deadlines[job_id] = now + _facade().timedelta(
        seconds=grace_seconds
    )
    _facade().logger.warning(
        "scheduler startup catch-up scheduled: job_id=%s state=%s run_at=%s",
        job_id,
        state,
        recovery_at.isoformat(),
    )
    return {"next_run_time": recovery_at}


def scheduler_runtime_health_status() -> dict[str, _facade().Any]:
    """Return health for active, critical daily jobs only.

    Historical rows from disabled jobs do not poison health. A startup catch-up
    is reported as ``recovering`` for a bounded grace period instead of causing
    the watchdog to restart the process while the recovery job is running.
    """
    from modstore_server.scheduler_runtime import get_runtime_status

    integrity = _facade().scheduler_integrity_status()
    active_required = set(_facade().required_scheduler_job_ids())
    monitored = {
        runtime_id: scheduler_id
        for (
            runtime_id,
            scheduler_id,
        ) in _facade()._CRITICAL_RUNTIME_JOB_TO_SCHEDULER_ID.items()
        if scheduler_id in active_required
    }
    runtime = get_runtime_status()
    rows = {
        str(item.get("job_id") or ""): dict(item)
        for item in runtime.get("jobs") or []
        if str(item.get("job_id") or "") in monitored
    }
    now = _facade().datetime.now(_facade().timezone.utc)
    unhealthy: list[str] = []
    recovering: list[str] = []
    jobs: list[dict[str, _facade().Any]] = []
    for runtime_id in sorted(monitored):
        row = rows.get(runtime_id) or {
            "job_id": runtime_id,
            "state": "missing",
            "last_status": None,
            "last_run_at": None,
            "last_success_at": None,
            "consecutive_failures": 0,
        }
        state = str(row.get("state") or "missing")
        deadline = _facade()._scheduler_startup_recovery_deadlines.get(runtime_id)
        if state in {"missing", "stale", "failing"} and deadline and (now <= deadline):
            row = {
                **row,
                "state": "recovering",
                "recovery_deadline": deadline.isoformat(),
            }
            recovering.append(runtime_id)
        elif state in {"missing", "stale", "failing"}:
            unhealthy.append(runtime_id)
        jobs.append(row)
    return {
        "ok": bool(runtime.get("ok")) and (not unhealthy),
        "integrity_ok": bool(integrity.get("ok")),
        "jobs": jobs,
        "unhealthy_jobs": unhealthy,
        "recovering_jobs": recovering,
        "generated_at": runtime.get("generated_at"),
    }


def _daily_pipeline_lock_wait_seconds(stage: str) -> int:
    env_name = f"MODSTORE_DAILY_PIPELINE_LOCK_WAIT_{stage.upper()}_SECONDS"
    defaults = {
        "daily_digest": 0,
        "daily_vibe_line_execute": 90 * 60,
        "release_train_orchestrator": 90 * 60,
    }
    return max(0, _facade()._env_int(env_name, defaults.get(stage, 0)))


def _run_daily_pipeline_stage(
    stage: str, fn: _facade().Callable[[], _facade().Any]
) -> _facade().Any:
    from modstore_server.daily_pipeline_lock import acquire_daily_pipeline_lock
    from modstore_server.scheduler_runtime import record_skip, track_job_run

    wait_seconds = _facade()._daily_pipeline_lock_wait_seconds(stage)
    with acquire_daily_pipeline_lock(stage=stage, timeout_seconds=wait_seconds) as lock:
        if not lock.get("acquired"):
            _facade().logger.warning(
                "daily pipeline stage skipped: stage=%s reason=%s wait=%s",
                stage,
                lock.get("reason"),
                wait_seconds,
            )
            record_skip(stage, reason=str(lock.get("reason") or ""))
            return {"ok": True, "skipped": True, **lock}
        with track_job_run(stage):
            return fn()


def _run_tracked_scheduler_job(
    job_id: str, fn: _facade().Callable[[], _facade().Any]
) -> _facade().Any:
    """Record non-daily scheduler jobs in the same runtime ledger.

    ``/api/scheduler/runtime`` reads ``scheduler_job_runs``. If only daily-pipeline
    stages write there, the scheduler can be alive and running employee loops while
    the runtime endpoint still claims only ``daily_digest`` exists.
    """
    from modstore_server.scheduler_runtime import track_job_run

    with track_job_run(job_id):
        return fn()


def _require_customer_value_source_ready(
    result: dict[str, _facade().Any],
) -> dict[str, _facade().Any]:
    if result.get("source_ready") is not True:
        owner = str(result.get("source_owner") or "unavailable")
        raise RuntimeError(f"customer_value_source_unready:{owner}")
    return result


def _run_authoritative_customer_value_job(
    fn: _facade().Callable[[], dict[str, _facade().Any]],
) -> dict[str, _facade().Any]:
    """Track source validation inside the scheduler job transaction.

    A reconciler function can return normally while reporting ``source_ready=false``.
    Validate that result before ``track_job_run`` closes, otherwise the runtime
    ledger records a false success and the immutable release gate can trust stale
    health even though the Java/PostgreSQL authority is unreachable.
    """
    return _facade()._run_tracked_scheduler_job(
        "customer_value_reconciler",
        lambda: _facade()._require_customer_value_source_ready(fn()),
    )


def _trigger_self_maintenance_from_incident(*, emitted: bool, source: str) -> None:
    if not emitted or not _facade()._env_bool(
        "MODSTORE_SELF_MAINTENANCE_EVENT_TRIGGER_ENABLED", True
    ):
        return
    try:
        from modstore_server.self_maintenance_loop_runner import (
            run_self_maintenance_loop,
        )

        result = run_self_maintenance_loop(
            triggered_by="incident_event",
            force=_facade()._env_bool("MODSTORE_SELF_MAINTENANCE_EVENT_FORCE", False),
            reason=source,
        )
        _facade().logger.info(
            "incident-driven self-maintenance finished: source=%s status=%s reason=%s",
            source,
            result.get("status"),
            result.get("reason") or (result.get("gate") or {}).get("reason"),
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("incident-driven self-maintenance failed: source=%s", source)


def _run_collector_with_timeout(
    fn: _facade().Callable[[], _facade().Any], *, label: str, timeout: float = 240.0
) -> _facade().Any:
    """运行 sync collector 并施加 wall-clock 超时。

    APScheduler ``BackgroundScheduler`` 在线程池里跑 sync 任务，没有运行中的事件循环；
    这里在 worker 线程里新建一个临时 loop，用 ``asyncio.wait_for`` + ``run_in_executor``
    包裹 sync 调用。超时后 ``wait_for`` 抛 ``TimeoutError``，被外层 ``except Exception``
    捕获并记日志——APScheduler 的 job 实例槽位（``max_instances=1``）随即释放，
    避免某个 collector 卡死后实例无限堆积。

    注意：CPython 无法强杀线程，超时后原 collector 仍可能在 executor 线程里跑（orphan），
    但已不再阻塞调度器。这是 Python 生态下 sync 调用超时的标准妥协。
    """

    async def _wrapped() -> _facade().Any:
        loop = _facade().asyncio.get_running_loop()
        return await _facade().asyncio.wait_for(loop.run_in_executor(None, fn), timeout=timeout)

    return _facade().asyncio.run(_wrapped())
