from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modstore_server import self_maintenance_loop_runner as runner


def _start(run_id: str, started_at: datetime) -> dict:
    return {
        "phase": "start",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "status": "running",
        "triggered_by": "scheduler",
    }


def test_reacquired_lease_closes_recent_interrupted_run(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc)
    rows = [_start("recent-run", now - timedelta(minutes=5))]
    appended: list[dict] = []

    monkeypatch.setattr(runner, "_read_ledger", lambda limit=300: rows[-limit:])
    monkeypatch.setattr(runner, "_append_ledger", appended.append)
    monkeypatch.setattr(runner, "_utc_now", lambda: now)

    result = runner.reconcile_stale_self_maintenance_runs(exclusive_lease_reacquired=True)

    assert result["reconciled"] == ["recent-run"]
    assert result["exclusive_lease_reacquired"] is True
    assert appended == [
        {
            "completed_at": now.isoformat(),
            "error": (
                "previous process lost the exclusive loop lease before writing a terminal record"
            ),
            "phase": "complete",
            "policy_decision": {
                "action": "stop",
                "reason": "interrupted_run_after_lease_reacquired",
                "exclusive_lease_reacquired": True,
                "recovery_required": True,
                "stale_minutes": 180,
            },
            "recovery_required": True,
            "run_id": "recent-run",
            "started_at": (now - timedelta(minutes=5)).isoformat(),
            "status": "abandoned_interrupted",
            "triggered_by": "scheduler",
        }
    ]


def test_without_lease_recent_run_remains_open(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc)
    rows = [_start("active-run", now - timedelta(minutes=5))]
    appended: list[dict] = []

    monkeypatch.setattr(runner, "_read_ledger", lambda limit=300: rows[-limit:])
    monkeypatch.setattr(runner, "_append_ledger", appended.append)
    monkeypatch.setattr(runner, "_utc_now", lambda: now)

    result = runner.reconcile_stale_self_maintenance_runs()

    assert result["reconciled"] == []
    assert result["exclusive_lease_reacquired"] is False
    assert appended == []


def test_age_based_reconciliation_preserves_existing_contract(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc)
    rows = [_start("stale-run", now - timedelta(minutes=181))]
    appended: list[dict] = []

    monkeypatch.setattr(runner, "_read_ledger", lambda limit=300: rows[-limit:])
    monkeypatch.setattr(runner, "_append_ledger", appended.append)
    monkeypatch.setattr(runner, "_utc_now", lambda: now)

    result = runner.reconcile_stale_self_maintenance_runs()

    assert result["reconciled"] == ["stale-run"]
    assert appended[-1]["status"] == "abandoned_stale"
    assert appended[-1]["policy_decision"]["reason"] == "stale_interrupted_run"
    assert appended[-1]["recovery_required"] is False


def test_same_trigger_interruption_bypasses_cooldown_and_signal_threshold(
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc)
    started_at = now - timedelta(minutes=5)
    rows = [
        {
            **_start("interrupted-run", started_at),
            "triggered_by": "automated_remediation",
        },
        {
            "completed_at": (now - timedelta(minutes=4)).isoformat(),
            "phase": "complete",
            "run_id": "interrupted-run",
            "status": "abandoned_interrupted",
            "triggered_by": "automated_remediation",
        },
    ]
    monkeypatch.setattr(runner, "_read_ledger", lambda limit=300: rows[-limit:])
    monkeypatch.setattr(runner, "_utc_now", lambda: now)
    monkeypatch.setattr(
        runner,
        "evaluate_self_maintenance_need",
        lambda: {
            "runtime_provenance": {"ok": True},
            "signal_count": 0,
        },
    )
    monkeypatch.setattr(runner, "evolution_metrics_gate", lambda: {"pause": False})

    gate = runner.should_run_self_maintenance_loop(
        force=False,
        triggered_by="automated_remediation",
    )

    assert gate["should_run"] is True
    assert gate["reason"] == "interrupted_recovery"
    assert gate["interrupted_recovery"] == {
        "interrupted_at": (now - timedelta(minutes=4)).isoformat(),
        "run_id": "interrupted-run",
        "started_at": started_at.isoformat(),
        "triggered_by": "automated_remediation",
    }


def test_interruption_does_not_bypass_cooldown_for_another_trigger(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc)
    rows = [
        {
            **_start("interrupted-run", now - timedelta(minutes=5)),
            "triggered_by": "automated_remediation",
        },
        {
            "completed_at": (now - timedelta(minutes=4)).isoformat(),
            "phase": "complete",
            "run_id": "interrupted-run",
            "status": "abandoned_interrupted",
            "triggered_by": "automated_remediation",
        },
    ]
    monkeypatch.setattr(runner, "_read_ledger", lambda limit=300: rows[-limit:])
    monkeypatch.setattr(runner, "_utc_now", lambda: now)
    monkeypatch.setattr(
        runner,
        "evaluate_self_maintenance_need",
        lambda: {
            "runtime_provenance": {"ok": True},
            "signal_count": 10,
        },
    )
    monkeypatch.setattr(runner, "evolution_metrics_gate", lambda: {"pause": False})

    gate = runner.should_run_self_maintenance_loop(
        force=False,
        triggered_by="scheduler",
    )

    assert gate["should_run"] is False
    assert gate["reason"] == "cooldown"


def test_interruption_recovery_does_not_bypass_evolution_pause(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc)
    rows = [
        {
            **_start("interrupted-run", now - timedelta(minutes=5)),
            "triggered_by": "automated_remediation",
        },
        {
            "completed_at": (now - timedelta(minutes=4)).isoformat(),
            "phase": "complete",
            "run_id": "interrupted-run",
            "status": "abandoned_interrupted",
            "triggered_by": "automated_remediation",
        },
    ]
    monkeypatch.setattr(runner, "_read_ledger", lambda limit=300: rows[-limit:])
    monkeypatch.setattr(
        runner,
        "evaluate_self_maintenance_need",
        lambda: {
            "runtime_provenance": {"ok": True},
            "signal_count": 10,
        },
    )
    monkeypatch.setattr(
        runner,
        "evolution_metrics_gate",
        lambda: {"pause": True, "reason": "verified_regression"},
    )

    gate = runner.should_run_self_maintenance_loop(
        force=False,
        triggered_by="automated_remediation",
    )

    assert gate["should_run"] is False
    assert gate["reason"] == "evolution_metrics_pause"
