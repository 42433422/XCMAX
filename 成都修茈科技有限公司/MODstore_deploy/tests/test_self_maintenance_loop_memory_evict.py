"""Tests for self-maintenance loop open_items auto-eviction.

任务 3 验收：注入 5 条 24h+ retry_count=3 的 open_items → 下次 LOOP 写 memory
后剩 0 条，evicted_items +5；同时验证 7 天老化路径与 governance 审计记录。
"""

from __future__ import annotations

import json
from datetime import timedelta

from modstore_server import self_maintenance_loop_runner as loop_runner
from modstore_server.self_maintenance_loop_runner import (
    LOOP_EVICT_AGE_OUT_SECONDS,
    LOOP_EVICT_STUCK_AGE_SECONDS,
    LOOP_EVICT_STUCK_RETRY_THRESHOLD,
    _iso,
    _load_loop_memory,
    _read_governance_audit,
    _update_loop_memory,
    _utc_now,
    evict_loop_memory_items,
)


def _seed_memory_file(memory_path, *, open_items, evicted_items=None):
    memory_path.write_text(
        json.dumps(
            {
                "closed_items": [],
                "evicted_items": evicted_items or [],
                "open_items": open_items,
                "recent_runs": [],
                "run_count": 0,
            }
        ),
        encoding="utf-8",
    )


def _stuck_failed_step(run_id, age_seconds, retry_count=3):
    """Build a failed_steps open_item aged age_seconds ago."""
    created = _iso(_utc_now() - timedelta(seconds=age_seconds))
    return {
        "created_at": created,
        "kind": "failed_steps",
        "retry_count": retry_count,
        "run_id": run_id,
        "steps": ["code"],
    }


# ---------------------------------------------------------------------------
# Acceptance test: 5 stuck open_items are evicted after _update_loop_memory
# ---------------------------------------------------------------------------


def test_update_loop_memory_auto_evicts_5_stuck_open_items(monkeypatch, tmp_path):
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))

    stuck_age = LOOP_EVICT_STUCK_AGE_SECONDS + 60  # 24h+
    open_items = [
        _stuck_failed_step(f"run-stuck-{i}", age_seconds=stuck_age, retry_count=3) for i in range(5)
    ]
    _seed_memory_file(memory_path, open_items=open_items)

    # Trigger _update_loop_memory with a fresh run that does not match any
    # existing open_item (so no resume, no close). The auto-evict path should
    # move all 5 stuck items to evicted_items.
    _update_loop_memory(
        final={
            "branch": None,
            "completed_at": _iso(_utc_now()),
            "para_task_id": "task-fresh",
            "policy_decision": {"action": "hold_for_automated_remediation"},
            "run_id": "run-fresh",
            "status": "completed_waiting_human_strategy",
            "steps": [],
        },
        gate={"reason": "force", "should_run": True},
    )

    memory = _load_loop_memory()
    # Acceptance: 0 failed_steps stuck items remain in open_items
    stuck_remaining = [
        item
        for item in memory.get("open_items", [])
        if isinstance(item, dict)
        and item.get("kind") == "failed_steps"
        and int(item.get("retry_count") or 0) >= 3
    ]
    assert stuck_remaining == []
    # Acceptance: evicted_items +5
    evicted_items = memory.get("evicted_items", [])
    assert len(evicted_items) == 5
    assert all(
        entry.get("evict_reason") == "stuck_24h_retry_3"
        and entry.get("actor") == "auto"
        and isinstance(entry.get("original_item"), dict)
        for entry in evicted_items
    )

    # Governance audit: loop_evicted record was written
    audit_rows = _read_governance_audit(50)
    evict_records = [r for r in audit_rows if r.get("action") == "loop_evicted"]
    assert len(evict_records) == 1
    record = evict_records[0]
    assert record["evicted_count"] == 5
    assert record["reasons"]["stuck_24h_retry_3"] == 5
    assert record["reasons"]["aged_out_7d"] == 0
    assert record["source"] == "self_maintenance_loop_runner"


# ---------------------------------------------------------------------------
# Eviction rule coverage
# ---------------------------------------------------------------------------


def test_evict_keeps_fresh_failed_step_with_low_retry(monkeypatch, tmp_path):
    """failed_steps younger than 24h or with retry_count < 3 are kept."""
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))

    fresh_young = _stuck_failed_step(
        "run-young",
        age_seconds=LOOP_EVICT_STUCK_AGE_SECONDS - 60,  # 23h59m
        retry_count=5,
    )
    fresh_low_retry = _stuck_failed_step(
        "run-low-retry",
        age_seconds=LOOP_EVICT_STUCK_AGE_SECONDS + 60,  # 24h+ but only retry 2
        retry_count=2,
    )
    _seed_memory_file(
        memory_path,
        open_items=[fresh_young, fresh_low_retry],
    )

    result = evict_loop_memory_items(actor="manual", note="manual veto")

    assert result["evicted_count"] == 0
    memory = _load_loop_memory()
    assert len(memory["open_items"]) == 2
    assert memory.get("evicted_items") == []


def test_evict_ages_out_7d_old_item_of_any_kind(monkeypatch, tmp_path):
    """Items older than 7d are evicted regardless of kind or retry_count."""
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))

    ancient = _stuck_failed_step(
        "run-ancient",
        age_seconds=LOOP_EVICT_AGE_OUT_SECONDS + 60,
        retry_count=0,
    )
    ancient["kind"] = "automated_remediation"  # not failed_steps, but >7d old
    _seed_memory_file(memory_path, open_items=[ancient])

    result = evict_loop_memory_items(actor="manual")

    assert result["evicted_count"] == 1
    assert result["reasons"]["aged_out_7d"] == 1
    memory = _load_loop_memory()
    assert memory["open_items"] == []
    assert memory["evicted_items"][0]["evict_reason"] == "aged_out_7d"

    audit_rows = _read_governance_audit(20)
    evict_records = [r for r in audit_rows if r.get("action") == "loop_evicted"]
    assert len(evict_records) == 1
    assert evict_records[0]["reasons"]["aged_out_7d"] == 1
    assert evict_records[0]["actor"] == "manual"


def test_evict_caps_evicted_items_at_max(monkeypatch, tmp_path):
    """evicted_items is capped at LOOP_EVICT_MAX_ITEMS (=100)."""
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))

    # Pre-fill evicted_items with 95 existing entries, then evict 10 new items
    pre_existing = [
        {
            "actor": "auto",
            "evicted_at": _iso(_utc_now() - timedelta(hours=1)),
            "evict_reason": "stuck_24h_retry_3",
            "original_item": {"run_id": f"old-{i}"},
        }
        for i in range(95)
    ]
    new_items = [
        _stuck_failed_step(
            f"run-new-{i}",
            age_seconds=LOOP_EVICT_STUCK_AGE_SECONDS + 60,
            retry_count=LOOP_EVICT_STUCK_RETRY_THRESHOLD,
        )
        for i in range(10)
    ]
    _seed_memory_file(
        memory_path,
        open_items=new_items,
        evicted_items=pre_existing,
    )

    result = evict_loop_memory_items(actor="auto")

    assert result["evicted_count"] == 10
    memory = _load_loop_memory()
    assert len(memory["evicted_items"]) == 100  # 95 + 10, capped at 100
    # The newest 100 should be kept (95 existing + 5 newest evictions).
    # The 5 oldest existing entries should be dropped.
    evicted_run_ids = [entry["original_item"].get("run_id") for entry in memory["evicted_items"]]
    # All 10 newly evicted run IDs are present
    for i in range(10):
        assert f"run-new-{i}" in evicted_run_ids
    # Oldest 5 pre-existing entries are dropped
    for i in range(5):
        assert f"old-{i}" not in evicted_run_ids


def test_evict_preserves_evicted_item_metadata(monkeypatch, tmp_path):
    """Each evicted entry includes actor, evicted_at, evict_reason, original_item."""
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))

    item = _stuck_failed_step(
        "run-meta",
        age_seconds=LOOP_EVICT_STUCK_AGE_SECONDS + 60,
        retry_count=3,
    )
    _seed_memory_file(memory_path, open_items=[item])

    result = evict_loop_memory_items(
        actor="manual",
        note="test-veto",
        admin_user_id=42,
    )

    assert result["evicted_count"] == 1
    entry = result["evicted_items"][0]
    assert entry["actor"] == "manual"
    assert entry["evict_reason"] == "stuck_24h_retry_3"
    assert entry["original_item"]["run_id"] == "run-meta"
    assert entry["note"] == "test-veto"
    assert entry["admin_user_id"] == 42
    assert entry["evicted_at"]  # ISO timestamp present


def test_evict_with_empty_open_items_returns_zero(monkeypatch, tmp_path):
    """Eviction on empty open_items is a no-op and writes no audit record."""
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))
    _seed_memory_file(memory_path, open_items=[])

    result = evict_loop_memory_items(actor="auto")

    assert result["evicted_count"] == 0
    assert result["evicted_items"] == []
    audit_rows = _read_governance_audit(10)
    assert all(r.get("action") != "loop_evicted" for r in audit_rows)


def test_evict_does_not_raise_when_audit_write_fails(monkeypatch, tmp_path):
    """If the governance audit write throws, eviction still returns the summary."""
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT",
        str(tmp_path / "missing" / "audit.jsonl"),
    )

    item = _stuck_failed_step(
        "run-audit-fail",
        age_seconds=LOOP_EVICT_STUCK_AGE_SECONDS + 60,
        retry_count=3,
    )
    _seed_memory_file(memory_path, open_items=[item])

    # Make _append_governance_audit raise
    monkeypatch.setattr(
        loop_runner,
        "_append_governance_audit",
        lambda record: (_ for _ in ()).throw(RuntimeError("simulated")),
    )

    result = evict_loop_memory_items(actor="auto")

    # Eviction still happened; audit write failed silently
    assert result["evicted_count"] == 1
    memory = _load_loop_memory()
    assert memory["open_items"] == []
    assert len(memory["evicted_items"]) == 1


# ---------------------------------------------------------------------------
# Governance audit records visible to UI
# ---------------------------------------------------------------------------


def test_governance_audit_record_structure(monkeypatch, tmp_path):
    """The loop_evicted record matches what the governance UI expects."""
    memory_path = tmp_path / "loop_memory.json"
    audit_path = tmp_path / "governance_audit.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(audit_path))
    _seed_memory_file(
        memory_path,
        open_items=[
            _stuck_failed_step(
                "run-a",
                age_seconds=LOOP_EVICT_STUCK_AGE_SECONDS + 60,
                retry_count=3,
            ),
            _stuck_failed_step(
                "run-b",
                age_seconds=LOOP_EVICT_AGE_OUT_SECONDS + 60,
                retry_count=0,  # aged_out_7d
            ),
        ],
    )

    evict_loop_memory_items(actor="manual", note="manual-veto-note")

    audit_rows = _read_governance_audit(10)
    record = next(r for r in audit_rows if r.get("action") == "loop_evicted")
    # Required fields for governance UI
    assert record["action"] == "loop_evicted"
    assert record["actor"] == "manual"
    assert record["created_at"]
    assert record["evicted_count"] == 2
    assert record["ok"] is True
    assert record["source"] == "self_maintenance_loop_runner"
    assert record["status"] == "evicted"
    assert record["note"] == "manual-veto-note"
    assert record["reasons"]["stuck_24h_retry_3"] == 1
    assert record["reasons"]["aged_out_7d"] == 1
    assert len(record["evicted_items"]) == 2
