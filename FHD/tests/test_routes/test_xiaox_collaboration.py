"""SQL parent/child settlement; external model responses remain explicit fixtures."""

from __future__ import annotations

import copy

import pytest

from app.application.agent_orchestrator import AgentOrchestrator
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    classification_metadata,
    classify_runtime_result,
)
from app.infrastructure.xiaox.receipt_projection import (
    refresh_xiaox_receipts,
    resume_ready_xiaox_runs,
)
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry
from tests.test_routes.test_xiaox_receipt_projection import receipt_task as receipt_task


def _second_waiting_child(state):
    state.store.receipt_snapshot(state.parent_id)
    binding = state.store.get(state.parent_id)
    grant = state.store.create(
        state.parent_id, runtime_config=copy.deepcopy(binding.metadata["runtime_config"])
    )
    bridge = XiaoxToolBridge(state.store, AgentOrchestrator(repository=state.repository))
    operation = {"tool_id": "customers", "action": "create"}
    pending = bridge.invoke(
        grant.mcp_token,
        "execute_action",
        {
            **operation,
            "params": {"unit_name": "rejected-child"},
            "call_id": "second-write",
            "schema_digest": bridge.invoke(grant.mcp_token, "capability_describe", operation)[
                "capability"
            ]["schema_digest"],
        },
    )
    assert pending["pending_approval"] is True
    rows = state.store.receipt_snapshot(state.parent_id)

    def wait(parent, metadata):
        result = base_runtime_result(parent.run_id)
        parent.status = classify_runtime_result(
            result, rows, classification_metadata(parent), "business", "completed"
        )
        parent.final_output["xiaox_result"] = result
        metadata["runtime_status"] = "completed"

    state.store.update(state.parent_id, wait)
    state.store.close(state.parent_id, "completed")
    return pending["run_id"]


def _reject_waiting_child(state, rejected_id, monkeypatch, *, no_effect_proof=True):
    from app.utils.resilience import rate_limiter

    endpoint = "agent-tool:customers.create"
    monkeypatch.setitem(rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(1))
    assert rate_limiter.check_rate_limit(str(state.actor.tenant_id), endpoint)["allowed"]
    if not no_effect_proof:
        monkeypatch.setattr(
            "app.application.agent_orchestrator.tool_executor._pre_dispatch_refusal",
            lambda result: result,
        )
    approval = state.client.get(f"/api/agent/runs/{rejected_id}").json()["approval"]["grant"]
    response = state.client.post(
        f"/api/agent/runs/{rejected_id}/continue", json={"approval_grant": approval}
    )
    assert response.status_code == 202, response.text
    state.drain(rejected_id)


@pytest.mark.parametrize("no_effect_proof", [True, False])
def test_settled_failed_child_resumes_parent_without_replaying_success(
    receipt_task, monkeypatch, no_effect_proof
):
    from app.domain.task_lifecycle.results import execution_result_proven_not_executed

    state = receipt_task
    state.complete_child()
    rejected_id = _second_waiting_child(state)
    _reject_waiting_child(state, rejected_id, monkeypatch, no_effect_proof=no_effect_proof)
    rejected = state.repository.get(rejected_id)
    assert rejected.status == "failed"
    assert len(rejected.tool_calls) == 1
    assert execution_result_proven_not_executed(rejected.tool_calls[0].output) is no_effect_proof
    original = state.repository.get(state.child_id).to_dict()
    parent = refresh_xiaox_receipts(
        state.repository.get(state.parent_id), repository=state.repository
    )
    result = parent.final_output["xiaox_result"]
    assert not result["business_completed"] and state.effect_count() == 1
    if not no_effect_proof:
        assert result["execution_state"] == "unknown"
        assert resume_ready_xiaox_runs(repository=state.repository) == 0
        assert state.repository.get(state.child_id).to_dict() == original
        return
    assert parent.status == "running", result
    assert result["exit_status"] == "continuation_pending", result
    assert len(result["business_receipts"]) == 2
    assert not result.get("reconciliation_required")
    from app.infrastructure.xiaox.receipts import resume_error

    binding = state.store.get(state.parent_id)
    assert not resume_error(state.store, binding, state.store.receipt_snapshot(state.parent_id))
    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    final = state.drain(state.parent_id)
    assert final.status == "completed", final.final_output
    assert final.final_output["xiaox_result"]["goal_coverage"]["completed"] is True
    assert state.resume_count == 1 and state.effect_count() == 1
    assert state.repository.get(state.child_id).to_dict() == original
    assert len(state.repository.get(rejected_id).tool_calls) == 1


@pytest.mark.parametrize("fence", ["settled_receipt", "goal_digest", "goal_version"])
def test_no_effect_continuation_requires_new_receipt_and_original_goal(
    receipt_task, monkeypatch, fence
):
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.domain.task_lifecycle.results import execution_result_proven_not_executed

    state = receipt_task
    state.complete_child()
    rejected_id = _second_waiting_child(state)
    _reject_waiting_child(state, rejected_id, monkeypatch)
    rows = state.store.receipt_snapshot(state.parent_id)
    failed = next(row for row in rows if row["child_run_id"] == rejected_id)
    assert execution_result_proven_not_executed(failed["receipt"])
    original = state.repository.get(state.child_id).to_dict()

    def change(parent, metadata):
        if fence == "settled_receipt":
            parent.final_output["xiaox_result"]["business_receipts"] = copy.deepcopy(rows)
        elif fence == "goal_digest":
            metadata["goal_digest"] = "different-goal"
        else:
            contract = parent.metadata["runtime_goal_contract"]
            contract["protocol"] += ":unsupported"
            contract["digest"] = canonical_digest(
                {key: value for key, value in contract.items() if key != "digest"}
            )
            parent.metadata["runtime_goal_digest"] = metadata["goal_digest"] = contract["digest"]

    before = state.store.update(state.parent_id, change).run
    parent = refresh_xiaox_receipts(before, repository=state.repository)
    result = parent.final_output["xiaox_result"]
    if fence == "settled_receipt":
        assert parent.status == "blocked" and result["execution_state"] == "partial"
        assert result["reconciliation_required"] is True and result["retryable"] is False
        assert result["verified_operations"] is True
        assert state.queue.get(parent.run_id).last_error_code == "needs_verification"
    else:
        assert parent.to_dict() == before.to_dict()
    assert result["business_completed"] is False
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    assert state.effect_count() == 1 and state.resume_count == 0
    assert state.repository.get(state.child_id).to_dict() == original
    assert len(state.repository.get(rejected_id).tool_calls) == 1


def test_cancelled_child_preserves_partial_success_and_cannot_complete_parent(receipt_task):
    state = receipt_task
    state.complete_child()
    cancelled_id = _second_waiting_child(state)
    response = state.client.post(f"/api/agent/runs/{cancelled_id}/cancel", json={})
    assert response.status_code in {200, 202}, response.text
    assert state.repository.get(cancelled_id).status == "cancelled"
    parent = refresh_xiaox_receipts(
        state.repository.get(state.parent_id), repository=state.repository
    )
    result = parent.final_output["xiaox_result"]
    assert parent.status == "blocked"
    assert result["execution_state"] == "partial", result
    assert result["business_completed"] is False
    assert any(
        row["child_run_id"] == state.child_id and row["receipt"]["verified"]
        for row in result["business_receipts"]
    )
    assert state.queue.get(parent.run_id).state == "failed"
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    assert state.effect_count() == 1


def test_only_failed_child_with_original_no_effect_proof_can_wake_once(receipt_task, monkeypatch):
    from app.utils.resilience import rate_limiter

    state = receipt_task
    endpoint = "agent-tool:customers.create"
    monkeypatch.setitem(rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(1))
    assert rate_limiter.check_rate_limit(str(state.actor.tenant_id), endpoint)["allowed"]
    state.complete_child()
    assert state.repository.get(state.child_id).status == "failed"
    assert state.effect_count() == 0
    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    parent = state.repository.get(state.parent_id)
    assert parent.status == "queued"
    requests = parent.metadata["runtime_requests"]
    assert sum(row.get("source") == "verified_child_receipts" for row in requests.values()) == 1
    assert len(state.repository.get(state.child_id).tool_calls) == 1
    assert state.effect_count() == state.resume_count == 0
