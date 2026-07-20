"""Tests for rational cooldown in ``should_run_self_maintenance_loop``."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from modstore_server import self_maintenance_loop_runner as loop_runner


@pytest.fixture
def isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ledger = tmp_path / "self_maintenance_loop_runs.jsonl"
    monkeypatch.setattr(loop_runner, "ledger_path", lambda: ledger)
    for key in list(os.environ):
        if key.startswith("MODSTORE_SELF_MAINTENANCE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(loop_runner, "evolution_metrics_gate", lambda: {"pause": False})
    monkeypatch.setattr(
        loop_runner,
        "evaluate_self_maintenance_need",
        lambda: {
            "signal_count": 1,
            "gaps": [],
            "failure_count": 0,
            "incident_count": 0,
            "proactive_task_count": 0,
        },
    )
    return ledger


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _write_terminal(ledger, *, status, completed_at, run_id="r1", started_at=None):
    if started_at is None:
        started_at = completed_at - timedelta(minutes=15)
    record = {
        "phase": "complete",
        "run_id": run_id,
        "status": status,
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
    }
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_start(ledger, *, run_id, started_at, triggered_by="scheduler"):
    record = {
        "phase": "start",
        "run_id": run_id,
        "triggered_by": triggered_by,
        "started_at": _iso(started_at),
    }
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def test_force_bypasses_all_cooldowns(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_start(isolated_ledger, run_id="in-progress-1", started_at=now - timedelta(minutes=5))
    _write_terminal(isolated_ledger, status="failed", completed_at=now - timedelta(minutes=30))
    result = loop_runner.should_run_self_maintenance_loop(force=True, triggered_by="scheduler")
    assert result["should_run"] is True
    assert result["reason"] == "force"


def test_in_progress_run_blocks_new_run(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger, status="completed", completed_at=now - timedelta(minutes=30), run_id="r0"
    )
    _write_start(isolated_ledger, run_id="in-progress-1", started_at=now - timedelta(minutes=10))
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["should_run"] is False
    assert result["reason"] == "in_progress"
    assert result["in_progress_run_id"] == "in-progress-1"


def test_scheduler_after_success_uses_short_cooldown(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(isolated_ledger, status="completed", completed_at=now - timedelta(minutes=10))
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["should_run"] is False
    assert result["reason"] == "cooldown"
    assert result["cooldown_minutes"] == 30
    assert result["last_terminal_status"] == "completed"


def test_scheduler_after_success_30min_plus_runs(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger, status="completed_merged", completed_at=now - timedelta(minutes=31)
    )
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["should_run"] is True
    assert result["reason"] == "threshold_met"


def test_scheduler_after_waiting_human_uses_60min(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger,
        status="completed_waiting_human_strategy",
        completed_at=now - timedelta(minutes=40),
    )
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["should_run"] is False
    assert result["reason"] == "cooldown"
    assert result["cooldown_minutes"] == 60


def test_scheduler_after_1_failure_uses_60min(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger, status="failed", completed_at=now - timedelta(minutes=30), run_id="r1"
    )
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["cooldown_minutes"] == 60
    assert result["reason"] == "cooldown"


def test_scheduler_after_2_failures_uses_120min(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger, status="failed", completed_at=now - timedelta(minutes=200), run_id="r1"
    )
    _write_terminal(
        isolated_ledger,
        status="abandoned_stale",
        completed_at=now - timedelta(minutes=30),
        run_id="r2",
    )
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["cooldown_minutes"] == 120


def test_scheduler_after_5_failures_capped_at_360min(isolated_ledger):
    now = datetime.now(timezone.utc)
    for i in range(10):
        _write_terminal(
            isolated_ledger,
            status="failed",
            completed_at=now - timedelta(minutes=(10 - i) * 60),
            run_id=f"r{i}",
        )
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["cooldown_minutes"] == 360


def test_scheduler_no_terminal_record_runs_immediately(isolated_ledger):
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["should_run"] is True
    assert result["cooldown_minutes"] == 0


def test_incident_event_uses_60min_regardless_of_outcome(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(isolated_ledger, status="completed", completed_at=now - timedelta(minutes=10))
    result = loop_runner.should_run_self_maintenance_loop(
        force=False, triggered_by="incident_event"
    )
    assert result["cooldown_minutes"] == 60
    assert result["reason"] == "cooldown"


def test_manual_uses_360min_default(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(isolated_ledger, status="completed", completed_at=now - timedelta(minutes=60))
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="manual")
    assert result["cooldown_minutes"] == 360


def test_legacy_mode_uses_last_started_360min(isolated_ledger, monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MODE", "legacy")
    now = datetime.now(timezone.utc)
    _write_start(isolated_ledger, run_id="r1", started_at=now - timedelta(minutes=30))
    _write_terminal(
        isolated_ledger, status="completed", completed_at=now - timedelta(minutes=20), run_id="r1"
    )
    result = loop_runner.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert result["cooldown_minutes"] == 360
    assert result["reason"] == "cooldown"


def test_consecutive_failures_counts_only_contiguous(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger, status="completed", completed_at=now - timedelta(minutes=240), run_id="r0"
    )
    _write_terminal(
        isolated_ledger, status="failed", completed_at=now - timedelta(minutes=180), run_id="r1"
    )
    _write_terminal(
        isolated_ledger, status="failed", completed_at=now - timedelta(minutes=120), run_id="r2"
    )
    _write_terminal(
        isolated_ledger,
        status="abandoned_stale",
        completed_at=now - timedelta(minutes=60),
        run_id="r3",
    )
    assert loop_runner._consecutive_failures() == 3


def test_last_terminal_record_returns_most_recent_complete(isolated_ledger):
    now = datetime.now(timezone.utc)
    _write_terminal(
        isolated_ledger, status="failed", completed_at=now - timedelta(minutes=120), run_id="r0"
    )
    _write_terminal(
        isolated_ledger, status="completed", completed_at=now - timedelta(minutes=30), run_id="r1"
    )
    record = loop_runner._last_terminal_record()
    assert record is not None
    assert record["status"] == "completed"
    assert record["run_id"] == "r1"
