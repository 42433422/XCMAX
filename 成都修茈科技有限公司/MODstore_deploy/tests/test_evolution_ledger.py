# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_ledger.py
"""演化决策 ledger 单元测试。"""

from __future__ import annotations

import json

import pytest

from modstore_server.evolution_ledger import (
    LEDGER_FILENAME,
    append_event,
    list_events,
    mark_audited,
)


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / LEDGER_FILENAME
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    return ledger_path


def test_append_event_writes_jsonl_line(tmp_ledger):
    event = {
        "event_type": "signal_detected",
        "triggered_by": "intent_benchmark",
        "signal_score": 0.85,
    }
    append_event(event)
    assert tmp_ledger.exists()
    lines = tmp_ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "signal_detected"
    assert parsed["signal_score"] == 0.85
    assert "event_id" in parsed
    assert "timestamp" in parsed
    assert parsed["owner_audit"]["audited"] is False


def test_append_event_multiple_lines(tmp_ledger):
    for i in range(3):
        append_event({"event_type": "signal_detected", "signal_score": i * 0.1})
    lines = tmp_ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_list_events_filters_by_event_type(tmp_ledger):
    append_event({"event_type": "signal_detected", "triggered_by": "intent_benchmark"})
    append_event({"event_type": "pack_listed", "pack_id": "test@1.0.0"})
    append_event({"event_type": "signal_detected", "triggered_by": "slo_metrics"})
    listed = list_events(event_type="pack_listed")
    assert len(listed) == 1
    assert listed[0]["pack_id"] == "test@1.0.0"


def test_list_events_filters_by_status(tmp_ledger):
    append_event({"event_type": "implement_failed", "final_status": "needs_human"})
    append_event({"event_type": "pack_listed", "final_status": "pack_listed"})
    needs_human = list_events(final_status="needs_human")
    assert len(needs_human) == 1
    assert needs_human[0]["final_status"] == "needs_human"


def test_list_events_since_filter(tmp_ledger):
    from datetime import datetime, timedelta, timezone

    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    recent_time = datetime.now(timezone.utc).isoformat()
    append_event({"event_type": "old", "timestamp": old_time})
    append_event({"event_type": "recent", "timestamp": recent_time})
    since_7d = list_events(since_days=7)
    assert len(since_7d) == 1
    assert since_7d[0]["event_type"] == "recent"


def test_mark_audited_updates_event(tmp_ledger):
    result = append_event({"event_type": "pack_listed", "pack_id": "test@1.0.0"})
    event_id = result["event_id"]
    mark_audited(event_id, verdict="approved")
    events = list_events(event_type="pack_listed")
    assert events[0]["owner_audit"]["audited"] is True
    assert events[0]["owner_audit"]["verdict"] == "approved"
    assert events[0]["owner_audit"]["audited_at"] is not None


def test_append_event_handles_missing_ledger_dir(tmp_path, monkeypatch):
    nested = tmp_path / "nested" / "deeper" / LEDGER_FILENAME
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(nested))
    append_event({"event_type": "test"})
    assert nested.exists()


def test_append_event_concurrent_safe(tmp_ledger):
    """并发写不应丢行（append-only 模式 + 文件锁）。"""
    import threading

    def writer(start: int):
        for i in range(20):
            append_event({"event_type": "concurrent", "idx": start + i})

    threads = [threading.Thread(target=writer, args=(i * 20,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = tmp_ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100
