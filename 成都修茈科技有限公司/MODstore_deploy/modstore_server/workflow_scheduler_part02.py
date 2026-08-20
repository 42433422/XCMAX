# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

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
