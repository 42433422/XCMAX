"""Fault-injection continuity suite (CI-runnable, no production hosts)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "stability" / "continuity_harness.py"


def _harness_mod():
    import sys

    spec = importlib.util.spec_from_file_location("continuity_harness", HARNESS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_disconnect_reconnect_preserves_session(tmp_path):
    mod = _harness_mod()
    h = mod.ContinuityHarness(data_dir=tmp_path)
    h.append_history("user", "hello")
    h.disconnect("wifi_lost")
    with pytest.raises(mod.ContinuityError, match="disconnected"):
        h.append_history("user", "should-fail")
    h.reconnect()
    h.append_history("assistant", "welcome back")
    assert [row["role"] for row in h.session.history] == ["user", "assistant"]


def test_history_restore_after_disconnect():
    mod = _harness_mod()
    h = mod.ContinuityHarness()
    for i in range(5):
        h.append_history("user", f"m{i}")
    h.disconnect()
    restored = h.restore_history()
    assert len(restored) == 5
    assert [row["seq"] for row in restored] == list(range(5))


def test_streaming_drop_then_resume_from_cursor():
    mod = _harness_mod()
    h = mod.ContinuityHarness()
    h.begin_stream(["a", "b", "c", "d", "e"])
    first = h.read_stream(inject_drop_after=2)
    assert first == ["a", "b"]
    assert h.session.connected is False
    rest = h.resume_stream()
    assert rest == ["c", "d", "e"]
    assert h.session.stream_cursor == 5


def test_tool_timeout_is_retryable_unknown(monkeypatch):
    mod = _harness_mod()
    h = mod.ContinuityHarness()

    clock = iter((0.0, 0.05))
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))
    h.set_tool(lambda: "late", timeout_seconds=0.01)
    outcome = h.run_tool_with_deadline()
    assert outcome["ok"] is False
    assert outcome["error"] == "tool_timeout"
    assert outcome["retryable"] is True
    assert outcome["reconciliation_required"] is True


def test_task_retry_and_idempotency():
    mod = _harness_mod()
    h = mod.ContinuityHarness()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"ok": True, "n": calls["n"]}

    first = h.submit_task("t1", "idem-1", flaky)
    assert first.status == "failed"
    second = h.retry_task("t1", flaky)
    assert second.status == "succeeded"
    assert second.attempts == 2
    # Same idempotency key must not create a duplicate task.
    dup = h.submit_task("t2", "idem-1", lambda: {"should": "not-run"})
    assert dup.task_id == "t1"
    assert dup.result == {"ok": True, "n": 2}
    assert calls["n"] == 2


def test_upgrade_preserves_business_data_readback(tmp_path):
    mod = _harness_mod()
    h = mod.ContinuityHarness(data_dir=tmp_path)
    h.write_business("attendance_days", 22)
    h.write_business("etl_batch_id", "batch-42")
    before = {
        "attendance_days": h.read_business("attendance_days"),
        "etl_batch_id": h.read_business("etl_batch_id"),
    }
    report = h.simulate_upgrade("1.0.0.7")
    assert report["version"] == "1.0.0.7"
    # New harness instance on same data dir must read identical business keys.
    h2 = mod.ContinuityHarness(data_dir=tmp_path)
    assert h2.app_version == "1.0.0.7"
    assert h2.read_business("attendance_days") == before["attendance_days"]
    assert h2.read_business("etl_batch_id") == before["etl_batch_id"]
