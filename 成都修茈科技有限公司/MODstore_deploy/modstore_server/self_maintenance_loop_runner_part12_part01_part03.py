# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def cron_trigger_for_self_maintenance() -> _facade().CronTrigger:
    hour = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3)
    minute = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0)
    timezone_name = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai")
    return _facade().CronTrigger(hour=hour, minute=minute, timezone=timezone_name)


def record_self_maintenance_heartbeat(
    *, triggered_by: str = "scheduler_heartbeat"
) -> _facade().Dict[str, _facade().Any]:
    """Append a side-effect-free liveness receipt for the outer loop.

    The full maintenance loop is intentionally daily and may be held by
    cooldown or governance.  A separate heartbeat proves the scheduler is
    still evaluating that gate without pretending code work was performed.
    """
    evaluation = _facade().should_run_self_maintenance_loop(force=False, triggered_by=triggered_by)
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
        "created_at": _facade()._iso(_facade()._utc_now()),
        "phase": "heartbeat",
        "run_id": f"heartbeat-{_facade().uuid.uuid4().hex[:16]}",
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
    _facade()._append_ledger(record)
    return record
