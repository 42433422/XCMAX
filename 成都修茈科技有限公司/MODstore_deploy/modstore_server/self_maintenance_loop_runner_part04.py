# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def reconcile_stale_self_maintenance_runs(
    *, exclusive_lease_reacquired: bool = False
) -> _facade().Dict[str, _facade().Any]:
    """Close interrupted runs without misreporting them as completed work.

    When the caller has just acquired the process-wide loop lease, any older
    start row without a terminal row is necessarily orphaned: an actually
    running transaction would still own the same OS lock.  Reconcile that case
    immediately instead of leaving the management console in ``running`` for
    the full stale timeout after a deploy or process restart.  Callers that do
    not hold the lease retain the conservative age-based behavior.
    """
    rows = _facade()._read_ledger(limit=300)
    started: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    terminal: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    steps_by_run: _facade().Dict[str, _facade().List[_facade().Dict[str, _facade().Any]]] = {}
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
    stale_minutes = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_STALE_RUN_MINUTES", 180)
    cutoff = _facade()._utc_now() - _facade().timedelta(minutes=stale_minutes)
    reconciled: _facade().List[str] = []
    for run_id, start in started.items():
        if run_id in terminal:
            continue
        started_at = _facade()._parse_iso(start.get("started_at") or start.get("created_at"))
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
                "timestamp": _facade()._iso(_facade()._utc_now()),
            }
            _facade()._append_ledger(step_terminal)
        final = {
            "completed_at": _facade()._iso(_facade()._utc_now()),
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
            "started_at": _facade()._iso(started_at),
            "status": terminal_status,
            "triggered_by": start.get("triggered_by"),
        }
        _facade()._append_ledger(final)
        reconciled.append(run_id)
    return {
        "exclusive_lease_reacquired": bool(exclusive_lease_reacquired),
        "reconciled": reconciled,
        "stale_minutes": stale_minutes,
    }


def should_run_self_maintenance_loop(
    force: bool = False, triggered_by: str = "manual"
) -> _facade().Dict[str, _facade().Any]:
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_ENABLED", True):
        return {"should_run": False, "reason": "disabled"}
    evaluation = _facade().evaluate_self_maintenance_need()
    runtime_provenance = evaluation.get("runtime_provenance")
    if (
        _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME", True)
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
    metrics_gate = _facade().evolution_metrics_gate()
    if not force and metrics_gate.get("pause"):
        return {
            **evaluation,
            "evolution_metrics_gate": metrics_gate,
            "reason": "evolution_metrics_pause",
            "should_run": False,
        }
    threshold = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1)
    from modstore_server.autonomy_scheduler import self_maintenance_cooldown_minutes

    cooldown_minutes = self_maintenance_cooldown_minutes(triggered_by)
    last_started = _facade()._last_started_at()
    pending_recovery = _facade().pending_run_recovery(
        _facade()._read_ledger(limit=300), triggered_by
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
        next_allowed = last_started + _facade().timedelta(minutes=cooldown_minutes)
        if _facade()._utc_now() < next_allowed:
            return {
                **evaluation,
                "cooldown_minutes": cooldown_minutes,
                "next_allowed_at": _facade()._iso(next_allowed),
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
