"""Scheduler startup registration phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_scheduler")


def _register_scheduler_phase_01():
    try:
        from modstore_server.backup_event_subscriber import (
            register_backup_event_subscribers,
        )

        register_backup_event_subscribers()
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("register backup event subscribers failed")
    _facade()._load_triggers()

    def _scheduler_heartbeat_job() -> None:
        try:
            from modstore_server.daily_pipeline_lock import write_scheduler_heartbeat

            write_scheduler_heartbeat(
                job_count=len(_facade()._scheduler.get_jobs()) if _facade()._scheduler else None
            )
            try:
                from modstore_server.node_coordinator import write_node_heartbeat

                write_node_heartbeat(
                    job_count=len(_facade()._scheduler.get_jobs()) if _facade()._scheduler else None
                )
            except RECOVERABLE_ERRORS:
                _facade().logger.debug("node heartbeat failed", exc_info=True)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("scheduler heartbeat failed")

    _facade()._scheduler.add_job(
        _scheduler_heartbeat_job,
        _facade().IntervalTrigger(minutes=5),
        id="scheduler_heartbeat",
        replace_existing=True,
        misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )
    _scheduler_heartbeat_job()
    _facade().autonomy_scheduler.register_autonomy_jobs(
        _facade()._scheduler, _facade()._scheduler_startup_recovery_deadlines
    )

    def _dead_letter_reconcile_job() -> None:
        try:
            from modstore_server.dead_letter_reconciler import reconcile_dead_letters

            result = _facade()._run_tracked_scheduler_job(
                "dead_letter_reconciler", lambda: reconcile_dead_letters(limit=200)
            )
            if result.get("checked") or result.get("unresolved_count"):
                _facade().logger.info(
                    "dead-letter reconciliation checked=%s replay=%s quarantined=%s deferred=%s unresolved=%s storage_ok=%s",
                    result.get("checked"),
                    result.get("replay_scheduled"),
                    result.get("quarantined"),
                    result.get("deferred"),
                    result.get("unresolved_count"),
                    bool((result.get("storage") or {}).get("ok")),
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("dead-letter reconciliation failed")

    _facade()._scheduler.add_job(
        _dead_letter_reconcile_job,
        _facade().IntervalTrigger(
            minutes=max(1, _facade()._env_int("MODSTORE_DLQ_RECONCILE_MINUTES", 5))
        ),
        id="dead_letter_reconciler",
        replace_existing=True,
        misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )
    _dead_letter_reconcile_job()

    def _customer_value_reconcile_job() -> None:
        if not _facade()._env_bool("MODSTORE_CUSTOMER_VALUE_RECONCILE_ENABLED", True):
            return
        try:
            from modstore_server.customer_value_scheduler_job import (
                reconcile_customer_value_with_escalation,
            )

            result = _facade()._run_authoritative_customer_value_job(
                reconcile_customer_value_with_escalation
            )
            if result.get("created") or not result.get("source_ready"):
                _facade().logger.info(
                    "customer-value reconciliation source=%s ready=%s checked=%s created=%s existing=%s skipped=%s",
                    result.get("source_owner"),
                    result.get("source_ready"),
                    result.get("checked"),
                    result.get("created"),
                    result.get("existing"),
                    result.get("skipped"),
                )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("customer-value reconciliation failed")
            raise

    _facade()._scheduler.add_job(
        _customer_value_reconcile_job,
        _facade().IntervalTrigger(
            minutes=max(1, _facade()._env_int("MODSTORE_CUSTOMER_VALUE_RECONCILE_MINUTES", 15))
        ),
        id="customer_value_reconciler",
        replace_existing=True,
        misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )
    _facade()._run_scheduler_startup_probe(
        "customer_value_reconciler", _customer_value_reconcile_job
    )

    def _close_stale_orders() -> None:
        try:
            n = _facade().payment_orders.close_pending_older_than(minutes=30)
            if n:
                _facade().logger.info("closed %d expired pending payment orders", n)
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("close expired payment orders failed")

    _facade()._scheduler.add_job(
        _close_stale_orders,
        _facade().IntervalTrigger(minutes=5),
        id="payment_orders_expire",
        replace_existing=True,
    )

    def _retention_janitor_daily() -> None:
        try:
            from modstore_server.file_retention_janitor import run_retention_janitor

            r = run_retention_janitor(
                notification_dry_run=_facade()._env_bool(
                    "MODSTORE_NOTIFICATION_RETENTION_DRY_RUN", False
                )
            )
            _facade().logger.info(
                "retention janitor done: dry_run=%s status=%s removed=%s released=%s ms=%.1f",
                bool(r.get("dry_run")),
                r.get("status"),
                r.get("removed_count"),
                r.get("released_bytes"),
                float(r.get("duration_ms") or 0.0),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("retention janitor failed")

    _facade()._scheduler.add_job(
        _retention_janitor_daily,
        _facade().CronTrigger(hour=3, minute=15),
        id="retention_janitor_daily",
        replace_existing=True,
        misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )
    from modstore_server.storage_pressure_self_heal import register_storage_pressure_job

    register_storage_pressure_job(
        _facade()._scheduler,
        track_job=_facade()._run_tracked_scheduler_job,
        startup_probe=_facade()._run_scheduler_startup_probe,
        misfire_grace_time=_facade()._cleanup_misfire_grace_time(),
    )

    def _incident_collect_pytest_cursor() -> None:

        def _body() -> None:
            from modstore_server.incident_collectors import (
                collect_cursor_log_spike,
                collect_pytest_failures,
            )

            emitted = bool(collect_pytest_failures())
            emitted = bool(collect_cursor_log_spike()) or emitted
            _facade()._trigger_self_maintenance_from_incident(
                emitted=emitted, source="incident_collect_pytest_cursor"
            )

        try:
            _facade()._run_collector_with_timeout(
                _body, label="incident_collect_pytest_cursor", timeout=240.0
            )
        except (TimeoutError, _facade().asyncio.TimeoutError):
            _facade().logger.error(
                "incident_collect_pytest_cursor exceeded 240s timeout; orphan thread left running"
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("incident_collect_pytest_cursor failed")

    def _incident_collect_nginx() -> None:

        def _body() -> None:
            from modstore_server.incident_collectors import collect_nginx_error_tail

            emitted = bool(collect_nginx_error_tail())
            _facade()._trigger_self_maintenance_from_incident(
                emitted=emitted, source="incident_collect_nginx"
            )

        try:
            _facade()._run_collector_with_timeout(
                _body, label="incident_collect_nginx", timeout=240.0
            )
        except (TimeoutError, _facade().asyncio.TimeoutError):
            _facade().logger.error(
                "incident_collect_nginx exceeded 240s timeout; orphan thread left running"
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("incident_collect_nginx failed")

    _facade()._scheduler.add_job(
        _incident_collect_pytest_cursor,
        _facade().IntervalTrigger(minutes=5),
        id="incident_collect_pytest_cursor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    _facade()._scheduler.add_job(
        _incident_collect_nginx,
        _facade().IntervalTrigger(minutes=10),
        id="incident_collect_nginx",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    def _incident_collect_extended() -> None:

        def _body() -> None:
            from modstore_server.incident_collectors import (
                collect_ci_failure_log,
                collect_git_push_event,
                collect_incident_bus_unknown_alarm,
            )

            emitted = bool(collect_git_push_event())
            emitted = bool(collect_ci_failure_log()) or emitted
            emitted = bool(collect_incident_bus_unknown_alarm()) or emitted
            _facade()._trigger_self_maintenance_from_incident(
                emitted=emitted, source="incident_collect_extended"
            )

        try:
            _facade()._run_collector_with_timeout(
                _body, label="incident_collect_extended", timeout=240.0
            )
        except (TimeoutError, _facade().asyncio.TimeoutError):
            _facade().logger.error(
                "incident_collect_extended exceeded 240s timeout; orphan thread left running"
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.exception("incident_collect_extended failed")

    _facade()._scheduler.add_job(
        _incident_collect_extended,
        _facade().IntervalTrigger(minutes=5),
        id="incident_collect_extended",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
