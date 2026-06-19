"""工作流 cron 触发：从 DB 加载 APScheduler 任务。"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from modstore_server import payment_orders
from modstore_server.models import WorkflowTrigger, get_session_factory
from modstore_server.workflow_event_runner import run_workflow_for_trigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None

_JOB_PREFIX = "wf_trigger_"
_LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS = 0.0
_LAST_TIME_RAIL_OBSERVABILITY_MISSING = -1


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _business_misfire_grace_time() -> int:
    return max(60, _env_int("MODSTORE_SCHEDULER_BUSINESS_MISFIRE_GRACE_SECONDS", 3600))


def _cleanup_misfire_grace_time() -> int:
    return max(60, _env_int("MODSTORE_SCHEDULER_CLEANUP_MISFIRE_GRACE_SECONDS", 4 * 3600))


def _daily_pipeline_lock_wait_seconds(stage: str) -> int:
    env_name = f"MODSTORE_DAILY_PIPELINE_LOCK_WAIT_{stage.upper()}_SECONDS"
    defaults = {
        "daily_digest": 0,
        "daily_vibe_line_execute": 90 * 60,
        "release_train_orchestrator": 90 * 60,
    }
    return max(0, _env_int(env_name, defaults.get(stage, 0)))


def _run_daily_pipeline_stage(stage: str, fn: Callable[[], Any]) -> Any:
    from modstore_server.daily_pipeline_lock import acquire_daily_pipeline_lock

    wait_seconds = _daily_pipeline_lock_wait_seconds(stage)
    with acquire_daily_pipeline_lock(stage=stage, timeout_seconds=wait_seconds) as lock:
        if not lock.get("acquired"):
            logger.warning(
                "daily pipeline stage skipped: stage=%s reason=%s wait=%s",
                stage,
                lock.get("reason"),
                wait_seconds,
            )
            return {"ok": True, "skipped": True, **lock}
        return fn()


def _trigger_self_maintenance_from_incident(*, emitted: bool, source: str) -> None:
    if not emitted or not _env_bool("MODSTORE_SELF_MAINTENANCE_EVENT_TRIGGER_ENABLED", True):
        return
    try:
        from modstore_server.self_maintenance_loop_runner import run_self_maintenance_loop

        result = run_self_maintenance_loop(
            triggered_by="incident_event",
            force=_env_bool("MODSTORE_SELF_MAINTENANCE_EVENT_FORCE", False),
            reason=source,
        )
        logger.info(
            "incident-driven self-maintenance finished: source=%s status=%s reason=%s",
            source,
            result.get("status"),
            result.get("reason") or (result.get("gate") or {}).get("reason"),
        )
    except Exception:
        logger.exception("incident-driven self-maintenance failed: source=%s", source)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    try:
        from modstore_server.backup_event_subscriber import register_backup_event_subscribers

        register_backup_event_subscribers()
    except Exception:
        logger.exception("register backup event subscribers failed")
    _load_triggers()

    def _scheduler_heartbeat_job() -> None:
        try:
            from modstore_server.daily_pipeline_lock import write_scheduler_heartbeat

            write_scheduler_heartbeat(job_count=len(_scheduler.get_jobs()) if _scheduler else None)
            try:
                from modstore_server.node_coordinator import write_node_heartbeat

                write_node_heartbeat(job_count=len(_scheduler.get_jobs()) if _scheduler else None)
            except Exception:
                logger.debug("node heartbeat failed", exc_info=True)
        except Exception:
            logger.exception("scheduler heartbeat failed")

    _scheduler.add_job(
        _scheduler_heartbeat_job,
        IntervalTrigger(minutes=5),
        id="scheduler_heartbeat",
        replace_existing=True,
        misfire_grace_time=_cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )
    _scheduler_heartbeat_job()

    def _close_stale_orders() -> None:
        try:
            n = payment_orders.close_pending_older_than(minutes=30)
            if n:
                logger.info("closed %d expired pending payment orders", n)
        except Exception:
            logger.exception("close expired payment orders failed")

    _scheduler.add_job(
        _close_stale_orders,
        IntervalTrigger(minutes=5),
        id="payment_orders_expire",
        replace_existing=True,
    )

    def _retention_janitor_daily() -> None:
        try:
            from modstore_server.file_retention_janitor import run_retention_janitor

            r = run_retention_janitor()
            logger.info(
                "retention janitor done: dry_run=%s status=%s removed=%s released=%s ms=%.1f",
                bool(r.get("dry_run")),
                r.get("status"),
                r.get("removed_count"),
                r.get("released_bytes"),
                float(r.get("duration_ms") or 0.0),
            )
        except Exception:
            logger.exception("retention janitor failed")

    _scheduler.add_job(
        _retention_janitor_daily,
        CronTrigger(hour=3, minute=15),
        id="retention_janitor_daily",
        replace_existing=True,
        misfire_grace_time=_cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )

    def _incident_collect_pytest_cursor() -> None:
        try:
            from modstore_server.incident_collectors import (
                collect_cursor_log_spike,
                collect_pytest_failures,
            )

            emitted = bool(collect_pytest_failures())
            emitted = bool(collect_cursor_log_spike()) or emitted
            _trigger_self_maintenance_from_incident(
                emitted=emitted,
                source="incident_collect_pytest_cursor",
            )
        except Exception:
            logger.exception("incident_collect_pytest_cursor failed")

    def _incident_collect_nginx() -> None:
        try:
            from modstore_server.incident_collectors import collect_nginx_error_tail

            emitted = bool(collect_nginx_error_tail())
            _trigger_self_maintenance_from_incident(
                emitted=emitted,
                source="incident_collect_nginx",
            )
        except Exception:
            logger.exception("incident_collect_nginx failed")

    _scheduler.add_job(
        _incident_collect_pytest_cursor,
        IntervalTrigger(minutes=5),
        id="incident_collect_pytest_cursor",
        replace_existing=True,
    )
    _scheduler.add_job(
        _incident_collect_nginx,
        IntervalTrigger(minutes=10),
        id="incident_collect_nginx",
        replace_existing=True,
    )

    def _incident_collect_extended() -> None:
        try:
            from modstore_server.incident_collectors import (
                collect_ci_failure_log,
                collect_git_push_event,
                collect_incident_bus_unknown_alarm,
            )

            emitted = bool(collect_git_push_event())
            emitted = bool(collect_ci_failure_log()) or emitted
            emitted = bool(collect_incident_bus_unknown_alarm()) or emitted
            _trigger_self_maintenance_from_incident(
                emitted=emitted,
                source="incident_collect_extended",
            )
        except Exception:
            logger.exception("incident_collect_extended failed")

    _scheduler.add_job(
        _incident_collect_extended,
        IntervalTrigger(minutes=5),
        id="incident_collect_extended",
        replace_existing=True,
    )

    def _daily_digest_email() -> None:
        try:
            from modstore_server.daily_digest import run_daily_digest_email

            result = _run_daily_pipeline_stage("daily_digest", run_daily_digest_email)
            if result and not result.get("ok"):
                logger.error(
                    "daily digest email job completed without delivery: reason=%s rows=%s",
                    result.get("reason"),
                    result.get("delivery_rows"),
                )
            else:
                logger.info(
                    "daily digest email job done: delivered=%s skipped=%s record_id=%s",
                    result.get("delivered") if isinstance(result, dict) else None,
                    result.get("skipped") if isinstance(result, dict) else None,
                    result.get("record_id") if isinstance(result, dict) else None,
                )
                if (
                    isinstance(result, dict)
                    and result.get("ok", True)
                    and not result.get("skipped")
                    and _env_bool("MODSTORE_DAILY_CHAIN_EVENT_TRIGGER_ENABLED", True)
                ):
                    record_id = result.get("record_id")
                    from modstore_server.daily_release_train_orchestrator_job import (
                        run_daily_release_train_orchestrator_job,
                    )
                    from modstore_server.daily_vibe_line_execute_job import (
                        run_daily_vibe_line_execute_job,
                    )

                    vibe_result = _run_daily_pipeline_stage(
                        "daily_vibe_line_execute",
                        lambda: run_daily_vibe_line_execute_job(record_id=record_id),
                    )
                    logger.info(
                        "daily chain event: vibe_line record_id=%s ok=%s skipped=%s",
                        record_id,
                        vibe_result.get("ok") if isinstance(vibe_result, dict) else None,
                        vibe_result.get("skipped") if isinstance(vibe_result, dict) else None,
                    )
                    release_result = _run_daily_pipeline_stage(
                        "release_train_orchestrator",
                        lambda: run_daily_release_train_orchestrator_job(record_id=record_id),
                    )
                    logger.info(
                        "daily chain event: release_train record_id=%s ok=%s skipped=%s",
                        record_id,
                        release_result.get("ok") if isinstance(release_result, dict) else None,
                        release_result.get("skipped") if isinstance(release_result, dict) else None,
                    )
        except Exception:
            logger.exception("daily digest email job failed")

    try:
        from modstore_server.daily_digest import cron_trigger_for_digest

        # 默认可错过窗口极短：若 08:00 整点线程正跑其它任务，cron 会 misfire 且当天不再补跑，导致库里缺「今天」。
        _scheduler.add_job(
            _daily_digest_email,
            cron_trigger_for_digest(),
            id="daily_ops_digest_email",
            replace_existing=True,
            misfire_grace_time=_business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except Exception:
        logger.exception("register daily digest cron failed")

    def _daily_vibe_line_execute_job() -> None:
        try:
            from modstore_server.daily_vibe_line_execute_job import run_daily_vibe_line_execute_job

            _run_daily_pipeline_stage("daily_vibe_line_execute", run_daily_vibe_line_execute_job)
        except Exception:
            logger.exception("daily vibe line execute job failed")

    try:
        from modstore_server.daily_vibe_line_execute_job import cron_trigger_for_vibe_line_execute

        if _env_bool("MODSTORE_DAILY_CHAIN_CRON_FALLBACK_ENABLED", False):
            _scheduler.add_job(
                _daily_vibe_line_execute_job,
                cron_trigger_for_vibe_line_execute(),
                id="daily_vibe_line_execute_job",
                replace_existing=True,
                misfire_grace_time=_business_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
            )
        else:
            logger.info("daily vibe line cron disabled; digest completion event is primary")
    except Exception:
        logger.exception("register daily vibe line execute cron failed")

    def _daily_orchestrator_job() -> None:
        try:
            from modstore_server.daily_orchestrator_job import run_daily_orchestrator_job

            run_daily_orchestrator_job()
        except Exception:
            logger.exception("daily orchestrator job failed")

    try:
        from modstore_server.daily_orchestrator_job import cron_trigger_for_orchestrator

        _scheduler.add_job(
            _daily_orchestrator_job,
            cron_trigger_for_orchestrator(),
            id="daily_orchestrator_job",
            replace_existing=True,
            misfire_grace_time=_business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except Exception:
        logger.exception("register daily orchestrator cron failed")

    def _self_maintenance_loop_job() -> None:
        try:
            from modstore_server.self_maintenance_loop_runner import (
                run_self_maintenance_loop,
            )

            result = run_self_maintenance_loop(triggered_by="scheduler")
            logger.info("self-maintenance loop finished: %s", result)
        except Exception:
            logger.exception("self-maintenance loop job failed")

    try:
        from modstore_server.self_maintenance_loop_runner import (
            cron_trigger_for_self_maintenance,
        )

        _scheduler.add_job(
            _self_maintenance_loop_job,
            cron_trigger_for_self_maintenance(),
            id="self_maintenance_loop_daily",
            replace_existing=True,
            misfire_grace_time=_business_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except Exception:
        logger.exception("register self-maintenance loop cron failed")

    def _daily_release_train_orchestrator_job() -> None:
        try:
            from modstore_server.daily_release_train_orchestrator_job import (
                run_daily_release_train_orchestrator_job,
            )

            _run_daily_pipeline_stage(
                "release_train_orchestrator",
                run_daily_release_train_orchestrator_job,
            )
        except Exception:
            logger.exception("daily release_train orchestrator job failed")

    try:
        from modstore_server.daily_release_train_orchestrator_job import (
            cron_trigger_for_release_train_orchestrator,
        )

        if _env_bool("MODSTORE_DAILY_CHAIN_CRON_FALLBACK_ENABLED", False):
            _scheduler.add_job(
                _daily_release_train_orchestrator_job,
                cron_trigger_for_release_train_orchestrator(),
                id="daily_release_train_orchestrator_job",
                replace_existing=True,
                misfire_grace_time=_business_misfire_grace_time(),
                coalesce=True,
                max_instances=1,
            )
        else:
            logger.info("daily release_train cron disabled; digest completion event is primary")
    except Exception:
        logger.exception("register daily release_train orchestrator cron failed")

    def _daily_backup_job() -> None:
        try:
            from modstore_server.daily_backup_job import run_daily_backup_job

            r = run_daily_backup_job()
            logger.info("daily backup job: ok=%s dir=%s", r.get("ok"), r.get("backup_dir"))
        except Exception:
            logger.exception("daily backup job failed")

    try:
        from modstore_server.daily_backup_job import cron_trigger_for_backup

        _scheduler.add_job(
            _daily_backup_job,
            cron_trigger_for_backup(),
            id="daily_backup_job",
            replace_existing=True,
            misfire_grace_time=_cleanup_misfire_grace_time(),
            coalesce=True,
            max_instances=1,
        )
    except Exception:
        logger.exception("register daily backup cron failed")

    def _dr_recovery_probe_job() -> None:
        try:
            from modstore_server.dr_recovery_probe_job import run_dr_recovery_probe

            r = run_dr_recovery_probe()
            if not r.get("skipped"):
                logger.info(
                    "dr recovery probe: ok=%s recovered=%s retry=%s escalated=%s",
                    r.get("ok"),
                    r.get("recovered"),
                    r.get("probe_retry_count"),
                    r.get("escalated"),
                )
        except Exception:
            logger.exception("dr recovery probe job failed")

    try:
        probe_mins = int(os.environ.get("MODSTORE_DR_PROBE_INTERVAL_MINUTES", "30"))
    except ValueError:
        probe_mins = 30
    _scheduler.add_job(
        _dr_recovery_probe_job,
        IntervalTrigger(minutes=max(5, probe_mins)),
        id="dr_recovery_probe_job",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    def _time_rail_observability_job() -> None:
        global _LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS
        global _LAST_TIME_RAIL_OBSERVABILITY_MISSING
        try:
            from modstore_server.time_rail_workflow import collect_node_runtime_status, sync_missing_evidence_backlog

            threshold = int(os.environ.get("MODSTORE_TIME_RAIL_MISSING_EVIDENCE_THRESHOLD", "3"))
            sync_limit = int(os.environ.get("MODSTORE_TIME_RAIL_MISSING_EVIDENCE_LIMIT", "32"))
            min_queue_gap = int(os.environ.get("MODSTORE_TIME_RAIL_MAINTENANCE_MIN_QUEUE_GAP", "1"))
            cooldown_seconds = int(os.environ.get("MODSTORE_TIME_RAIL_MAINTENANCE_COOLDOWN_SECONDS", str(10 * 60)))
            if threshold < 1:
                threshold = 1
            if sync_limit < 1:
                sync_limit = 1
            if min_queue_gap < 1:
                min_queue_gap = 1
            if cooldown_seconds < 0:
                cooldown_seconds = 10 * 60

            now = time.time()
            if (
                _LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS > 0
                and (now - _LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS) < cooldown_seconds
            ):
                logger.info(
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
                logger.info(
                    "time rail observability sync skipped: below_threshold",
                    extra={"missing": missing, "threshold": threshold},
                )
                return
            if remaining < min_queue_gap:
                logger.info(
                    "time rail observability sync skipped: queue_gap_not_reached",
                    extra={"remaining": remaining, "min_queue_gap": min_queue_gap},
                )
                return

            if (
                _LAST_TIME_RAIL_OBSERVABILITY_MISSING >= 0
                and missing <= _LAST_TIME_RAIL_OBSERVABILITY_MISSING
                and (now - _LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS) < cooldown_seconds
            ):
                logger.info(
                    "time rail observability sync skipped: no_new_missing_and_cooldown",
                    extra={"missing": missing},
                )
                return

            r = sync_missing_evidence_backlog(limit=sync_limit)
            _LAST_TIME_RAIL_OBSERVABILITY_SYNC_TS = now
            _LAST_TIME_RAIL_OBSERVABILITY_MISSING = missing
            if r.get("added"):
                logger.info(
                    "time rail observability sync: added=%s missing=%s queued=%s",
                    r.get("added"),
                    r.get("total_missing"),
                    queued,
                )
            else:
                logger.info(
                    "time rail observability sync: no_new_backlog missing=%s queued=%s",
                    missing,
                    queued,
                )
        except ValueError:
            logger.exception("time rail observability sync env parse failed")
        except Exception:
            logger.exception("time rail observability sync failed")

    _scheduler.add_job(
        _time_rail_observability_job,
        CronTrigger(hour=3, minute=0),
        id="time_rail_observability_sync",
        replace_existing=True,
        misfire_grace_time=_cleanup_misfire_grace_time(),
        coalesce=True,
        max_instances=1,
    )

    def _inbox_poll_job() -> None:
        try:
            from modstore_server.inbox_poller import poll_inbox_once

            poll_inbox_once()
        except Exception:
            logger.exception("inbox poll job failed")

    try:
        poll_secs = int(os.environ.get("MODSTORE_INBOX_POLL_SECONDS", "120"))
    except ValueError:
        poll_secs = 120
    poll_secs = max(60, poll_secs)
    _scheduler.add_job(
        _inbox_poll_job,
        IntervalTrigger(seconds=poll_secs),
        id="inbox_approval_poll",
        replace_existing=True,
    )

    def _email_intake_poll_job() -> None:
        try:
            from modstore_server.email_intake import poll_email_intake_once

            out = poll_email_intake_once()
            if not out.get("ok"):
                logger.warning(
                    "email intake poll failed: %s",
                    out.get("error") or "unknown",
                )
        except Exception:
            logger.exception("email intake poll job failed")

    try:
        intake_secs = int(os.environ.get("MODSTORE_EMAIL_INTAKE_POLL_SECONDS", "120"))
    except ValueError:
        intake_secs = 120
    _scheduler.add_job(
        _email_intake_poll_job,
        IntervalTrigger(seconds=max(30, intake_secs)),
        id="email_intake_poll",
        replace_existing=True,
    )

    def _employee_autonomy_dispatch_loop() -> None:
        try:
            from modstore_server.employee_autonomy_service import (
                dispatch_pending_brief_tasks,
                dispatch_pending_suggestions,
            )

            try:
                brief_limit = int(os.environ.get("MODSTORE_BRIEF_DISPATCH_BATCH", "20"))
            except ValueError:
                brief_limit = 20
            try:
                sug_limit = int(os.environ.get("MODSTORE_SUGGESTION_DISPATCH_BATCH", "20"))
            except ValueError:
                sug_limit = 20
            b = dispatch_pending_brief_tasks(limit=max(1, min(brief_limit, 100)))
            s = dispatch_pending_suggestions(limit=max(1, min(sug_limit, 100)))
            logger.info(
                "employee autonomy dispatch: brief processed=%s done=%s failed=%s; suggestion processed=%s ok=%s skipped=%s",
                b.get("processed"),
                b.get("done"),
                b.get("failed"),
                s.get("processed"),
                s.get("ok_count"),
                s.get("skipped"),
            )
        except Exception:
            logger.exception("employee autonomy dispatch loop failed")

    try:
        loop_seconds = int(os.environ.get("MODSTORE_EMPLOYEE_AUTONOMY_LOOP_SECONDS", "120"))
    except ValueError:
        loop_seconds = 120
    _scheduler.add_job(
        _employee_autonomy_dispatch_loop,
        IntervalTrigger(seconds=max(30, loop_seconds)),
        id="employee_autonomy_dispatch_loop",
        replace_existing=True,
    )

    def _employee_evolution_scan_loop() -> None:
        try:
            from modstore_server.employee_autonomy_service import run_employee_evolution_scan

            try:
                lookback = int(os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_LOOKBACK_HOURS", "24"))
            except ValueError:
                lookback = 24
            try:
                min_fail = int(os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_MIN_FAILURES", "3"))
            except ValueError:
                min_fail = 3
            try:
                lim = int(os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_SCAN_LIMIT", "20"))
            except ValueError:
                lim = 20
            out = run_employee_evolution_scan(
                lookback_hours=lookback,
                min_failures=min_fail,
                limit=lim,
                triggered_by="scheduler",
            )
            logger.info(
                "employee evolution scan: processed=%s created=%s enabled=%s",
                out.get("processed"),
                out.get("created"),
                out.get("enabled"),
            )
        except Exception:
            logger.exception("employee evolution scan loop failed")

    try:
        evolution_minutes = int(
            os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_INTERVAL_MINUTES", "60")
        )
    except ValueError:
        evolution_minutes = 60
    _scheduler.add_job(
        _employee_evolution_scan_loop,
        IntervalTrigger(minutes=max(10, evolution_minutes)),
        id="employee_evolution_scan_loop",
        replace_existing=True,
    )

    def _employee_health_scan_loop() -> None:
        try:
            from modstore_server.employee_health_scan import run_health_scan

            out = run_health_scan()
            if out.get("scanned"):
                logger.info(
                    "employee health scan: warned=%d deactivated=%d",
                    len(out.get("warned") or []),
                    len(out.get("deactivated") or []),
                )
        except Exception:
            logger.exception("employee health scan loop failed")

    try:
        health_minutes = int(os.environ.get("MODSTORE_HEALTH_SCAN_INTERVAL_MIN", "30"))
    except ValueError:
        health_minutes = 30
    _scheduler.add_job(
        _employee_health_scan_loop,
        IntervalTrigger(minutes=max(5, health_minutes)),
        id="employee_health_scan_loop",
        replace_existing=True,
    )

    try:
        _register_employee_cron_jobs()
    except Exception:
        logger.exception("register employee cron jobs failed")

    def _auto_fix_loop_job() -> None:
        try:
            from modstore_server.auto_fix_loop import register_auto_fix_event_bindings

            register_auto_fix_event_bindings()
        except Exception:
            logger.debug("auto_fix event bindings registration skipped")

    _scheduler.add_job(
        _auto_fix_loop_job,
        IntervalTrigger(hours=1),
        id="auto_fix_event_bindings_refresh",
        replace_existing=True,
    )

    def _auto_version_bump_job() -> None:
        try:
            from modstore_server.auto_version_bump import auto_version_bump
            from modstore_server.integrations.ops_action_handlers import repo_root

            root = str(repo_root())
            out = auto_version_bump(root)
            if out.get("ok") and not out.get("skipped"):
                logger.info(
                    "auto version bump: %s → %s (anchors=%d)",
                    out.get("old_version"),
                    out.get("new_version"),
                    out.get("anchors_synced"),
                )
        except Exception:
            logger.exception("auto version bump job failed")

    _scheduler.add_job(
        _auto_version_bump_job,
        CronTrigger(hour=6, minute=0),
        id="auto_version_bump_daily",
        replace_existing=True,
    )

    def _telemetry_backlog_scan_job() -> None:
        try:
            from modstore_server.telemetry_backlog_loop import run_telemetry_scan

            out = run_telemetry_scan()
            if out.get("ok") and not out.get("skipped"):
                logger.info(
                    "telemetry backlog scan: signals=%d ingested=%d",
                    out.get("signals_found"),
                    out.get("signals_ingested"),
                )
        except Exception:
            logger.exception("telemetry backlog scan job failed")

    _scheduler.add_job(
        _telemetry_backlog_scan_job,
        IntervalTrigger(hours=6),
        id="telemetry_backlog_scan",
        replace_existing=True,
    )

    def _predictive_maintenance_job() -> None:
        try:
            from modstore_server.predictive_maintenance import run_predictive_maintenance_once

            out = run_predictive_maintenance_once()
            logger.info(
                "predictive maintenance: predictions=%s emitted=%s path=%s",
                len(out.get("predictions") or []),
                out.get("emitted_incident"),
                out.get("forecast_path"),
            )
        except Exception:
            logger.exception("predictive maintenance job failed")

    _scheduler.add_job(
        _predictive_maintenance_job,
        IntervalTrigger(hours=max(1, _env_int("MODSTORE_PREDICTIVE_MAINTENANCE_INTERVAL_HOURS", 6))),
        id="predictive_maintenance_forecast",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    def _kb_self_maintenance_job() -> None:
        try:
            from modstore_server.kb_self_maintenance import run_kb_self_maintenance_once

            out = run_kb_self_maintenance_once()
            logger.info(
                "kb self-maintenance: actions=%s dry_run=%s audit=%s",
                out.get("action_count"),
                out.get("dry_run"),
                out.get("audit_path"),
            )
        except Exception:
            logger.exception("kb self-maintenance job failed")

    _scheduler.add_job(
        _kb_self_maintenance_job,
        IntervalTrigger(hours=max(1, _env_int("MODSTORE_KB_SELF_MAINTENANCE_INTERVAL_HOURS", 24))),
        id="kb_self_maintenance",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    def _auto_merge_audit_sampling_job() -> None:
        try:
            from modstore_server.auto_merge_audit_sampler import run_auto_merge_audit_sampling_once

            out = run_auto_merge_audit_sampling_once()
            logger.info(
                "auto-merge audit sampling: candidates=%s queued=%s summary=%s",
                out.get("total_auto_merge_candidates"),
                out.get("new_queue_items"),
                out.get("latest_summary_path"),
            )
        except Exception:
            logger.exception("auto-merge audit sampling job failed")

    _scheduler.add_job(
        _auto_merge_audit_sampling_job,
        IntervalTrigger(hours=max(1, _env_int("MODSTORE_AUTO_MERGE_AUDIT_INTERVAL_HOURS", 168))),
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
            _scheduler.add_job(
                run_post_deploy_smoke_job,
                interval_trigger_for_post_deploy_smoke(),
                id="post_deploy_smoke_interval",
                replace_existing=True,
            )
    except Exception:
        logger.exception("register post_deploy_smoke cron failed")

    logger.info("workflow scheduler started")


_EMPLOYEE_CRON_JOB_PREFIX = "emp_cron_"


def _employee_auto_cron_enabled() -> bool:
    return os.environ.get("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _employee_cron_job_id(employee_id: str) -> str:
    safe = "".join(c for c in (employee_id or "") if c.isalnum() or c in ("-", "_"))[:64]
    return f"{_EMPLOYEE_CRON_JOB_PREFIX}{safe or 'unknown'}"


def _extract_employee_schedule(manifest: dict) -> Optional[dict]:
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


def _register_employee_cron_jobs() -> None:
    """扫描所有员工包 manifest 的 ``schedule`` 字段，注册全员日常轮值。"""
    if _scheduler is None:
        return
    if not _employee_auto_cron_enabled():
        logger.info("employee auto cron disabled (MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED=0)")
        return

    try:
        import importlib

        task_router = importlib.import_module("modstore_server.task_router")
        employee_runtime = importlib.import_module("modstore_server.employee_runtime")
        _load_all_employee_profiles = task_router._load_all_employee_profiles
        load_employee_pack = employee_runtime.load_employee_pack
        from modstore_server.models import get_session_factory
    except Exception:
        logger.exception("employee cron: import failed")
        return

    profiles = _load_all_employee_profiles()
    if not profiles:
        logger.info("employee cron: no profiles found in catalog")
        return

    sf = get_session_factory()
    registered = 0
    skipped = 0
    for prof in profiles:
        emp_id = str(prof.get("id") or "").strip()
        if not emp_id:
            continue
        try:
            with sf() as session:
                pack = load_employee_pack(session, emp_id)
            manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        except Exception:
            skipped += 1
            continue

        sched = _extract_employee_schedule(manifest)
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

        trigger = None
        try:
            if cron_expr:
                trigger = CronTrigger.from_crontab(cron_expr)
            elif isinstance(interval_seconds, (int, float)) and interval_seconds >= 60:
                trigger = IntervalTrigger(seconds=int(interval_seconds))
        except Exception as exc:
            logger.warning("employee cron: invalid trigger for %s: %s", emp_id, exc)
            skipped += 1
            continue

        if trigger is None:
            skipped += 1
            continue

        job_id = _employee_cron_job_id(emp_id)
        eid_local = emp_id
        brief_local = task_brief

        def _runner(eid: str = eid_local, brief: str = brief_local) -> None:
            try:
                import importlib

                employee_executor = importlib.import_module("modstore_server.employee_executor")
                employee_executor.execute_employee_task(
                    eid, brief, {"trigger": "schedule"}, user_id=0
                )
            except Exception:
                logger.exception("employee cron job failed: %s", eid)

        try:
            _scheduler.add_job(_runner, trigger, id=job_id, replace_existing=True)
            registered += 1
            logger.info(
                "employee cron registered: %s -> %s",
                emp_id,
                cron_expr or f"interval {interval_seconds}s",
            )
        except Exception:
            logger.exception("employee cron add_job failed: %s", emp_id)
            skipped += 1

    logger.info("employee cron: registered=%d skipped=%d", registered, skipped)


def list_employee_cron_jobs() -> list:
    """返回当前已注册的员工 cron 任务清单（前端缺岗看板用）。"""
    if _scheduler is None:
        return []
    out = []
    for job in _scheduler.get_jobs():
        jid = job.id or ""
        if not jid.startswith(_EMPLOYEE_CRON_JOB_PREFIX):
            continue
        out.append(
            {
                "job_id": jid,
                "employee_id": jid[len(_EMPLOYEE_CRON_JOB_PREFIX) :],
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
        )
    return out


def reload_employee_cron_jobs() -> dict:
    """重新扫描 catalog 并刷新员工 cron 注册（修改 manifest / 上架新员工后调用）。"""
    if _scheduler is None:
        return {"ok": False, "error": "scheduler not started"}
    for job in list(_scheduler.get_jobs()):
        if (job.id or "").startswith(_EMPLOYEE_CRON_JOB_PREFIX):
            try:
                _scheduler.remove_job(job.id)
            except Exception:
                pass
    _register_employee_cron_jobs()
    return {"ok": True, "active_jobs": list_employee_cron_jobs()}


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("workflow scheduler stopped")


def _job_id(trigger_id: int) -> str:
    return f"{_JOB_PREFIX}{trigger_id}"


def _load_triggers() -> None:
    if _scheduler is None:
        return
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(WorkflowTrigger)
            .filter(
                WorkflowTrigger.trigger_type == "cron",
                WorkflowTrigger.is_active.is_(True),
            )
            .all()
        )
    for t in rows:
        _register_cron_trigger(t.id, t.workflow_id, t.user_id, t.config_json or "{}")


def _register_cron_trigger(
    trigger_id: int, workflow_id: int, user_id: int, config_json: str
) -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        config = json.loads(config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    cron_expr = str(config.get("cron") or config.get("schedule") or "0 0 * * *").strip()

    wf_id = workflow_id
    uid = user_id

    def job_wrapper() -> None:
        try:
            run_workflow_for_trigger(workflow_id=wf_id, user_id=uid, input_data={})
        except Exception as e:
            logger.exception("cron workflow failed workflow_id=%s: %s", wf_id, e)

    jid = _job_id(trigger_id)
    try:
        _scheduler.remove_job(jid)
    except Exception:
        pass
    try:
        _scheduler.add_job(
            job_wrapper,
            CronTrigger.from_crontab(cron_expr),
            id=jid,
            replace_existing=True,
        )
        logger.info(
            "registered cron trigger id=%s workflow=%s expr=%s", trigger_id, wf_id, cron_expr
        )
    except Exception as e:
        logger.warning("invalid cron for trigger id=%s: %s", trigger_id, e)


def unregister_cron_trigger(trigger_id: int) -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_job_id(trigger_id))
    except Exception:
        pass


def refresh_cron_trigger(trigger_id: int) -> None:
    sf = get_session_factory()
    with sf() as session:
        t = session.query(WorkflowTrigger).filter(WorkflowTrigger.id == trigger_id).first()
    if not t or not t.is_active or (t.trigger_type or "").lower() != "cron":
        unregister_cron_trigger(trigger_id)
        return
    _register_cron_trigger(t.id, t.workflow_id, t.user_id, t.config_json or "{}")


def reload_all_cron_triggers() -> None:
    global _scheduler
    if _scheduler is None:
        return
    for job in list(_scheduler.get_jobs()):
        jid = job.id or ""
        if jid.startswith(_JOB_PREFIX):
            try:
                _scheduler.remove_job(jid)
            except Exception:
                pass
    _load_triggers()
