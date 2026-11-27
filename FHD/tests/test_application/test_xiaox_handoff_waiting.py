"""Exercise child handoff at real SQL checkpoints, before and after independent QC."""

from __future__ import annotations

import copy

import pytest

from app.application.agent_orchestrator import stale_run_reconciler, step_execution
from app.db.models.agent import AgentTaskExecutionRecord
from app.infrastructure.xiaox.receipt_projection import (
    refresh_xiaox_receipts,
    resume_ready_xiaox_runs,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry
from tests.test_routes.test_xiaox_receipt_projection import receipt_task as receipt_task


@pytest.mark.parametrize("outcome", ["completed", "unknown"])
def test_receipt_during_child_qc_does_not_invent_an_unknown_effect(
    receipt_task, monkeypatch, outcome
):
    state = receipt_task
    state.outcome = outcome
    verify = step_execution.verify_step_result
    observations = []

    def observe_before_qc(**kwargs):
        child = state.repository.get(state.child_id)
        assert child.status == "running"
        assert child.tool_calls[0].metadata["verification"]["accepted"] is False
        # The production executor has committed the raw receipt. A concurrent
        # reader opens new SQL sessions while that same worker enters QC.
        for _ in range(2):
            rows = state.store.receipt_snapshot(state.parent_id)
            observations.append(copy.deepcopy(rows[0]["receipt"]))
        return verify(**kwargs)

    monkeypatch.setattr(step_execution, "verify_step_result", observe_before_qc)
    state.complete_child()
    expected = "running" if outcome == "completed" else "unknown"
    assert [row["status"] for row in observations] == [expected, expected]
    assert all(row["verified"] is False for row in observations)
    parent = state.repository.get(state.parent_id)
    assert bool(parent.metadata.get("non_retryable")) is (outcome == "unknown")
    settled = state.store.receipt_snapshot(state.parent_id)[0]
    assert settled["state"] == outcome
    assert settled["receipt"]["verified"] is (outcome == "completed")
    assert state.effect_count() == 1
    assert len(state.repository.get(state.child_id).tool_calls) == 1


@pytest.mark.parametrize("late_state", ["running", "unknown"])
def test_old_child_receipt_cannot_replace_new_verified_completion(
    receipt_task, monkeypatch, late_state
):
    state = receipt_task
    verify = step_execution.verify_step_result
    pending = []

    def delay_snapshot(**kwargs):
        pending.extend(copy.deepcopy(state.store.receipt_snapshot(state.parent_id)))
        return verify(**kwargs)

    monkeypatch.setattr(step_execution, "verify_step_result", delay_snapshot)
    state.complete_child()
    completed = state.store.receipt_snapshot(state.parent_id)[0]
    parent = state.repository.get(state.parent_id)
    stale = pending[0]
    assert stale["receipt"]["child_updated_at"] < completed["receipt"]["child_updated_at"]
    # An older worker/reader can still deliver its pre-fix QC observation.
    stale["receipt"]["status"] = late_state
    if late_state == "unknown":
        stale["receipt"].update(outcome="unknown", reconciliation_required=True)
    state.store.record_call(
        state.parent_id,
        stale["call_id"],
        child_run_id=stale["child_run_id"],
        receipt=stale["receipt"],
    )
    stored = state.store.get(state.parent_id)
    assert stored.metadata["calls"][stale["call_id"]]["receipt"] == completed["receipt"]
    assert not stored.run.metadata.get("non_retryable")
    for key in ("reserved_cost_units", "ai_cost_units_total"):
        assert stored.run.metadata.get(key) == parent.metadata.get(key)
    assert state.effect_count() == 1


def test_unversioned_unknown_receipt_still_requires_reconciliation(receipt_task):
    from app.infrastructure.xiaox.receipts import _unknown

    state = receipt_task
    state.complete_child()
    completed = state.store.receipt_snapshot(state.parent_id)[0]
    missing = _unknown(completed)
    assert "child_updated_at" not in missing
    state.store.record_call(
        state.parent_id, completed["call_id"], child_run_id=state.child_id, receipt=missing
    )
    stored = state.store.get(state.parent_id)
    assert stored.metadata["calls"][completed["call_id"]]["state"] == "unknown"
    assert stored.run.metadata["non_retryable"] is True
    assert stored.run.metadata["recovery"]["state"] == "manual_reconciliation_required"
    assert state.effect_count() == 1 and state.resume_count == 0


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_late_child_receipt_does_not_resume_a_controlled_parent(receipt_task, action):
    state = receipt_task
    state.complete_child()
    response = state.client.post(f"/api/agent/runs/{state.parent_id}/{action}", json={})
    assert response.status_code == 200, response.text
    expected = "cancelled" if action == "cancel" else "paused"
    assert state.repository.get(state.parent_id).status == expected
    rows = state.store.receipt_snapshot(state.parent_id)
    assert rows[0]["state"] == "completed"
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    assert state.repository.get(state.parent_id).status == expected
    assert state.queue.get(state.parent_id).state == expected
    assert state.effect_count() == 1 and state.resume_count == 0


def test_failed_wakeup_commit_is_recovered_once_after_repository_reopen(receipt_task, monkeypatch):
    from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository

    state = receipt_task
    state.complete_child()
    enqueue = state.queue.enqueue_in_session

    def interrupt_commit(db, run, **kwargs):
        enqueue(db, run, **kwargs)
        raise OSError("injected failure after queue write and before commit")

    monkeypatch.setattr(state.queue, "enqueue_in_session", interrupt_commit)
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    state.repository = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    set_agent_run_repository_for_tests(state.repository)
    parent = state.repository.get(state.parent_id)
    assert parent.final_output["xiaox_result"]["exit_status"] == "continuation_pending"
    assert not parent.metadata["runtime_requests"]
    assert not parent.metadata.get("_xiaox_queued_request")
    assert state.queue.get(state.parent_id).state == "waiting_approval"
    assert state.effect_count() == 1 and state.resume_count == 0

    monkeypatch.setattr(state.queue, "enqueue_in_session", enqueue)
    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    parent = state.drain(state.parent_id)
    assert parent.status == "completed", parent.final_output
    assert state.effect_count() == state.resume_count == 1


def test_two_scanners_enqueue_one_continuation_from_the_same_sql_parent(receipt_task, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Barrier

    from app.infrastructure.xiaox import queued_runtime

    state = receipt_task
    state.complete_child()
    ready = Barrier(2)
    enqueue = queued_runtime.enqueue_resume

    def race_admission(store, parent, mutation):
        assert parent.run_id == state.parent_id
        ready.wait(timeout=10)
        return enqueue(store, parent, mutation)

    monkeypatch.setattr(queued_runtime, "enqueue_resume", race_admission)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(copy_context().run, resume_ready_xiaox_runs, repository=state.repository)
            for _ in range(2)
        ]
        assert sorted(future.result(timeout=20) for future in futures) == [0, 1]
    parent = state.repository.get(state.parent_id)
    assert len(parent.metadata["runtime_requests"]) == 1
    assert state.queue.get(parent.run_id).state == "queued"
    assert state.effect_count() == 1 and state.resume_count == 0
    parent = state.drain(state.parent_id)
    assert parent.status == "completed", parent.final_output
    assert state.effect_count() == state.resume_count == 1


def test_restart_preserves_pending_readback_and_wakes_the_original_parent(
    receipt_task, monkeypatch
):
    from app.application.agent_orchestrator import verification_readback

    state = receipt_task
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    state.outcome, state.acknowledged_success = "pending", True
    readback = verification_readback.verify_independent_result
    source_ready = False

    def delayed_readback(**kwargs):
        if not source_ready:
            return {"status": "inconclusive", "code": "source_pending", "checks": []}
        return readback(**kwargs)

    monkeypatch.setattr(verification_readback, "verify_independent_result", delayed_readback)
    state.complete_child()
    child = state.repository.get(state.child_id)
    assert child.status == "blocked" and child.metadata["recovery"]["state"] == "result_pending"
    parent = refresh_xiaox_receipts(
        state.repository.get(state.parent_id), repository=state.repository
    )
    assert parent.status == "running" and state.queue.get(parent.run_id).state == "waiting_approval"
    before = parent.to_dict()

    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    assert state.repository.get(parent.run_id).to_dict() == before
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    assert state.effect_count() == 1
    source_ready = True
    response = state.client.post(f"/api/agent/runs/{state.child_id}/verify")
    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is True
    child = state.drain(state.child_id)
    assert child.status == "completed"

    # The dispatcher scan resumes without another user message or result GET.
    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    parent = state.drain(state.parent_id)
    assert parent.status == "completed", parent.final_output
    assert state.resume_count == state.effect_count() == 1
    assert len(state.repository.get(state.child_id).tool_calls) == 1


@pytest.mark.parametrize("tamper", ["lease", "owner", "tenant", "task", "goal", "coordinator"])
def test_parked_queue_label_alone_cannot_exempt_an_interrupted_parent(
    receipt_task, monkeypatch, tamper
):
    state = receipt_task
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    state.complete_child()
    parent = refresh_xiaox_receipts(
        state.repository.get(state.parent_id), repository=state.repository
    )
    assert parent.status == "running"
    if tamper in {"goal", "coordinator"}:

        def change(run, binding):
            if tamper == "goal":
                run.metadata["runtime_goal_contract"]["request"]["text"] = "different request"
            else:
                binding["coordinator_active"] = True

        state.store.update(parent.run_id, change)
    else:
        with state.actor.factory.begin() as db:
            execution = db.get(AgentTaskExecutionRecord, parent.run_id)
            if tamper == "lease":
                execution.lease_owner = "unsettled-worker"
            elif tamper == "owner":
                execution.user_id = "foreign-owner"
            elif tamper == "tenant":
                execution.tenant_id = "foreign-tenant"
            else:
                execution.task_id = "different-task"

    assert stale_run_reconciler.reconcile_stale_running_runs() == 1
    parent = state.repository.get(state.parent_id)
    assert parent.status in {"unknown", "failed"}
    assert parent.metadata["interrupted"]["error_code"] == "interrupted_by_restart"
    assert state.effect_count() == 1 and state.resume_count == 0
