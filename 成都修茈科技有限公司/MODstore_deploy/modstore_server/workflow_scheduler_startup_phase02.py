"""Scheduler startup registration phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_scheduler")


def _register_scheduler_phase_02():

    def _autonomy_metrics_snapshot() -> None:
        try:
            from modstore_server.autonomy_metrics_job import (
                run_autonomy_metrics_snapshot,
            )

            result = _facade()._run_tracked_scheduler_job(
                "autonomy_metrics_snapshot", run_autonomy_metrics_snapshot
            )
            message = "autonomy metrics snapshot: date=%s severity=%s windows=%s" % (
                result.get("snapshot_date"),
                result.get("severity"),
                [
                    {
                        "days": item.get("window_days"),
                        "status": item.get("status"),
                        "veto_rate": item.get("veto_rate"),
                    }
                    for item in result.get("snapshots") or []
                ],
            )
            if result.get("severity") == "critical":
                _facade().logger.error(message)
            elif result.get("alert"):
                _facade().logger.warning(message)
            else:
                _facade().logger.info(message)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("autonomy metrics snapshot job failed")

    try:
        _facade()._scheduler.add_job(
            _autonomy_metrics_snapshot,
            _facade().CronTrigger(hour=0, minute=5, timezone="UTC"),
            id="autonomy_metrics_snapshot",
            replace_existing=True,
            next_run_time=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(seconds=15),
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register autonomy metrics snapshot cron failed")

    def _autonomy_posthoc_audit() -> None:
        try:
            from modstore_server.autonomy_posthoc_auditor import (
                run_autonomy_posthoc_audit,
            )

            result = _facade()._run_tracked_scheduler_job(
                "autonomy_posthoc_audit", run_autonomy_posthoc_audit
            )
            _facade().logger.info(
                "autonomy posthoc audit: candidates=%s audited=%s incomplete=%s",
                result.get("candidate_count"),
                result.get("audited_count"),
                result.get("incomplete_count"),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("autonomy posthoc audit job failed")

    try:
        _facade()._scheduler.add_job(
            _autonomy_posthoc_audit,
            _facade().IntervalTrigger(minutes=10),
            id="autonomy_posthoc_audit",
            replace_existing=True,
            next_run_time=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(seconds=45),
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register autonomy posthoc audit job failed")

    def _daily_digest_email() -> None:
        try:
            from modstore_server.daily_digest import run_daily_digest_email

            result = _facade()._run_daily_pipeline_stage("daily_digest", run_daily_digest_email)
            if result and (not result.get("ok")):
                _facade().logger.error(
                    "daily digest email job completed without delivery: reason=%s rows=%s",
                    result.get("reason"),
                    result.get("delivery_rows"),
                )
            else:
                _facade().logger.info(
                    "daily digest email job done: delivered=%s skipped=%s record_id=%s",
                    result.get("delivered") if isinstance(result, dict) else None,
                    result.get("skipped") if isinstance(result, dict) else None,
                    result.get("record_id") if isinstance(result, dict) else None,
                )
                if (
                    isinstance(result, dict)
                    and result.get("ok", True)
                    and (not result.get("skipped"))
                    and _facade()._env_bool("MODSTORE_DAILY_CHAIN_EVENT_TRIGGER_ENABLED", True)
                ):
                    record_id = result.get("record_id")
                    from modstore_server.daily_release_train_orchestrator_job import (
                        run_daily_release_train_orchestrator_job,
                    )
                    from modstore_server.daily_vibe_line_execute_job import (
                        run_daily_vibe_line_execute_job,
                    )

                    vibe_result = _facade()._run_daily_pipeline_stage(
                        "daily_vibe_line_execute",
                        lambda: run_daily_vibe_line_execute_job(record_id=record_id),
                    )
                    _facade().logger.info(
                        "daily chain event: vibe_line record_id=%s ok=%s skipped=%s",
                        record_id,
                        vibe_result.get("ok") if isinstance(vibe_result, dict) else None,
                        vibe_result.get("skipped") if isinstance(vibe_result, dict) else None,
                    )
                    release_result = _facade()._run_daily_pipeline_stage(
                        "release_train_orchestrator",
                        lambda: run_daily_release_train_orchestrator_job(record_id=record_id),
                    )
                    _facade().logger.info(
                        "daily chain event: release_train record_id=%s ok=%s skipped=%s",
                        record_id,
                        release_result.get("ok") if isinstance(release_result, dict) else None,
                        release_result.get("skipped") if isinstance(release_result, dict) else None,
                    )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily digest email job failed")

    try:
        from modstore_server.daily_digest import cron_trigger_for_digest

        _facade()._scheduler.add_job(
            _daily_digest_email,
            cron_trigger_for_digest(),
            id="daily_ops_digest_email",
            replace_existing=True,
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
            **_facade()._startup_recovery_kwargs("daily_digest", delay_seconds=20),
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register daily digest cron failed")

    def _daily_vibe_line_execute_job() -> None:
        try:
            from modstore_server.daily_vibe_line_execute_job import (
                run_daily_vibe_line_execute_job,
            )

            _facade()._run_daily_pipeline_stage(
                "daily_vibe_line_execute", run_daily_vibe_line_execute_job
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily vibe line execute job failed")

    try:
        from modstore_server.daily_vibe_line_execute_job import (
            cron_trigger_for_vibe_line_execute,
        )

        if _facade()._env_bool("MODSTORE_DAILY_CHAIN_CRON_FALLBACK_ENABLED", False):
            _facade()._scheduler.add_job(
                _daily_vibe_line_execute_job,
                cron_trigger_for_vibe_line_execute(),
                id="daily_vibe_line_execute_job",
                replace_existing=True,
                misfire_grace_time=_facade()._business_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
            )
        else:
            _facade().logger.info(
                "daily vibe line cron disabled; digest completion event is primary"
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register daily vibe line execute cron failed")

    def _daily_orchestrator_job() -> None:
        try:
            from modstore_server.daily_orchestrator_job import (
                run_daily_orchestrator_job,
            )

            run_daily_orchestrator_job()
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily orchestrator job failed")

    try:
        from modstore_server.daily_orchestrator_job import cron_trigger_for_orchestrator

        _facade()._scheduler.add_job(
            _daily_orchestrator_job,
            cron_trigger_for_orchestrator(),
            id="daily_orchestrator_job",
            replace_existing=True,
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register daily orchestrator cron failed")

    def _self_maintenance_loop_job() -> None:
        try:

            def _run() -> None:
                from modstore_server.self_maintenance_loop_runner import (
                    run_self_maintenance_loop,
                )

                result = run_self_maintenance_loop(triggered_by="scheduler")
                _facade().logger.info("self-maintenance loop finished: %s", result)

            _facade()._run_tracked_scheduler_job("self_maintenance_loop_daily", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("self-maintenance loop job failed")

    try:
        from modstore_server.self_maintenance_loop_runner import (
            cron_trigger_for_self_maintenance,
        )

        _facade()._scheduler.add_job(
            _self_maintenance_loop_job,
            cron_trigger_for_self_maintenance(),
            id="self_maintenance_loop_daily",
            replace_existing=True,
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
            **_facade()._startup_recovery_kwargs("self_maintenance_loop_daily", delay_seconds=40),
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register self-maintenance loop cron failed")

    def _self_maintenance_heartbeat_job() -> None:
        try:

            def _run() -> None:
                from modstore_server.self_maintenance_loop_runner import (
                    record_self_maintenance_heartbeat,
                )

                receipt = record_self_maintenance_heartbeat()
                _facade().logger.info(
                    "self-maintenance heartbeat: status=%s reason=%s",
                    receipt.get("status"),
                    (receipt.get("gate") or {}).get("reason"),
                )

            _facade()._run_tracked_scheduler_job("self_maintenance_heartbeat", _run)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("self-maintenance heartbeat failed")

    _facade()._scheduler.add_job(
        _self_maintenance_heartbeat_job,
        _facade().IntervalTrigger(
            minutes=max(
                15,
                _facade()._env_int("MODSTORE_SELF_MAINTENANCE_HEARTBEAT_MINUTES", 120),
            )
        ),
        id="self_maintenance_heartbeat",
        replace_existing=True,
        next_run_time=_facade().datetime.now(_facade().timezone.utc),
        coalesce=True,
        max_instances=1,
    )

    def _daily_release_train_orchestrator_job() -> None:
        try:
            from modstore_server.daily_release_train_orchestrator_job import (
                run_daily_release_train_orchestrator_job,
            )

            _facade()._run_daily_pipeline_stage(
                "release_train_orchestrator", run_daily_release_train_orchestrator_job
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily release_train orchestrator job failed")

    try:
        from modstore_server.daily_release_train_orchestrator_job import (
            cron_trigger_for_release_train_orchestrator,
        )

        if _facade()._env_bool("MODSTORE_DAILY_CHAIN_CRON_FALLBACK_ENABLED", False):
            _facade()._scheduler.add_job(
                _daily_release_train_orchestrator_job,
                cron_trigger_for_release_train_orchestrator(),
                id="daily_release_train_orchestrator_job",
                replace_existing=True,
                misfire_grace_time=_facade()._business_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
            )
        else:
            _facade().logger.info(
                "daily release_train cron disabled; digest completion event is primary"
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register daily release_train orchestrator cron failed")

    def _daily_backup_job() -> None:
        try:
            from modstore_server.daily_backup_job import run_daily_backup_job

            r = run_daily_backup_job()
            _facade().logger.info(
                "daily backup job: ok=%s dir=%s", r.get("ok"), r.get("backup_dir")
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("daily backup job failed")

    try:
        from modstore_server.daily_backup_job import cron_trigger_for_backup

        _facade()._scheduler.add_job(
            _daily_backup_job,
            cron_trigger_for_backup(),
            id="daily_backup_job",
            replace_existing=True,
            misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register daily backup cron failed")

    def _dr_recovery_probe_job() -> None:
        try:
            from modstore_server.dr_recovery_probe_job import run_dr_recovery_probe

            r = run_dr_recovery_probe()
            if not r.get("skipped"):
                _facade().logger.info(
                    "dr recovery probe: ok=%s recovered=%s retry=%s escalated=%s",
                    r.get("ok"),
                    r.get("recovered"),
                    r.get("probe_retry_count"),
                    r.get("escalated"),
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("dr recovery probe job failed")

    try:
        probe_mins = int(_facade().os.environ.get("MODSTORE_DR_PROBE_INTERVAL_MINUTES", "30"))
    except ValueError:
        probe_mins = 30
    _facade()._scheduler.add_job(
        _dr_recovery_probe_job,
        _facade().IntervalTrigger(minutes=max(5, probe_mins)),
        id="dr_recovery_probe_job",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
