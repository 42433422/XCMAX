"""Scheduler startup registration phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_scheduler")


def _register_scheduler_phase_04():
    try:
        from modstore_server.duty_workforce_burnin import (
            burn_in_execution_enabled,
            burn_in_scheduler_enabled,
            run_burn_in,
        )

        if burn_in_scheduler_enabled():

            def _duty_workforce_burn_in_job() -> None:
                try:
                    out = _facade()._run_tracked_scheduler_job(
                        "duty_workforce_burnin",
                        lambda: run_burn_in(dry_run=not burn_in_execution_enabled()),
                    )
                    _facade().logger.info(
                        "duty workforce burn-in dry_run=%s selected=%s accepted=%s blocked=%s",
                        out.get("dry_run"),
                        out.get("selected_count"),
                        out.get("accepted_receipt_count", 0),
                        out.get("execution_blocked", False),
                    )
                except RECOVERABLE_ERRORS:
                    _facade().logger.exception("duty workforce burn-in failed")

            _facade()._scheduler.add_job(
                _duty_workforce_burn_in_job,
                _facade().IntervalTrigger(
                    minutes=max(
                        15,
                        min(
                            _facade()._env_int("MODSTORE_EMPLOYEE_BURN_IN_INTERVAL_MINUTES", 60),
                            24 * 60,
                        ),
                    )
                ),
                id="duty_workforce_burnin",
                replace_existing=True,
                misfire_grace_time=_facade()._business_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register duty workforce burn-in failed")

    def _duty_workforce_learning_job() -> None:
        try:
            from modstore_server.duty_workforce_learning import (
                run_duty_workforce_learning,
            )

            out = _facade()._run_tracked_scheduler_job(
                "duty_workforce_learning", run_duty_workforce_learning
            )
            _facade().logger.info(
                "duty workforce learning rows=%s unresolved=%s resolved=%s written=%s",
                out.get("audit_row_count", 0),
                out.get("unresolved_employee_count", 0),
                out.get("resolved_pair_count", 0),
                out.get("knowledge_written_count", 0),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("duty workforce learning failed")

    try:
        _facade()._scheduler.add_job(
            _duty_workforce_learning_job,
            _facade().IntervalTrigger(minutes=15),
            id="duty_workforce_learning",
            replace_existing=True,
            next_run_time=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(seconds=75),
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register duty workforce learning failed")

    def _self_evolution_metrics_job() -> None:
        try:
            from modstore_server.self_evolution_metrics_job import (
                run_self_evolution_metrics_snapshot,
            )

            out = _facade()._run_tracked_scheduler_job(
                "self_evolution_metrics", run_self_evolution_metrics_snapshot
            )
            _facade().logger.info(
                "self evolution metrics week=%s skipped=%s coverage=%s tests=%s debt=%s",
                out.get("week"),
                out.get("skipped", False),
                out.get("backend_coverage"),
                out.get("pytest_passed"),
                out.get("type_debt"),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("self evolution metrics job failed")

    try:
        _facade()._scheduler.add_job(
            _self_evolution_metrics_job,
            _facade().CronTrigger(day_of_week="sun", hour=0, minute=35, timezone="UTC"),
            id="self_evolution_metrics",
            replace_existing=True,
            next_run_time=_facade().datetime.now(_facade().timezone.utc)
            + _facade().timedelta(seconds=105),
            misfire_grace_time=_facade()._business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register self evolution metrics job failed")

    def _auto_fix_loop_job() -> None:
        try:
            from modstore_server.auto_fix_loop import register_auto_fix_event_bindings

            register_auto_fix_event_bindings()
        except RECOVERABLE_ERRORS:
            _facade().logger.debug("auto_fix event bindings registration skipped")

    _facade()._scheduler.add_job(
        _auto_fix_loop_job,
        _facade().IntervalTrigger(hours=1),
        id="auto_fix_event_bindings_refresh",
        replace_existing=True,
    )

    def _auto_version_bump_job() -> None:
        try:
            from modstore_server.auto_version_bump import auto_version_bump
            from modstore_server.integrations.ops_action_handlers import repo_root

            root = str(repo_root())
            out = auto_version_bump(root)
            if out.get("ok") and (not out.get("skipped")):
                _facade().logger.info(
                    "auto version bump: %s → %s (anchors=%d)",
                    out.get("old_version"),
                    out.get("new_version"),
                    out.get("anchors_synced"),
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("auto version bump job failed")

    _facade()._scheduler.add_job(
        _auto_version_bump_job,
        _facade().CronTrigger(hour=6, minute=0),
        id="auto_version_bump_daily",
        replace_existing=True,
    )

    def _telemetry_backlog_scan_job() -> None:
        try:
            from modstore_server.telemetry_backlog_loop import run_telemetry_scan

            out = run_telemetry_scan()
            if out.get("ok") and (not out.get("skipped")):
                _facade().logger.info(
                    "telemetry backlog scan: signals=%d ingested=%d",
                    out.get("signals_found"),
                    out.get("signals_ingested"),
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("telemetry backlog scan job failed")

    _facade()._scheduler.add_job(
        _telemetry_backlog_scan_job,
        _facade().IntervalTrigger(hours=6),
        id="telemetry_backlog_scan",
        replace_existing=True,
    )

    def _predictive_maintenance_job() -> None:
        try:
            from modstore_server.predictive_maintenance import (
                run_predictive_maintenance_once,
            )

            out = run_predictive_maintenance_once()
            _facade().logger.info(
                "predictive maintenance: predictions=%s emitted=%s path=%s",
                len(out.get("predictions") or []),
                out.get("emitted_incident"),
                out.get("forecast_path"),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("predictive maintenance job failed")

    _facade()._scheduler.add_job(
        _predictive_maintenance_job,
        _facade().IntervalTrigger(
            hours=max(
                1,
                _facade()._env_int("MODSTORE_PREDICTIVE_MAINTENANCE_INTERVAL_HOURS", 6),
            )
        ),
        id="predictive_maintenance_forecast",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    def _kb_self_maintenance_job() -> None:
        try:
            from modstore_server.kb_self_maintenance import run_kb_self_maintenance_once

            out = run_kb_self_maintenance_once()
            _facade().logger.info(
                "kb self-maintenance: actions=%s dry_run=%s audit=%s",
                out.get("action_count"),
                out.get("dry_run"),
                out.get("audit_path"),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("kb self-maintenance job failed")

    _facade()._scheduler.add_job(
        _kb_self_maintenance_job,
        _facade().IntervalTrigger(
            hours=max(1, _facade()._env_int("MODSTORE_KB_SELF_MAINTENANCE_INTERVAL_HOURS", 24))
        ),
        id="kb_self_maintenance",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    def _auto_merge_audit_sampling_job() -> None:
        try:
            from modstore_server.auto_merge_audit_sampler import (
                run_auto_merge_audit_sampling_once,
            )

            out = run_auto_merge_audit_sampling_once()
            _facade().logger.info(
                "auto-merge audit sampling: candidates=%s queued=%s summary=%s",
                out.get("total_auto_merge_candidates"),
                out.get("new_queue_items"),
                out.get("latest_summary_path"),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("auto-merge audit sampling job failed")

    _facade()._scheduler.add_job(
        _auto_merge_audit_sampling_job,
        _facade().IntervalTrigger(
            hours=max(1, _facade()._env_int("MODSTORE_AUTO_MERGE_AUDIT_INTERVAL_HOURS", 168))
        ),
        id="auto_merge_audit_sampling",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    try:
        from modstore_server.post_deploy_smoke_job import (
            cron_smoke_enabled,
            interval_trigger_for_post_deploy_smoke,
            run_post_deploy_smoke_job,
        )

        if cron_smoke_enabled():
            _facade()._scheduler.add_job(
                run_post_deploy_smoke_job,
                interval_trigger_for_post_deploy_smoke(),
                id="post_deploy_smoke_interval",
                replace_existing=True,
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register post_deploy_smoke cron failed")
