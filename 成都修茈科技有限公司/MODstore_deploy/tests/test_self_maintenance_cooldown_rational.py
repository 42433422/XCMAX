"""Tests for rational cooldown in ``self_maintenance_loop_runner`` (2026-07-20).

验证：
- force=True 绕过所有 gate
- in_progress run 阻断（reason=in_progress）
- 成功 → 30min cooldown
- 成功后 31min+ → 可跑（reason=threshold_met）
- waiting_human → 60min cooldown
- 失败 1/2/5 次指数退避（60/120/360，cap 360）
- 无任何 ledger 记录 → scheduler cooldown=0
- incident_event → 60min
- manual → 360min
- legacy 模式回退旧逻辑
- _consecutive_failures 计数正确
- _last_terminal_record 返回最近终态
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

import pytest

from modstore_server import self_maintenance_loop_runner as mod


# ---- helpers ----------------------------------------------------------------


def _ledger_row(
    *,
    phase: str,
    run_id: str = "run-1",
    status: str = "",
    minutes_ago: float = 0.0,
    triggered_by: str = "scheduler",
) -> Dict[str, Any]:
    """Build a ledger row. ``minutes_ago`` shifts started_at/completed_at back in time."""
    from modstore_server.self_maintenance_loop_runner import _iso, _utc_now

    ts = _iso(_utc_now() - timedelta(minutes=minutes_ago))
    row: Dict[str, Any] = {
        "phase": phase,
        "run_id": run_id,
        "triggered_by": triggered_by,
        "started_at": ts,
        "created_at": ts,
    }
    if status:
        row["status"] = status
    if phase in {"complete", "skip"}:
        row["completed_at"] = ts
    return row


@pytest.fixture
def stub_evaluation(monkeypatch):
    """让 evaluate_self_maintenance_need / evolution_metrics_gate 稳定可控。"""
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_THRESHOLD", "1")
    monkeypatch.setattr(
        mod,
        "evaluate_self_maintenance_need",
        lambda: {"signal_count": 5, "proactive_task_count": 1, "repo_url": "test"},
    )
    monkeypatch.setattr(mod, "evolution_metrics_gate", lambda: {"pause": False})


@pytest.fixture
def ledger(monkeypatch):
    """Replace _read_ledger with an in-memory list under test control."""
    records: List[Dict[str, Any]] = []
    monkeypatch.setattr(mod, "_read_ledger", lambda limit=100: list(records))
    return records


def _set_last_terminal(
    ledger: List[Dict[str, Any]],
    *,
    status: str,
    minutes_ago: float = 0.0,
    run_id: str = "run-prev",
) -> None:
    """Replace ledger with a single terminal record at ``minutes_ago``."""
    ledger.clear()
    ledger.append(
        _ledger_row(
            phase="complete",
            run_id=run_id,
            status=status,
            minutes_ago=minutes_ago,
        )
    )


# ---- force / in_progress ---------------------------------------------------


def test_force_bypasses_all_gates(stub_evaluation, ledger):
    """force=True 跳过 in_progress 与 cooldown 闸。"""
    ledger.append(_ledger_row(phase="start", run_id="run-in-progress"))
    decision = mod.should_run_self_maintenance_loop(force=True, triggered_by="scheduler")
    assert decision["should_run"] is True
    assert decision["reason"] == "force"


def test_in_progress_run_blocks(stub_evaluation, ledger):
    """有 start 无 complete → reason=in_progress，should_run=False。"""
    ledger.append(_ledger_row(phase="start", run_id="run-in-progress"))
    decision = mod.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert decision["should_run"] is False
    assert decision["reason"] == "in_progress"
    assert decision["in_progress_run_id"] == "run-in-progress"


# ---- scheduler / success ---------------------------------------------------


def test_success_yields_30min_cooldown(stub_evaluation, ledger):
    """上次终态=completed → scheduler cooldown=30min。"""
    _set_last_terminal(ledger, status="completed", minutes_ago=5.0)
    decision = mod.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert decision["should_run"] is False
    assert decision["reason"] == "cooldown"
    assert decision["cooldown_minutes"] == 30


def test_success_then_31min_runs_again(stub_evaluation, ledger):
    """成功后 31min+ → 跳出 cooldown，进入 threshold_met。"""
    _set_last_terminal(ledger, status="completed", minutes_ago=31.0)
    decision = mod.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert decision["should_run"] is True
    assert decision["reason"] == "threshold_met"


# ---- waiting_human ---------------------------------------------------------


def test_waiting_human_yields_60min_cooldown(stub_evaluation, ledger):
    _set_last_terminal(ledger, status="completed_waiting_human_strategy", minutes_ago=10.0)
    decision = mod.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert decision["should_run"] is False
    assert decision["reason"] == "cooldown"
    assert decision["cooldown_minutes"] == 60


# ---- failures exponential backoff ------------------------------------------


def test_one_failure_yields_60min(stub_evaluation, ledger):
    """1 次连续失败 → base=60min。"""
    _set_last_terminal(ledger, status="failed", minutes_ago=5.0)
    assert mod._compute_cooldown_minutes("scheduler") == 60


def test_two_failures_yields_120min(stub_evaluation, ledger):
    """2 次连续失败 → base + step = 120min。"""
    ledger.clear()
    ledger.append(_ledger_row(phase="complete", status="failed", run_id="r2", minutes_ago=5.0))
    ledger.append(_ledger_row(phase="complete", status="failed", run_id="r1", minutes_ago=70.0))
    assert mod._consecutive_failures() == 2
    assert mod._compute_cooldown_minutes("scheduler") == 120


def test_six_failures_capped_at_360min(stub_evaluation, ledger):
    """6 次连续失败 → base + 5*step = 360，cap=360 取 min → 360。"""
    ledger.clear()
    for i in range(6):
        ledger.append(
            _ledger_row(
                phase="complete",
                status="failed",
                run_id=f"r{i}",
                minutes_ago=5.0 + i * 70.0,
            )
        )
    assert mod._compute_cooldown_minutes("scheduler") == 360


def test_failure_then_success_resets_consecutive(stub_evaluation, ledger):
    """失败后跟着成功 → consecutive=0（成功 break）。"""
    ledger.clear()
    ledger.append(_ledger_row(phase="complete", status="failed", run_id="r1", minutes_ago=130.0))
    ledger.append(_ledger_row(phase="complete", status="completed", run_id="r2", minutes_ago=5.0))
    assert mod._consecutive_failures() == 0


# ---- no records / incident / manual ----------------------------------------


def test_no_records_yields_zero_cooldown(stub_evaluation, ledger):
    """无任何 ledger 终态 → scheduler cooldown=0（直接放行）。"""
    ledger.clear()
    assert mod._compute_cooldown_minutes("scheduler") == 0


def test_incident_event_yields_60min(stub_evaluation, ledger):
    _set_last_terminal(ledger, status="completed", minutes_ago=1.0)
    assert mod._compute_cooldown_minutes("incident_event") == 60


def test_manual_yields_360min(stub_evaluation, ledger):
    _set_last_terminal(ledger, status="completed", minutes_ago=1.0)
    assert mod._compute_cooldown_minutes("manual") == 360


# ---- legacy mode -----------------------------------------------------------


def test_legacy_mode_uses_old_logic(stub_evaluation, ledger, monkeypatch):
    """MODSTORE_SELF_MAINTENANCE_COOLDOWN_MODE=legacy → 不看 last_terminal，固定 360min。"""
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MODE", "legacy")
    _set_last_terminal(ledger, status="completed", minutes_ago=1.0)
    assert mod._compute_cooldown_minutes("scheduler") == 360
    # legacy cooldown 基于 _last_started_at，没有 start 记录则放行
    ledger.clear()
    decision = mod.should_run_self_maintenance_loop(force=False, triggered_by="scheduler")
    assert decision["should_run"] is True
    assert decision["reason"] == "threshold_met"


# ---- helper introspection --------------------------------------------------


def test_last_terminal_record_returns_most_recent_complete(stub_evaluation, ledger):
    ledger.clear()
    ledger.append(_ledger_row(phase="start", run_id="r1"))
    ledger.append(_ledger_row(phase="complete", run_id="r1", status="completed"))
    ledger.append(_ledger_row(phase="start", run_id="r2"))
    last = mod._last_terminal_record()
    assert last is not None
    assert last["run_id"] == "r1"
    assert last["status"] == "completed"


def test_last_terminal_record_returns_none_when_only_start(stub_evaluation, ledger):
    ledger.clear()
    ledger.append(_ledger_row(phase="start", run_id="r1"))
    assert mod._last_terminal_record() is None


def test_skip_phase_counts_as_terminal(stub_evaluation, ledger):
    """phase=skip 也是终态（_last_terminal_record / _last_in_progress_start 都认）。"""
    ledger.clear()
    ledger.append(_ledger_row(phase="start", run_id="r1"))
    ledger.append(_ledger_row(phase="skip", run_id="r1", status="skipped"))
    assert mod._last_in_progress_start() is None
    last = mod._last_terminal_record()
    assert last is not None
    assert last["phase"] == "skip"


# ---- env override ----------------------------------------------------------


def test_env_can_override_success_cooldown(stub_evaluation, ledger, monkeypatch):
    """MODSTORE_SELF_MAINTENANCE_SUCCESS_COOLDOWN_MINUTES 覆盖默认 30min。"""
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SUCCESS_COOLDOWN_MINUTES", "15")
    _set_last_terminal(ledger, status="completed", minutes_ago=1.0)
    assert mod._compute_cooldown_minutes("scheduler") == 15


def test_env_can_override_failure_cap(stub_evaluation, ledger, monkeypatch):
    """MODSTORE_SELF_MAINTENANCE_FAILURE_COOLDOWN_CAP_MINUTES=180 触发更早 cap。"""
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FAILURE_COOLDOWN_CAP_MINUTES", "180")
    ledger.clear()
    for i in range(5):
        ledger.append(
            _ledger_row(
                phase="complete",
                status="failed",
                run_id=f"r{i}",
                minutes_ago=5.0 + i * 70.0,
            )
        )
    # base=60, step=60, consecutive=5 → 60 + 4*60 = 300, cap=180 → 180
    assert mod._compute_cooldown_minutes("scheduler") == 180
