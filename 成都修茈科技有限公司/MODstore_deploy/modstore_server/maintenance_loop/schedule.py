"""Read runtime signals, cooldowns and recovery evidence before authorizing a run."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from apscheduler.triggers.cron import CronTrigger

from modstore_server import (
    models,
    runtime_provenance,
    self_evolution_knowledge,
    self_maintenance_recovery_policy,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, store


def _self_maintenance_actor_user_id() -> int:
    """自维护 loop 的 LLM 执行身份（默认平台身份 ``user_id=0``）。

    ``services.llm.chat_dispatch_via_session`` 仅在 ``uid > 0`` 时调
    ``quota_middleware.require_llm_credit`` 走某真实用户的个人 ``llm_calls`` 月配额闸；
    传 ``0`` 即跳过该配额、改用 ``llm_key_resolver.resolve_api_key`` 的平台密钥
    （``user_id=0`` 无 BYOK 凭证行，自然回落 ``platform_api_key``）。指标表 ``user_id``
    仍由 ``employee_executor._resolve_metric_user_id`` 回落到真实 ``users.id``，监控不丢。

    历史 bug：本函数旧实现（``_first_user_id``）取「库里第一个真实用户」作执行身份，
    使平台自治工作全部记到 owner 个人配额上；其额度耗尽后整条 loop 持续报
    ``403: 配额不足: llm_calls``（生产实测 99.6% 失败的根因）。

    运维如需按某真实用户 BYOK/配额计费，可设 ``MODSTORE_SELF_MAINTENANCE_USER_ID=<uid>``。
    """
    env_uid = os.environ.get("MODSTORE_SELF_MAINTENANCE_USER_ID", "").strip()
    if env_uid:
        try:
            return int(env_uid)
        except ValueError:
            config.logger.warning("MODSTORE_SELF_MAINTENANCE_USER_ID not an int: %s", env_uid)
    return 0


def _recent_employee_failure_count(lookback_hours: int) -> int:
    since = config._utc_now() - timedelta(hours=lookback_hours)
    db = models.get_session_factory()()
    try:
        return (
            db.query(models.EmployeeExecutionMetric)
            .filter(models.EmployeeExecutionMetric.created_at >= since)
            .filter(models.EmployeeExecutionMetric.status != "success")
            .count()
        )
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to count recent employee failures")
        return 1
    finally:
        db.close()


def _recent_incident_signals(lookback_hours: int, *, limit: int = 8) -> Dict[str, Any]:
    """Return fresh incident signals that should wake the maintenance loop.

    The 03:00 cron remains as a batch safety net, but Phase A treats new
    quality/error/security incidents as a real-time signal for employee
    delegation.
    """
    since = config._utc_now() - timedelta(hours=lookback_hours)
    event_types = {
        "ci.failed",
        "incident.unknown",
        "on_error",
        "on_quality_fail",
        "security.alert",
    }
    db = models.get_session_factory()()
    try:
        query = (
            db.query(models.IncidentEvent)
            .filter(models.IncidentEvent.created_at >= since)
            .filter(models.IncidentEvent.event_type.in_(sorted(event_types)))
            .order_by(models.IncidentEvent.created_at.desc())
        )
        rows = query.limit(max(1, int(limit))).all()
        count = query.count()
        incidents: List[Dict[str, Any]] = []
        for row in rows:
            payload: Dict[str, Any] = {}
            try:
                loaded = json.loads(row.payload_json or "{}")
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {}
            incidents.append(
                {
                    "created_at": (
                        config._iso(row.created_at)
                        if isinstance(row.created_at, datetime)
                        else str(row.created_at or "")
                    ),
                    "event_type": row.event_type,
                    "fingerprint": row.fingerprint,
                    "id": int(row.id),
                    "source": row.source,
                    "summary": str(payload.get("summary") or "")[:500],
                }
            )
        return {
            "count": int(count),
            "events": incidents,
            "lookback_hours": lookback_hours,
        }
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to read recent incident signals")
        return {"count": 1, "events": [], "error": "incident_signal_query_failed"}
    finally:
        db.close()


def evaluate_self_maintenance_need() -> Dict[str, Any]:
    """Return deterministic signals used by the threshold gate."""
    gaps: List[str] = []
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    device_id = os.environ.get("MODSTORE_PARA_DEVICE_ID", "").strip()
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    runtime_provenance_result = runtime_provenance.collect_runtime_provenance(
        target_branch=branch or "main"
    )
    if not api_base:
        gaps.append("missing MODSTORE_PARA_API_BASE")
    if not device_id:
        gaps.append("missing MODSTORE_PARA_DEVICE_ID")
    if not repo_url:
        gaps.append("missing MODSTORE_PARA_REPO_URL")
    elif "/Desktop/" in repo_url and (
        not config._env_bool("MODSTORE_SELF_MAINTENANCE_ALLOW_DESKTOP_REPO", False)
    ):
        gaps.append("repo url still points into Desktop")
    if not branch:
        gaps.append("missing MODSTORE_PARA_BRANCH")
    if config._env_bool("MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME", True) and (
        not runtime_provenance_result.get("ok")
    ):
        reasons = ",".join(
            str(item) for item in runtime_provenance_result.get("reasons") or []
        )
        gaps.append(f"runtime provenance blocked: {reasons or 'unknown'}")
    repo_path = config._file_url_to_path(repo_url)
    if repo_path is not None and (not repo_path.exists()):
        gaps.append(f"repo url path does not exist: {repo_path}")
    lookback_hours = config._env_int("MODSTORE_SELF_MAINTENANCE_LOOKBACK_HOURS", 24)
    failure_count = _recent_employee_failure_count(lookback_hours)
    incident_signals = _recent_incident_signals(lookback_hours)
    incident_count = int(incident_signals.get("count") or 0)
    proactive_signals = self_evolution_knowledge.collect_proactive_signals()
    proactive_task_count = (
        len(proactive_signals.get("candidates") or [])
        if config._env_bool("MODSTORE_SELF_EVOLUTION_PROACTIVE_ENABLED", True)
        else 0
    )
    signal_count = len(gaps) + failure_count + incident_count + proactive_task_count
    return {
        "api_base": api_base,
        "branch": branch,
        "device_id": device_id,
        "failure_count": failure_count,
        "gaps": gaps,
        "incident_count": incident_count,
        "incident_signals": incident_signals,
        "lookback_hours": lookback_hours,
        "proactive_signals": proactive_signals,
        "proactive_task_count": proactive_task_count,
        "repo_url": repo_url,
        "runtime_provenance": runtime_provenance,
        "signal_count": signal_count,
    }


def _last_started_at() -> Optional[datetime]:
    for row in reversed(store._read_ledger()):
        if row.get("phase") == "start":
            return config._parse_iso(row.get("started_at") or row.get("created_at"))
    return None


def reconcile_stale_self_maintenance_runs(
    *, exclusive_lease_reacquired: bool = False
) -> Dict[str, Any]:
    """Close interrupted runs without misreporting them as completed work.

    When the caller has just acquired the process-wide loop lease, any older
    start row without a terminal row is necessarily orphaned: an actually
    running transaction would still own the same OS lock.  Reconcile that case
    immediately instead of leaving the management console in ``running`` for
    the full stale timeout after a deploy or process restart.  Callers that do
    not hold the lease retain the conservative age-based behavior.
    """
    rows = store._read_ledger(limit=300)
    started: Dict[str, Dict[str, Any]] = {}
    terminal: Dict[str, Dict[str, Any]] = {}
    steps_by_run: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        phase = str(row.get("phase") or "")
        if phase == "start":
            started[run_id] = row
        elif phase in {"complete", "skip"}:
            terminal[run_id] = row
        elif phase in {"step", "step_retry"}:
            steps_by_run.setdefault(run_id, []).append(row)
    stale_minutes = config._env_int("MODSTORE_SELF_MAINTENANCE_STALE_RUN_MINUTES", 180)
    cutoff = config._utc_now() - timedelta(minutes=stale_minutes)
    reconciled: List[str] = []
    for run_id, start in started.items():
        if run_id in terminal:
            continue
        started_at = config._parse_iso(start.get("started_at") or start.get("created_at"))
        if started_at is None:
            continue
        if not exclusive_lease_reacquired and started_at > cutoff:
            continue
        interrupted = bool(exclusive_lease_reacquired)
        terminal_status = "abandoned_interrupted" if interrupted else "abandoned_stale"
        terminal_reason = (
            "interrupted_run_after_lease_reacquired" if interrupted else "stale_interrupted_run"
        )
        terminal_error = (
            "previous process lost the exclusive loop lease before writing a terminal record"
            if interrupted
            else "run did not write a terminal record before stale timeout"
        )
        run_steps = steps_by_run.get(run_id) or []
        last_step_phase = str(run_steps[-1].get("phase") or "") if run_steps else ""
        if last_step_phase == "step_retry":
            last_step = run_steps[-1]
            step_terminal = {
                "employee_id": last_step.get("employee_id"),
                "error": (
                    "step interrupted before the process released its loop lease"
                    if interrupted
                    else "step abandoned during inner retry before stale timeout"
                ),
                "ok": False,
                "phase": "step",
                "run_id": run_id,
                "status": terminal_status,
                "step": last_step.get("step"),
                "timestamp": config._iso(config._utc_now()),
            }
            store._append_ledger(step_terminal)
        final = {
            "completed_at": config._iso(config._utc_now()),
            "error": terminal_error,
            "phase": "complete",
            "policy_decision": {
                "action": "stop",
                "reason": terminal_reason,
                "exclusive_lease_reacquired": interrupted,
                "recovery_required": interrupted,
                "stale_minutes": stale_minutes,
            },
            "recovery_required": interrupted,
            "run_id": run_id,
            "started_at": config._iso(started_at),
            "status": terminal_status,
            "triggered_by": start.get("triggered_by"),
        }
        store._append_ledger(final)
        reconciled.append(run_id)
    return {
        "exclusive_lease_reacquired": bool(exclusive_lease_reacquired),
        "reconciled": reconciled,
        "stale_minutes": stale_minutes,
    }


def should_run_self_maintenance_loop(
    force: bool = False, triggered_by: str = "manual"
) -> Dict[str, Any]:
    if not config._env_bool("MODSTORE_SELF_MAINTENANCE_ENABLED", True):
        return {"should_run": False, "reason": "disabled"}
    evaluation = evaluate_self_maintenance_need()
    runtime_provenance = evaluation.get("runtime_provenance")
    if (
        config._env_bool("MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME", True)
        and isinstance(runtime_provenance, dict)
        and (not runtime_provenance.get("ok"))
    ):
        return {
            **evaluation,
            "force_requested": force,
            "reason": "runtime_provenance_blocked",
            "should_run": False,
            "triggered_by": triggered_by,
        }
    metrics_gate = self_evolution_knowledge.evolution_metrics_gate()
    if not force and metrics_gate.get("pause"):
        return {
            **evaluation,
            "evolution_metrics_gate": metrics_gate,
            "reason": "evolution_metrics_pause",
            "should_run": False,
        }
    threshold = config._env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1)
    from modstore_server.autonomy_scheduler import self_maintenance_cooldown_minutes

    cooldown_minutes = self_maintenance_cooldown_minutes(triggered_by)
    last_started = _last_started_at()
    pending_recovery = self_maintenance_recovery_policy.pending_run_recovery(
        store._read_ledger(limit=300), triggered_by
    )
    recovery_kind = str((pending_recovery or {}).get("kind") or "")
    recovery_detail = (pending_recovery or {}).get("detail")
    interrupted_recovery = recovery_detail if recovery_kind == "interrupted_recovery" else None
    transient_failure_recovery = (
        recovery_detail if recovery_kind == "transient_failure_recovery" else None
    )
    if (
        not force
        and pending_recovery is None
        and (last_started is not None)
        and (cooldown_minutes > 0)
    ):
        next_allowed = last_started + timedelta(minutes=cooldown_minutes)
        if config._utc_now() < next_allowed:
            return {
                **evaluation,
                "cooldown_minutes": cooldown_minutes,
                "next_allowed_at": config._iso(next_allowed),
                "reason": "cooldown",
                "should_run": False,
                "threshold": threshold,
                "triggered_by": triggered_by,
            }
    if not force and pending_recovery is None and (int(evaluation["signal_count"]) < threshold):
        return {
            **evaluation,
            "cooldown_minutes": cooldown_minutes,
            "reason": "below_threshold",
            "should_run": False,
            "threshold": threshold,
        }
    return {
        **evaluation,
        "cooldown_minutes": cooldown_minutes,
        "interrupted_recovery": interrupted_recovery,
        "transient_failure_recovery": transient_failure_recovery,
        "reason": (
            "force"
            if force
            else (
                "interrupted_recovery"
                if interrupted_recovery is not None
                else (
                    "transient_failure_recovery"
                    if transient_failure_recovery is not None
                    else "threshold_met"
                )
            )
        ),
        "should_run": True,
        "threshold": threshold,
    }


def cron_trigger_for_self_maintenance() -> CronTrigger:
    hour = config._env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3)
    minute = config._env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0)
    timezone_name = os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai")
    return CronTrigger(hour=hour, minute=minute, timezone=timezone_name)


def record_self_maintenance_heartbeat(
    *, triggered_by: str = "scheduler_heartbeat"
) -> Dict[str, Any]:
    """Append a side-effect-free liveness receipt for the outer loop.

    The full maintenance loop is intentionally daily and may be held by
    cooldown or governance.  A separate heartbeat proves the scheduler is
    still evaluating that gate without pretending code work was performed.
    """
    evaluation = should_run_self_maintenance_loop(force=False, triggered_by=triggered_by)
    provenance = (
        evaluation.get("runtime_provenance")
        if isinstance(evaluation.get("runtime_provenance"), dict)
        else {}
    )
    metrics_gate = (
        evaluation.get("evolution_metrics_gate")
        if isinstance(evaluation.get("evolution_metrics_gate"), dict)
        else {}
    )
    record = {
        "created_at": config._iso(config._utc_now()),
        "phase": "heartbeat",
        "run_id": f"heartbeat-{uuid.uuid4().hex[:16]}",
        "status": "heartbeat_ready" if evaluation.get("should_run") is True else "heartbeat_idle",
        "triggered_by": str(triggered_by or "scheduler_heartbeat")[:80],
        "gate": {
            "should_run": evaluation.get("should_run") is True,
            "reason": str(evaluation.get("reason") or "")[:160],
            "runtime_provenance_ok": provenance.get("ok") is True,
            "evolution_metrics_paused": metrics_gate.get("pause") is True,
        },
        "read_only": True,
        "side_effects": [],
    }
    store._append_ledger(record)
    return record
