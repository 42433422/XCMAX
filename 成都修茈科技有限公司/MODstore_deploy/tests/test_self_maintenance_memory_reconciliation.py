from __future__ import annotations

import pytest

from modstore_server.maintenance_loop import store
from modstore_server.self_maintenance_memory_reconciliation import (
    reconcile_completed_loop_memory_from_ledger,
)

pytestmark = pytest.mark.release_gate


def test_verified_merge_closes_resumed_failures_and_updates_recent_run(monkeypatch):
    memory = {
        "pending_execution": {"task_id": "original-task", "request_id": "original-request"},
        "closed_items": [],
        "open_items": [
            {
                "branch": "devfleet/cursor/fix",
                "kind": "failed_steps",
                "para_task_id": "task-1",
                "run_id": "failed-run",
                "steps": ["review"],
            },
            {
                "branch": "devfleet/cursor/fix",
                "kind": "automated_remediation",
                "reason": "structured_qa_black_not_passed",
                "run_id": "held-run",
                "task_id": "task-1",
            },
            {
                "branch": "devfleet/cursor/unrelated",
                "kind": "automated_remediation",
                "run_id": "unrelated-run",
                "task_id": "task-2",
            },
        ],
        "recent_runs": [{"run_id": "merged-run", "status": "completed_merge_requested"}],
    }
    rows = [
        {
            "branch": "devfleet/cursor/fix",
            "para_task_id": "task-1",
            "phase": "complete",
            "resume_candidate": {
                "branch": "devfleet/cursor/fix",
                "failed_run_id": "held-run",
                "para_task_id": "task-1",
            },
            "run_id": "merged-run",
            "status": "completed_merge_requested",
        },
        {
            "branch": "devfleet/cursor/fix",
            "event": "merge_completed",
            "merge_sha": "a" * 40,
            "ok": True,
            "para_task_id": "task-1",
            "run_id": "merged-run",
            "status": "completed_merged",
        },
    ]
    writes = []
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._read_ledger",
        lambda limit: rows,
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._write_loop_memory",
        lambda value: writes.append(value),
    )

    result = reconcile_completed_loop_memory_from_ledger()

    assert result == {
        "closed_count": 2,
        "reconciled_run_ids": ["merged-run"],
        "updated_runs": 1,
    }
    assert [item["run_id"] for item in memory["open_items"]] == ["unrelated-run"]
    assert memory["recent_runs"][0] == {
        "deployment_verified": True,
        "merge_sha": "a" * 40,
        "run_id": "merged-run",
        "status": "completed_merged",
    }
    assert memory["completed_merge_reconciliations"] == ["merged-run"]
    assert memory["pending_execution"]["task_id"] == "original-task"
    assert len(writes) == 1


def test_merge_reconciler_does_not_read_or_write_during_active_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEASE_FILE", str(tmp_path / "loop.lock"))

    def unexpected_read(*args, **kwargs):
        pytest.fail("an active execution owns the memory transaction")

    monkeypatch.setattr(store, "_read_ledger", unexpected_read)
    monkeypatch.setattr(store, "_load_loop_memory", unexpected_read)
    monkeypatch.setattr(store, "_write_loop_memory", unexpected_read)
    with store._exclusive_loop_lease() as acquired:
        assert acquired
        result = reconcile_completed_loop_memory_from_ledger()
    assert result == {
        "ok": False,
        "status": "skipped_active_lease",
        "changed": False,
        "closed_count": 0,
    }


def test_merge_reconciler_preserves_unreadable_execution_state(monkeypatch, tmp_path):
    memory_path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEASE_FILE", str(tmp_path / "loop.lock"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    monkeypatch.setattr(store, "_read_ledger", lambda **kwargs: [])
    memory_path.write_text('{"pending_execution":', encoding="utf-8")
    before = memory_path.read_bytes()
    result = reconcile_completed_loop_memory_from_ledger()
    assert result["ok"] is False
    assert result["status"] == "waiting_reconciliation"
    assert memory_path.read_bytes() == before


def test_reconciliation_is_idempotent(monkeypatch):
    memory = {
        "completed_merge_reconciliations": ["merged-run"],
        "open_items": [],
        "recent_runs": [],
    }
    rows = [
        {
            "event": "merge_completed",
            "ok": True,
            "run_id": "merged-run",
            "status": "completed_merged",
        }
    ]
    writes = []
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._read_ledger",
        lambda limit: rows,
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._write_loop_memory",
        lambda value: writes.append(value),
    )

    assert reconcile_completed_loop_memory_from_ledger() == {
        "closed_count": 0,
        "reconciled_run_ids": [],
        "updated_runs": 0,
    }
    assert writes == []


def test_fresh_completed_run_reconciles_without_resume_candidate(monkeypatch):
    memory = {
        "completed_merge_reconciliations": ["older-run"],
        "open_items": [
            {
                "branch": "devfleet/cursor/fresh",
                "kind": "failed_steps",
                "run_id": "fresh-run",
                "steps": ["qa"],
            }
        ],
        "recent_runs": [],
    }
    rows = [
        {
            "branch": "devfleet/cursor/fresh",
            "phase": "complete",
            "run_id": "fresh-run",
            "status": "completed_merge_requested",
        },
        {
            "branch": "devfleet/cursor/fresh",
            "event": "merge_completed",
            "merge_sha": "b" * 40,
            "ok": True,
            "run_id": "fresh-run",
            "status": "completed_merged",
        },
    ]
    writes = []
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._read_ledger",
        lambda limit: rows,
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.store._write_loop_memory",
        lambda value: writes.append(value),
    )

    assert reconcile_completed_loop_memory_from_ledger() == {
        "closed_count": 1,
        "reconciled_run_ids": ["fresh-run"],
        "updated_runs": 0,
    }
    assert memory["completed_merge_reconciliations"] == ["older-run", "fresh-run"]
    assert memory["open_items"] == []
    assert len(writes) == 1
