"""Durable, bounded discovery of original deliveries outside the recent-run view."""

from __future__ import annotations

import io
import json

import pytest

from modstore_server.maintenance_loop import deployment, outcomes, store
from modstore_server.self_maintenance_deploy_receipts import DeploymentReceiptError
from modstore_server.self_maintenance_gh_gateway import GhActionsDeploymentGateway
from tests.test_self_maintenance_async_delivery import MERGE_SHA, GitHubFixture, _writes


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(tmp_path / "loop.jsonl"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "memory.json"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEASE_FILE", str(tmp_path / "loop.lock"))


def request(run_id="old-loop", task_id="old-task"):
    return {
        "event": "merge_requested",
        "ok": True,
        "status": "pending",
        "run_id": run_id,
        "para_task_id": task_id,
        "branch": "repair/original",
        "branch_head_sha": MERGE_SHA,
    }


def test_evicted_request_enters_original_delivery_reconciliation(ledger, monkeypatch):
    store._append_ledger(request())
    recent = [{"run_id": f"new-{index}", "status": "completed"} for index in range(25)]
    for row in recent:
        store._append_ledger({**row, "phase": "complete"})
    memory = {"recent_runs": recent[-20:], "open_items": []}
    calls = []
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **kwargs: (
            calls.append(kwargs)
            or {"enabled": True, "ok": False, "reason": "workflow_not_completed"}
        ),
    )
    outcomes._reconcile_requested_merge_feedback(
        memory,
        api_base="https://para.invalid",
        task_fetcher=lambda *_: {"status": "merged", "merge_commit_sha": MERGE_SHA},
    )
    assert calls == [
        {
            "run_id": "old-loop",
            "merge_result": {
                "ok": True,
                "merge_commit_sha": MERGE_SHA,
                "remote_task_id": "old-task",
                "branch": "repair/original",
            },
        }
    ]
    assert memory["recent_runs"] == recent[-20:]


def tick(fetcher):
    with store._exclusive_loop_lease() as acquired:
        assert acquired
        memory = store._load_loop_memory()
        result = outcomes._reconcile_requested_merge_feedback(
            memory,
            api_base="https://para.invalid",
            task_fetcher=fetcher,
        )
        if result["changed"]:
            store._write_loop_memory(memory)
    return memory


@pytest.mark.parametrize("recent_unknown", [False, True])
def test_persisted_pages_make_bounded_progress_past_unknown_first_page(
    ledger, monkeypatch, recent_unknown
):
    for index in range(store.DELIVERY_RECOVERY_RUNS * 2 + 1):
        store._append_ledger(request(f"loop-{index}", f"task-{index}"))
    for index in range(store.DELIVERY_RECOVERY_ROWS + 17):
        store._append_ledger({"phase": "complete", "run_id": f"new-{index}", "status": "completed"})
    if recent_unknown:
        store._write_loop_memory({
            "recent_runs": [
                {**request(f"loop-{index}", f"task-{index}"), "status": "completed_merge_requested"}
                for index in range(store.DELIVERY_RECOVERY_RUNS)
            ],
            "open_items": [],
        })
    calls, checked, reads = [], [], []
    original = store._read_delivery_row

    def observed(handle, end, budget):
        row = original(handle, end, budget)
        if row is not None:
            reads.append(row)
        return row

    def fetch(_base, task_id):
        checked.append(task_id)
        return (
            {"status": "in_progress"}
            if int(task_id.split("-")[-1]) < store.DELIVERY_RECOVERY_RUNS
            else {"status": "merged", "merge_commit_sha": MERGE_SHA}
        )

    monkeypatch.setattr(store, "_read_delivery_row", observed)
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **kwargs: (calls.append(kwargs["run_id"]) or {"enabled": True, "ok": False}),
    )
    seen_progress = []
    for _ in range(12):
        reads.clear()
        memory = tick(fetch)
        assert len(reads) <= store.DELIVERY_RECOVERY_ROWS
        seen_progress.append(memory.get("delivery_recovery_cursor", {}).get("verify_offset", 0))
        if f"loop-{store.DELIVERY_RECOVERY_RUNS * 2}" in calls:
            break
    assert any(seen_progress)
    assert set(checked) == {
        f"task-{index}" for index in range(store.DELIVERY_RECOVERY_RUNS * 2 + 1)
    }
    assert calls == [
        f"loop-{index}"
        for index in reversed(range(store.DELIVERY_RECOVERY_RUNS, store.DELIVERY_RECOVERY_RUNS * 2))
    ] + [f"loop-{store.DELIVERY_RECOVERY_RUNS * 2}"]


def test_terminal_appended_during_paged_verification_is_seen_before_recovery(ledger):
    original = request()
    store._append_ledger(original)
    for _ in range(store.DELIVERY_RECOVERY_ROWS + 17):
        store._append_ledger({"phase": "heartbeat"})
    ready, cursor = store._pending_delivery_page()
    assert ready == [] and cursor["candidates"]
    store._append_ledger(
        {
            **original,
            "event": "merge_completed",
            "status": "completed_merged",
            "merge_sha": MERGE_SHA,
        }
    )
    recovered = []
    for _ in range(6):
        ready, cursor = store._pending_delivery_page(cursor)
        recovered.extend(ready)
        if not cursor:
            break
    assert recovered == [] and cursor == {}


@pytest.mark.parametrize("status", ["completed_merged", "completed_merge_failed"])
def test_paged_terminal_fences_stale_recent_projection_before_any_fetch(ledger, status):
    original = request()
    store._append_ledger(original)
    for _ in range(store.DELIVERY_RECOVERY_ROWS + 17):
        store._append_ledger({"phase": "heartbeat"})
    store._append_ledger(
        {
            **original,
            "event": "merge_feedback_reconciled",
            "status": status,
            "merge_reconciliation": {
                "status": "merged" if status == "completed_merged" else "failed"
            },
            "deployment_receipt": {"ok": status == "completed_merged"},
        }
    )
    stale = {**original, "status": "completed_merge_requested"}
    store._write_loop_memory({"recent_runs": [dict(stale), stale], "open_items": []})

    def forbidden(*_):
        pytest.fail("an unverified UI projection must never bypass the durable terminal")

    for _ in range(6):
        memory = tick(forbidden)
        if not memory.get("delivery_recovery_cursor"):
            break
    assert all(run["status"] == status for run in memory["recent_runs"])
    assert memory["recent_runs"][0]["deployment_receipt"] == {"ok": status == "completed_merged"}


def test_partial_snapshot_resumes_after_the_original_append_completes(ledger):
    for _ in range(store.DELIVERY_RECOVERY_ROWS):
        store._append_ledger({"phase": "heartbeat"})
    raw = json.dumps(request()).encode() + b"\n"
    with store.ledger_path().open("ab") as handle:
        handle.write(raw[: len(raw) // 2])
    ready, cursor = store._pending_delivery_page()
    assert not ready and cursor["offset"] < cursor["end"]
    with pytest.raises(ValueError, match="incomplete or oversized"):
        store._pending_delivery_page(cursor)
    with store.ledger_path().open("ab") as handle:
        handle.write(raw[len(raw) // 2 :])
    recovered = []
    for _ in range(4):
        ready, cursor = store._pending_delivery_page(cursor)
        recovered.extend(ready)
        if not cursor:
            break
    assert [row["run_id"] for row in recovered] == ["old-loop"]
    assert cursor == {}


def test_byte_budget_leaves_partial_rows_for_the_next_tick():
    class CountedReader(io.BytesIO):
        bytes_read = 0

        def readline(self, size=-1):
            raw = super().readline(size)
            self.bytes_read += len(raw)
            return raw

    raw = json.dumps({"phase": "heartbeat"}).encode() + b"\n"
    handle = CountedReader(raw * 2)
    limit = len(raw) + 4
    budget = {"rows": store.DELIVERY_RECOVERY_ROWS, "bytes": limit}
    assert store._read_delivery_row(handle, len(raw) * 2, budget)
    assert store._read_delivery_row(handle, len(raw) * 2, budget) is None
    assert handle.tell() == len(raw)
    assert handle.bytes_read == limit
    assert store._read_delivery_row(
        handle, len(raw) * 2, {"rows": 1, "bytes": store.DELIVERY_RECOVERY_BYTES}
    )


def test_conflicting_request_and_orphan_dispatch_cannot_authorize_recovery(ledger):
    store._append_ledger(request())
    store._append_ledger({**request(), "para_task_id": "different-task"})
    store._append_ledger(
        {
            "event": "deploy_dispatch_intent",
            "run_id": "orphan",
            "merge_sha": MERGE_SHA,
            "status": "submitting",
        }
    )
    assert store._pending_delivery_page() == ([], {})


def test_original_merge_sha_cannot_change_when_pending_run_is_rediscovered(ledger, monkeypatch):
    store._append_ledger(request())
    store._append_ledger(
        {
            "phase": "deployment",
            "event": "deploy_verification_failed",
            "run_id": "old-loop",
            "merge_sha": MERGE_SHA,
        }
    )
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **_: pytest.fail("changed release cannot dispatch"),
    )
    tick(lambda *_: {"status": "merged", "merge_commit_sha": "d" * 40})


@pytest.mark.parametrize("unknown", [False, True])
def test_evicted_delivery_recovers_original_workflow_without_replay(ledger, monkeypatch, unknown):
    class DeferredGateway(GitHubFixture):
        ready = False

        def wait_for_success(self, receipt):
            if not self.ready:
                raise DeploymentReceiptError("workflow_not_completed")
            return super().wait_for_success(receipt)

    remote = []
    first = DeferredGateway(remote)
    first.lose_response, first.accept = unknown, not unknown
    current = [first]
    monkeypatch.setattr(GhActionsDeploymentGateway, "from_environment", lambda **_: current[0])
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", "0")
    store._append_ledger(request())
    fetch = lambda *_: {"status": "merged", "merge_commit_sha": MERGE_SHA}
    tick(fetch)
    assert len(_writes(first)) == 1
    newer = [{"run_id": f"new-{index}", "status": "completed"} for index in range(25)]
    for row in newer:
        store._append_ledger({**row, "phase": "complete"})
    store._write_loop_memory({"recent_runs": newer[-20:], "open_items": []})
    restarted = DeferredGateway(remote)
    restarted.ready = True
    current[0] = restarted
    for _ in range(3):
        tick(fetch)
    assert _writes(restarted) == []
    rows = store._read_ledger(limit=0)
    assert len([row for row in rows if row.get("event") == "merge_requested"]) == 1
    terminal = [row for row in rows if row.get("event") == "delivery_reconciled"]
    if unknown:
        assert terminal == [] and remote == []
        assert any(row.get("reason") == "deployment_dispatch_outcome_unknown" for row in rows)
    else:
        assert len(terminal) == 1 and len(remote) == 1
        assert terminal[0]["run_id"] == "old-loop"
        assert terminal[0]["merge_sha"] == MERGE_SHA
        assert terminal[0]["deployment_receipt"]["staging"]["workflow_run_id"] == "900"
        assert store._load_loop_memory()["recent_runs"] == newer[-20:]
