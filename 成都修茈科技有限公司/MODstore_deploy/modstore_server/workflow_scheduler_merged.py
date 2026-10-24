"""Auto-merged part* modules (debt24)."""
from __future__ import annotations
import importlib
from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from workflow_scheduler_part01.py ---
"""Implementation extracted from the public facade module."""


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
        from modstore_server.maintenance_loop.coordinator import (
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

# --- from workflow_scheduler_part02.py ---
"""Implementation extracted from the public facade module."""


import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_scheduler")


def _employee_auto_cron_enabled() -> bool:
    return _facade().os.environ.get("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _employee_cron_job_id(employee_id: str) -> str:
    safe = "".join((c for c in employee_id or "" if c.isalnum() or c in ("-", "_")))[:64]
    return f"{_facade()._EMPLOYEE_CRON_JOB_PREFIX}{safe or 'unknown'}"


def _extract_employee_schedule(manifest: dict) -> _facade().Optional[dict]:
    """从员工 manifest 中提取 schedule 配置。

    支持：
      - ``employee_config_v2.schedule = {"cron": "0 9 * * *", "task_brief": "..."}``
      - ``schedule = {...}`` （顶层兼容）
      - ``employee_config_v2.schedule.interval_seconds = 600`` （间隔触发）
    """
    if not isinstance(manifest, dict):
        return None
    ev2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    sched = ev2.get("schedule") if isinstance(ev2.get("schedule"), dict) else None
    if sched is None and isinstance(manifest.get("schedule"), dict):
        sched = manifest["schedule"]
    return sched if isinstance(sched, dict) else None


def _employee_project_root() -> str:
    """Resolve the root used by yuangon workspace-policy globs.

    Desktop source checkouts add one company directory above
    ``MODstore_deploy`` while packaged autonomy runtimes do not.  Passing the
    monorepo parent makes perception scan the entire checkout and none of the
    employee scopes match.
    """
    configured = str(_facade().os.environ.get("MODSTORE_DUTY_PROJECT_ROOT") or "").strip()
    if configured:
        target = _facade().Path(configured).expanduser().resolve()
        if target.is_dir():
            return str(target)
        _facade().logger.error("employee duty project root missing: %s", target)
        return ""
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = _facade().Path(repo_root()).resolve()
    except RECOVERABLE_ERRORS:
        return ""
    if (root / "MODstore_deploy").is_dir():
        return str(root)
    company_root = root / "成都修茈科技有限公司"
    if (company_root / "MODstore_deploy").is_dir():
        return str(company_root)
    return str(root)


def _register_employee_cron_jobs() -> None:
    """Register employee shifts from manifest or the 55-role work-contract SSOT.

    A manifest proves that an employee pack exists; it does not assign work.
    Explicit manifest schedules remain authoritative, while the central duty
    contract supplies schedules for the rest of the roster.
    """
    if _facade()._scheduler is None:
        return
    if not _facade()._employee_auto_cron_enabled():
        _facade().logger.info("employee auto cron disabled (MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED=0)")
        return
    try:
        import importlib

        task_router = importlib.import_module("modstore_server.task_router")
        employee_runtime = importlib.import_module("modstore_server.employee_runtime")
        _load_all_employee_profiles = task_router._load_all_employee_profiles
        load_employee_pack = employee_runtime.load_employee_pack
        from modstore_server.duty_workforce_contracts import (
            contract_schedule,
            workforce_contract_map,
        )
        from modstore_server.employee_cron_registration import (
            build_employee_cron_candidates,
        )
        from modstore_server.employee_cron_registration_ledger import (
            defer_employee_cron_if_approval_required,
            reconcile_employee_cron_registrations,
            record_employee_cron_registration,
        )
        from modstore_server.models import get_session_factory
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("employee cron: import failed")
        return
    try:
        work_contracts = workforce_contract_map()
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("employee cron: duty work contracts unavailable")
        work_contracts = {}
    candidates = build_employee_cron_candidates(
        profiles=_load_all_employee_profiles(),
        work_contracts=work_contracts,
        load_employee_pack=load_employee_pack,
        session_factory=get_session_factory(),
    )
    if not candidates:
        _facade().logger.info("employee cron: no catalog profiles or duty contracts found")
        return
    registered = 0
    skipped = 0
    represented_ids: set[str] = set()
    for emp_id, manifest, contract in candidates:
        sched = _facade()._extract_employee_schedule(manifest) or contract_schedule(contract)
        if not sched:
            skipped += 1
            continue
        cron_expr = str(sched.get("cron") or "").strip()
        interval_seconds = sched.get("interval_seconds")
        task_brief = str(sched.get("task_brief") or f"{emp_id} 日常轮值").strip()
        enabled = sched.get("enabled", True)
        if not enabled:
            skipped += 1
            continue
        if defer_employee_cron_if_approval_required(emp_id, contract):
            represented_ids.add(emp_id)
            continue
        trigger = None
        try:
            if cron_expr:
                trigger = _facade().CronTrigger.from_crontab(cron_expr)
            elif isinstance(interval_seconds, (int, float)) and interval_seconds >= 60:
                trigger = _facade().IntervalTrigger(seconds=int(interval_seconds))
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("employee cron: invalid trigger for %s: %s", emp_id, exc)
            skipped += 1
            continue
        if trigger is None:
            skipped += 1
            continue
        job_id = _facade()._employee_cron_job_id(emp_id)
        eid_local = emp_id
        brief_local = task_brief
        contract_local = dict(contract)
        schedule_source_local = str(sched.get("source") or "manifest")

        def _runner(
            eid: str = eid_local,
            brief: str = brief_local,
            work_contract: dict = contract_local,
            schedule_source: str = schedule_source_local,
        ) -> None:
            try:
                from modstore_server.employee_duty_cron_runtime import (
                    execute_employee_cron_duty,
                )

                execute_employee_cron_duty(
                    employee_id=eid,
                    task_brief=brief,
                    work_contract=work_contract,
                    schedule_source=schedule_source,
                    project_root=_facade()._employee_project_root(),
                )
            except RECOVERABLE_ERRORS:
                _facade().logger.exception("employee cron job failed: %s", eid)

        try:
            _facade()._scheduler.add_job(_runner, trigger, id=job_id, replace_existing=True)
            registered += 1
            represented_ids.add(emp_id)
            record_employee_cron_registration(emp_id, status="success")
            _facade().logger.info(
                "employee cron registered: %s -> %s",
                emp_id,
                cron_expr or f"interval {interval_seconds}s",
            )
        except RECOVERABLE_ERRORS as exc:
            record_employee_cron_registration(
                emp_id, status="failed", error=f"registration failed: {exc!r}"
            )
            _facade().logger.exception("employee cron add_job failed: %s", emp_id)
            skipped += 1
    try:
        reconcile_employee_cron_registrations(represented_ids)
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("employee cron: registration ledger reconciliation failed")
    _facade().logger.info("employee cron: registered=%d skipped=%d", registered, skipped)


def list_employee_cron_jobs() -> list:
    """返回当前已注册的员工 cron 任务清单（前端缺岗看板用）。"""
    if _facade()._scheduler is None:
        return []
    try:
        from modstore_server.duty_workforce_contracts import workforce_contract_map

        work_contracts = workforce_contract_map()
    except RECOVERABLE_ERRORS:
        work_contracts = {}
    out = []
    for job in _facade()._scheduler.get_jobs():
        jid = job.id or ""
        if not jid.startswith(_facade()._EMPLOYEE_CRON_JOB_PREFIX):
            continue
        contract = work_contracts.get(jid[len(_facade()._EMPLOYEE_CRON_JOB_PREFIX) :]) or {}
        out.append(
            {
                "job_id": jid,
                "employee_id": jid[len(_facade()._EMPLOYEE_CRON_JOB_PREFIX) :],
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "contract_mode": str(contract.get("mode") or ""),
                "risk_level": str(contract.get("risk_level") or ""),
                "mission": str(contract.get("mission") or ""),
            }
        )
    return out


def reload_employee_cron_jobs() -> dict:
    """重新扫描 catalog 并刷新员工 cron 注册（修改 manifest / 上架新员工后调用）。"""
    if _facade()._scheduler is None:
        return {"ok": False, "error": "scheduler not started"}
    for job in list(_facade()._scheduler.get_jobs()):
        if (job.id or "").startswith(_facade()._EMPLOYEE_CRON_JOB_PREFIX):
            try:
                _facade()._scheduler.remove_job(job.id)
            except RECOVERABLE_ERRORS:
                pass
    _facade()._register_employee_cron_jobs()
    return {"ok": True, "active_jobs": _facade().list_employee_cron_jobs()}


def stop_scheduler() -> None:
    global _scheduler, _scheduler_registration_complete, _scheduler_startup_probe_failures
    global _scheduler_startup_recovery_deadlines
    if _facade()._scheduler is not None:
        _facade()._scheduler.shutdown(wait=False)
        _facade()._scheduler = None
        _facade().logger.info("workflow scheduler stopped")
    _facade()._scheduler_registration_complete = False
    _facade()._scheduler_startup_probe_failures = []
    _facade()._scheduler_startup_recovery_deadlines = {}


def _job_id(trigger_id: int) -> str:
    return f"{_facade()._JOB_PREFIX}{trigger_id}"


def _load_triggers() -> None:
    if _facade()._scheduler is None:
        return
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().WorkflowTrigger)
            .filter(
                _facade().WorkflowTrigger.trigger_type == "cron",
                _facade().WorkflowTrigger.is_active.is_(True),
            )
            .all()
        )
    for t in rows:
        _facade()._register_cron_trigger(t.id, t.workflow_id, t.user_id, t.config_json or "{}")


def _register_cron_trigger(
    trigger_id: int, workflow_id: int, user_id: int, config_json: str
) -> None:
    global _scheduler
    if _facade()._scheduler is None:
        return
    try:
        config = _facade().json.loads(config_json or "{}")
    except _facade().json.JSONDecodeError:
        config = {}
    cron_expr = str(config.get("cron") or config.get("schedule") or "0 0 * * *").strip()
    wf_id = workflow_id
    uid = user_id

    def job_wrapper() -> None:
        try:
            _facade().run_workflow_for_trigger(workflow_id=wf_id, user_id=uid, input_data={})
        except RECOVERABLE_ERRORS as e:
            _facade().logger.exception("cron workflow failed workflow_id=%s: %s", wf_id, e)

    jid = _facade()._job_id(trigger_id)
    try:
        _facade()._scheduler.remove_job(jid)
    except RECOVERABLE_ERRORS:
        pass
    try:
        _facade()._scheduler.add_job(
            job_wrapper,
            _facade().CronTrigger.from_crontab(cron_expr),
            id=jid,
            replace_existing=True,
        )
        _facade().logger.info(
            "registered cron trigger id=%s workflow=%s expr=%s",
            trigger_id,
            wf_id,
            cron_expr,
        )
    except RECOVERABLE_ERRORS as e:
        _facade().logger.warning("invalid cron for trigger id=%s: %s", trigger_id, e)


def unregister_cron_trigger(trigger_id: int) -> None:
    global _scheduler
    if _facade()._scheduler is None:
        return
    try:
        _facade()._scheduler.remove_job(_facade()._job_id(trigger_id))
    except RECOVERABLE_ERRORS:
        pass


def refresh_cron_trigger(trigger_id: int) -> None:
    sf = _facade().get_session_factory()
    with sf() as session:
        t = (
            session.query(_facade().WorkflowTrigger)
            .filter(_facade().WorkflowTrigger.id == trigger_id)
            .first()
        )
    if not t or not t.is_active or (t.trigger_type or "").lower() != "cron":
        _facade().unregister_cron_trigger(trigger_id)
        return
    _facade()._register_cron_trigger(t.id, t.workflow_id, t.user_id, t.config_json or "{}")


def reload_all_cron_triggers() -> None:
    global _scheduler
    if _facade()._scheduler is None:
        return
    for job in list(_facade()._scheduler.get_jobs()):
        jid = job.id or ""
        if jid.startswith(_facade()._JOB_PREFIX):
            try:
                _facade()._scheduler.remove_job(jid)
            except RECOVERABLE_ERRORS:
                pass
    _facade()._load_triggers()
