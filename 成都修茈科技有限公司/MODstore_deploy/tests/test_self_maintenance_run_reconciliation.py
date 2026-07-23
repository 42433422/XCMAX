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
                "stale_minutes": 180,
            },
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
