"""Restart reconciliation keeps failed file evidence and queues only parent planning."""

import copy

import pytest

from app.application.agent_orchestrator.result_verification import (
    _scope,
    bind_execution_receipt,
    canonical_hash,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_context import apply_task_context
from app.db.models.agent import AgentTaskExecutionRecord
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.domain.task_lifecycle.control import SessionBook
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from app.infrastructure.xiaox.receipt_projection import refresh_xiaox_receipts
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry
from tests.test_infrastructure.test_workbook_failed_receipt import bound_failure


@pytest.mark.parametrize("barrier", [None, "model_unknown", "leased", "foreign_effect", "paused"])
def test_known_file_failure_reconciles_original_unknown_without_replaying(
    runtime_entry, monkeypatch, barrier
):
    state = runtime_entry
    parent = AgentRun(
        user_id=str(state.actor.user_id),
        message="Create and verify an isolated workbook",
        status="running",
        intent="xiaox.runtime",
    )
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_context=state.actor.context,
        runtime_completion_mode="business",
    )
    apply_task_context(parent, state.actor.context)
    goal = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=goal, runtime_goal_digest=goal["digest"])
    state.repository.save(parent)
    state.queue.enqueue(parent)
    store = XiaoxBindingStore(state.repository)
    grant = store.create(parent.run_id)
    child, step, call = bound_failure(monkeypatch)
    operation = {"tool_id": step.tool_id, "action": step.action, "params": step.params}
    claimed, _ = store.claim_call(
        parent.run_id,
        "original-write",
        **operation,
        read_only=False,
        isolated_artifact=True,
        generation=grant.binding.metadata["generation"],
    )
    context = {
        **state.actor.context,
        "task_id": claimed["child_task_id"],
        "root_run_id": parent.run_id,
        "parent_run_id": parent.run_id,
    }
    child.user_id = parent.user_id
    child.metadata["runtime_context"] = context
    child.metadata["plan"] = {"nodes": [{"node_id": step.node_id, **copy.deepcopy(operation)}]}
    apply_task_context(child, context)
    contract = call.metadata["verification_contract"]
    contract["scope"] = _scope(child, context)
    contract["contract_sha256"] = canonical_hash(
        {k: v for k, v in contract.items() if k != "contract_sha256"}
    )
    bind_execution_receipt(call)
    verify_step_result(run=child, step=step, call=call, context=context)
    state.repository.save(child)
    store.record_call(
        parent.run_id,
        "original-write",
        child_run_id=child.run_id,
        receipt={"run_id": child.run_id, "task_id": claimed["child_task_id"], "status": "unknown"},
    )

    def stopped(run, metadata):
        metadata["runtime_status"] = "failed"
        run.status = "blocked"
        run.metadata.update(
            non_retryable=True, recovery={"state": "manual_reconciliation_required"}
        )
        run.final_output["xiaox_result"] = {
            "exit_status": "unknown",
            "business_receipts": [
                {"call_id": "original-write", **copy.deepcopy(metadata["calls"]["original-write"])}
            ],
        }
        if barrier == "model_unknown":
            metadata["model_requests"] = {"original": {"state": "unknown"}}

    store.update(parent.run_id, stopped)
    store.close(parent.run_id, "paused" if barrier == "paused" else "completed")
    with state.actor.factory() as db:
        execution = db.get(AgentTaskExecutionRecord, parent.run_id)
        execution.state, execution.last_error_code = "unknown", "needs_verification"
        if barrier == "leased":
            execution.lease_owner = "original-worker"
        body = SessionBook(db).get("agent", str(state.actor.tenant_id), parent.run_id)
        body["effects"] = (
            ["child:foreign:effect"]
            if barrier == "foreign_effect"
            else [f"child:{child.run_id}:{step.step_id}"]
        )
        SessionBook(db).put("agent", str(state.actor.tenant_id), parent.run_id, body)
        db.commit()
    # Reopen SQL repositories, as in a host restart. No business dispatcher runs.
    repository = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    before = repository.get(child.run_id).to_dict()
    from app.application.agent_orchestrator.verification_workbook import (
        known_workbook_expectation_failure,
    )

    assert known_workbook_expectation_failure(child, step, call)

    refresh_xiaox_receipts(repository.get(parent.run_id), repository=repository)
    recovered = repository.get(parent.run_id)
    assert repository.get(child.run_id).to_dict() == before
    assert state.calls == []
    if barrier:
        assert recovered.metadata["non_retryable"] is True
        assert recovered.status == "blocked"
    else:
        assert recovered.status == "running", recovered.to_dict()
        assert recovered.final_output["xiaox_result"]["exit_status"] == "continuation_pending"
        assert not recovered.final_output["xiaox_result"]["business_completed"]
        assert "non_retryable" not in recovered.metadata
        assert (
            recovered.final_output["xiaox_result"]["business_receipts"][0]["receipt"]["verified"]
            is False
        )
        snapshot = recovered.to_dict()
        refresh_xiaox_receipts(repository.get(parent.run_id), repository=repository)
        reread = repository.get(parent.run_id).to_dict()
        reread.pop("updated_at")
        snapshot.pop("updated_at")
        assert reread == snapshot
