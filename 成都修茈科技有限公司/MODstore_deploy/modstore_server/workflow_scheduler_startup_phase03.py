"""Scheduler startup registration phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_scheduler")


def _register_scheduler_phase_03():

    def _time_rail_observability_job() -> None:
        global _LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS
        global _LAST_TIME_RAIL_OBSERVABILITY_MISSING
        try:
            from modstore_server.time_rail_workflow import (
                collect_node_runtime_status,
                sync_missing_evidence_backlog,
            )

            threshold = int(
                _facade().os.environ.get("MODSTORE_TIME_RAIL_MISSING_EVIDENCE_THRESHOLD", "3")
            )
            sync_limit = int(
                _facade().os.environ.get("MODSTORE_TIME_RAIL_MISSING_EVIDENCE_LIMIT", "32")
            )
            min_queue_gap = int(
                _facade().os.environ.get("MODSTORE_TIME_RAIL_MAINTENANCE_MIN_QUEUE_GAP", "1")
            )
            cooldown_seconds = int(
                _facade().os.environ.get(
                    "MODSTORE_TIME_RAIL_MAINTENANCE_COOLDOWN_SECONDS", str(10 * 60)
                )
            )
            if threshold < 1:
                threshold = 1
            if sync_limit < 1:
                sync_limit = 1
            if min_queue_gap < 1:
                min_queue_gap = 1
            if cooldown_seconds < 0:
                cooldown_seconds = 10 * 60
            now = _facade().time.time()
            if (
                _facade()._LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS > 0
                and now - _facade()._LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS < cooldown_seconds
            ):
                _facade().logger.info(
                    "time rail observability sync skipped: cooldown_not_elapsed",
                    extra={"cooldown_seconds": cooldown_seconds},
                )
                return
            status = collect_node_runtime_status()
            missing_nodes = status.get("missing_evidence") or []
            backlog_nodes = status.get("maintenance_backlog") or []
            missing = len(missing_nodes)
            queued = len(backlog_nodes)
            remaining = missing - queued
            if missing < threshold:
                _facade().logger.info(
                    "time rail observability sync skipped: below_threshold",
                    extra={"missing": missing, "threshold": threshold},
                )
                return
            if remaining < min_queue_gap:
                _facade().logger.info(
                    "time rail observability sync skipped: queue_gap_not_reached",
                    extra={"remaining": remaining, "min_queue_gap": min_queue_gap},
                )
                return
            if (
                _facade()._LAST_TIME_RAIL_OBSERVABILITY_MISSING >= 0
                and missing <= _facade()._LAST_TIME_RAIL_OBSERVABILITY_MISSING
                and (now - _facade()._LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS < cooldown_seconds)
            ):
                _facade().logger.info(
                    "time rail observability sync skipped: no_new_missing_and_cooldown",
                    extra={"missing": missing},
                )
                return
            r = sync_missing_evidence_backlog(limit=sync_limit)
            _facade()._LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS = now
            _facade()._LAST_TIME_RAIL_OBSERVABILITY_MISSING = missing
            if r.get("added"):
                _facade().logger.info(
                    "time rail observability sync: added=%s missing=%s queued=%s",
                    r.get("added"),
                    r.get("total_missing"),
                    queued,
                )
            else:
                _facade().logger.info(
                    "time rail observability sync: no_new_backlog missing=%s queued=%s",
                    missing,
                    queued,
                )
        except ValueError:
            _facade().logger.exception("time rail observability sync env parse failed")
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("time rail observability sync failed")

    _facade()._scheduler.add_job(
        _time_rail_observability_job,
        _facade().CronTrigger(hour=3, minute=0),
        id="time_rail_observability_sync",
        replace_existing=True,
        misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )

    def _inbox_poll_job() -> None:
        try:

            def _run() -> None:
                from modstore_server.inbox_poller import poll_inbox_once

                poll_inbox_once()

            _facade()._run_tracked_scheduler_job("inbox_approval_poll", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("inbox poll job failed")

    try:
        poll_secs = int(_facade().os.environ.get("MODSTORE_INBOX_POLL_SECONDS", "120"))
    except ValueError:
        poll_secs = 120
    poll_secs = max(60, poll_secs)
    _facade()._scheduler.add_job(
        _inbox_poll_job,
        _facade().IntervalTrigger(seconds=poll_secs),
        id="inbox_approval_poll",
        replace_existing=True,
    )

    def _email_intake_poll_job() -> None:
        try:

            def _run() -> None:
                from modstore_server.email_intake import poll_email_intake_once

                out = poll_email_intake_once()
                if not out.get("ok"):
                    _facade().logger.warning(
                        "email intake poll failed: %s", out.get("error") or "unknown"
                    )

            _facade()._run_tracked_scheduler_job("email_intake_poll", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("email intake poll job failed")

    try:
        intake_secs = int(_facade().os.environ.get("MODSTORE_EMAIL_INTAKE_POLL_SECONDS", "120"))
    except ValueError:
        intake_secs = 120
    _facade()._scheduler.add_job(
        _email_intake_poll_job,
        _facade().IntervalTrigger(seconds=max(30, intake_secs)),
        id="email_intake_poll",
        replace_existing=True,
    )

    def _employee_autonomy_dispatch_loop() -> None:
        try:

            def _run() -> None:
                from modstore_server.employee_autonomy_service import (
                    dispatch_pending_brief_tasks,
                    dispatch_pending_suggestions,
                )

                try:
                    brief_limit = int(
                        _facade().os.environ.get("MODSTORE_BRIEF_DISPATCH_BATCH", "20")
                    )
                except ValueError:
                    brief_limit = 20
                try:
                    sug_limit = int(
                        _facade().os.environ.get("MODSTORE_SUGGESTION_DISPATCH_BATCH", "20")
                    )
                except ValueError:
                    sug_limit = 20
                b = dispatch_pending_brief_tasks(limit=max(1, min(brief_limit, 100)))
                s = dispatch_pending_suggestions(limit=max(1, min(sug_limit, 100)))
                _facade().logger.info(
                    "employee autonomy dispatch: brief processed=%s done=%s failed=%s; suggestion processed=%s ok=%s skipped=%s",
                    b.get("processed"),
                    b.get("done"),
                    b.get("failed"),
                    s.get("processed"),
                    s.get("ok_count"),
                    s.get("skipped"),
                )

            _facade()._run_tracked_scheduler_job("employee_autonomy_dispatch_loop", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("employee autonomy dispatch loop failed")

    try:
        loop_seconds = int(
            _facade().os.environ.get("MODSTORE_EMPLOYEE_AUTONOMY_LOOP_SECONDS", "120")
        )
    except ValueError:
        loop_seconds = 120
    _facade()._scheduler.add_job(
        _employee_autonomy_dispatch_loop,
        _facade().IntervalTrigger(seconds=max(30, loop_seconds)),
        id="employee_autonomy_dispatch_loop",
        replace_existing=True,
    )

    def _llm_route_autopilot_job() -> None:
        try:

            def _run() -> None:
                from modstore_server.llm_runtime_autopilot import (
                    run_llm_route_autopilot,
                )

                out = run_llm_route_autopilot(triggered_by="scheduler")
                _facade().logger.info(
                    "llm route autopilot: ok=%s action=%s reason=%s target=%s",
                    out.get("ok"),
                    out.get("action"),
                    out.get("reason"),
                    out.get("target"),
                )

            _facade()._run_tracked_scheduler_job("llm_route_autopilot", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("llm route autopilot failed")

    try:
        from modstore_server.llm_runtime_autopilot import autopilot_enabled

        if autopilot_enabled():
            autopilot_minutes = max(
                1, _facade()._env_int("MODSTORE_LLM_AUTOPILOT_INTERVAL_MINUTES", 5)
            )
            _facade()._scheduler.add_job(
                _llm_route_autopilot_job,
                _facade().IntervalTrigger(minutes=autopilot_minutes),
                id="llm_route_autopilot",
                replace_existing=True,
                next_run_time=_facade().datetime.now(_facade().timezone.utc)
                + _facade().timedelta(seconds=5),
                misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
            )
        else:
            _facade().logger.info("llm route autopilot disabled")
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register llm route autopilot failed")

    def _employee_evolution_scan_loop() -> None:
        try:

            def _run() -> None:
                from modstore_server.employee_autonomy_service import (
                    run_employee_evolution_scan,
                )

                try:
                    lookback = int(
                        _facade().os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_LOOKBACK_HOURS", "24")
                    )
                except ValueError:
                    lookback = 24
                try:
                    min_fail = int(
                        _facade().os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_MIN_FAILURES", "3")
                    )
                except ValueError:
                    min_fail = 3
                try:
                    lim = int(
                        _facade().os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_SCAN_LIMIT", "20")
                    )
                except ValueError:
                    lim = 20
                out = run_employee_evolution_scan(
                    lookback_hours=lookback,
                    min_failures=min_fail,
                    limit=lim,
                    triggered_by="scheduler",
                )
                _facade().logger.info(
                    "employee evolution scan: processed=%s created=%s enabled=%s quota_failures=%s circuit_broken=%s",
                    out.get("processed"),
                    out.get("created"),
                    out.get("enabled"),
                    out.get("quota_failures"),
                    out.get("circuit_broken"),
                )

            _facade()._run_tracked_scheduler_job("employee_evolution_scan_loop", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("employee evolution scan loop failed")

    try:
        evolution_minutes = int(
            _facade().os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_INTERVAL_MINUTES", "60")
        )
    except ValueError:
        evolution_minutes = 60
    _facade()._scheduler.add_job(
        _employee_evolution_scan_loop,
        _facade().IntervalTrigger(minutes=max(10, evolution_minutes)),
        id="employee_evolution_scan_loop",
        replace_existing=True,
    )
    _facade()._register_extensions(
        _facade()._scheduler, track_job=_facade()._run_tracked_scheduler_job
    )

    def _employee_health_scan_loop() -> None:
        try:

            def _run() -> None:
                from modstore_server.employee_health_scan import run_health_scan

                out = run_health_scan()
                if out.get("scanned"):
                    _facade().logger.info(
                        "employee health scan: warned=%d deactivated=%d",
                        len(out.get("warned") or []),
                        len(out.get("deactivated") or []),
                    )

            _facade()._run_tracked_scheduler_job("employee_health_scan_loop", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("employee health scan loop failed")

    try:
        health_minutes = int(_facade().os.environ.get("MODSTORE_HEALTH_SCAN_INTERVAL_MIN", "30"))
    except ValueError:
        health_minutes = 30
    _facade()._scheduler.add_job(
        _employee_health_scan_loop,
        _facade().IntervalTrigger(minutes=max(5, health_minutes)),
        id="employee_health_scan_loop",
        replace_existing=True,
    )

    def _boss_daily_im_report_job() -> None:
        try:

            def _run() -> None:
                from modstore_server.boss_daily_im_report import (
                    send_boss_daily_im_report,
                )

                out = send_boss_daily_im_report()
                _facade().logger.info(
                    "boss daily im report: ok=%s sent=%s skipped=%s",
                    out.get("ok"),
                    out.get("sent"),
                    out.get("skipped_reason") or "-",
                )

            _facade()._run_tracked_scheduler_job("boss_daily_im_report", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("boss daily im report job failed")

    try:
        from modstore_server.boss_daily_im_report import report_enabled, report_hour_utc

        if report_enabled():
            _facade()._scheduler.add_job(
                _boss_daily_im_report_job,
                _facade().CronTrigger(hour=report_hour_utc(), minute=15),
                id="boss_daily_im_report",
                replace_existing=True,
                misfire_grace_time=_facade()._business_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
                **_facade()._startup_recovery_kwargs("boss_daily_im_report", delay_seconds=60),
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register boss daily im report cron failed")
    try:
        _facade()._register_employee_cron_jobs()
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register employee cron jobs failed")
