from __future__ import annotations

from copy import deepcopy

import pytest

from modstore_server.self_maintenance_memory_reconciliation import (
    reconcile_completed_loop_memory_from_ledger,
)

pytestmark = pytest.mark.release_gate


@pytest.mark.parametrize("sha", ["a" * 40, "b" * 64, "a" * 41, "a" * 63, "", "g" * 40])
def test_verified_merge_closes_resumed_failures_and_updates_recent_run(monkeypatch, sha):
    memory = {
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
            "merge_sha": sha,
            "ok": True,
            "para_task_id": "task-1",
            "run_id": "merged-run",
            "status": "completed_merged",
        },
    ]
    writes = []
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._read_ledger",
        lambda limit: rows,
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._write_loop_memory",
        lambda value: writes.append(value),
    )

    before = deepcopy(memory)
    result = reconcile_completed_loop_memory_from_ledger()
    if sha not in ("a" * 40, "b" * 64):
        assert result == {"closed_count": 0, "reconciled_run_ids": [], "updated_runs": 0}
        assert memory == before
        assert writes == []
        return

    assert result == {
        "closed_count": 2,
        "reconciled_run_ids": ["merged-run"],
        "updated_runs": 1,
    }
    assert [item["run_id"] for item in memory["open_items"]] == ["unrelated-run"]
    assert memory["recent_runs"][0] == {
        "deployment_verified": True,
        "merge_sha": sha,
        "run_id": "merged-run",
        "status": "completed_merged",
    }
    assert memory["completed_merge_reconciliations"] == ["merged-run"]
    assert len(writes) == 1


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
        "modstore_server.self_maintenance_loop_runner._read_ledger",
        lambda limit: rows,
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._write_loop_memory",
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
        "modstore_server.self_maintenance_loop_runner._read_ledger",
        lambda limit: rows,
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._write_loop_memory",
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
