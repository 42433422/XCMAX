"""Frozen verification evidence survives stale and conflicting repository writes."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, get_tool_action_spec


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        yield InMemoryAgentRunRepository()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'verification.db'}")
    try:
        yield SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    finally:
        engine.dispose()


def pending_run(repository):
    step = AgentStep(
        node_id="n", tool_id="customers", action="create", params={"name": "A"}, attempt_count=1
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id="n",
        tool_id="customers",
        action="create",
        params=copy.deepcopy(step.params),
        metadata={"attempt_count": 1},
    )
    run = AgentRun(user_id="1", message="create", status="running", steps=[step], tool_calls=[call])
    freeze_verification_contract(run, step, call, ToolActionSpecV2("customers", "create"), {})
    return repository.save(run)


def completed_receipt(repository, *, pending=False):
    run = pending_run(repository)
    run.steps[0].status = run.tool_calls[0].status = "completed"
    run.steps[0].output = (
        {"success": False, "execution_state": "pending", "request_id": "original"}
        if pending
        else {"success": True, "id": 17}
    )
    run.tool_calls[0].output = copy.deepcopy(run.steps[0].output)
    bind_execution_receipt(run.tool_calls[0])
    return repository.save(run)


def test_pending_to_receipt_then_reverification_keeps_original_fact(repository):
    run = completed_receipt(repository)
    before = copy.deepcopy(run.tool_calls[0])
    run.tool_calls[0].metadata["verification"] = {"status": "inconclusive", "attempt": 2}
    repository.save(run)
    stored = repository.get(run.run_id).tool_calls[0]
    assert stored.output == before.output
    assert stored.metadata["verification_contract"] == before.metadata["verification_contract"]
    assert stored.metadata["verification"]["attempt"] == 2


@pytest.mark.parametrize(
    "change",
    ["output", "status", "params", "identity", "attempt", "contract", "digest", "new_call"],
)
@pytest.mark.parametrize("pending", [False, True])
def test_successful_receipt_conflicts_cannot_overwrite_committed_evidence(
    repository, change, pending
):
    run = completed_receipt(repository, pending=pending)
    original = repository.get(run.run_id)
    call = run.tool_calls[0]
    if change == "output":
        call.output["id"] = 99
    elif change == "status":
        call.status = "failed"
    elif change == "params":
        call.params["name"] = "B"
    elif change == "identity":
        call.action = "delete"
    elif change == "attempt":
        call.metadata["attempt_count"] = 2
    elif change == "contract":
        call.metadata["verification_contract"]["read_only"] = True
    elif change == "digest":
        call.metadata["verification_output_sha256"] = "different"
    else:
        other = copy.deepcopy(call)
        other.call_id = "replacement"
        run.tool_calls.append(other)
    # Context renewal must not turn immutable evidence into a new generation.
    run.metadata["runtime_context"] = {"renewed": True}
    with pytest.raises(ValueError, match="verification"):
        repository.save(run)
    assert repository.get(run.run_id).to_dict() == original.to_dict()


@pytest.mark.parametrize("missing", ["call", "metadata", "receipt"])
def test_omitted_frozen_evidence_is_retained_without_business_replay(repository, missing):
    run = completed_receipt(repository)
    original = copy.deepcopy(run.tool_calls[0])
    if missing == "call":
        run.tool_calls = []
    elif missing == "metadata":
        run.tool_calls[0].metadata = {}
    else:
        run.tool_calls[0].output = {}
        run.tool_calls[0].status = "running"
        run.tool_calls[0].metadata.pop("verification_output_sha256")
    run.metadata["runtime_context"] = {"renewed": True}
    stored = repository.save(run).tool_calls[0]
    assert stored.output == original.output
    assert stored.status == "completed"
    assert stored.metadata["verification_contract"] == original.metadata["verification_contract"]
    assert (
        stored.metadata["verification_output_sha256"]
        == original.metadata["verification_output_sha256"]
    )


def test_legacy_calls_without_verification_contract_keep_previous_save_behavior(repository):
    run = pending_run(repository)
    run.tool_calls[0].metadata = {}
    # A genuinely old record was never frozen; use a separate run identity.
    run.run_id += "_legacy"
    repository.save(run)
    run.tool_calls[0].params["name"] = "legacy update"
    repository.save(run)
    assert repository.get(run.run_id).tool_calls[0].params["name"] == "legacy update"


def test_plain_save_or_unverified_cas_cannot_clear_pending_effect(repository):
    run = completed_receipt(repository, pending=True)
    run.status = "blocked"
    run.metadata.update(non_retryable=True, recovery={"state": "result_pending"})
    previous = repository.save(run)
    for cas in (False, True):
        candidate = copy.deepcopy(previous)
        candidate.metadata.pop("non_retryable")
        candidate.metadata.pop("recovery")
        if cas:
            assert repository.save_if_unchanged(candidate, previous)
        else:
            repository.save(candidate)
        previous = repository.get(run.run_id)
        assert previous.metadata["non_retryable"] is True
        assert previous.metadata["recovery"]["state"] == "result_pending"


@pytest.fixture(params=["memory", "sqlite"])
def parallel_repository(request, tmp_path):
    if request.param == "memory":
        yield InMemoryAgentRunRepository()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'verification.db'}")
    try:
        yield SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    finally:
        engine.dispose()


def _saved_preview(parallel_repository, monkeypatch):
    """A host-bound report for testing parallel_repository invariants, without dispatch."""
    step = AgentStep(
        node_id="preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": "original-upload"},
        attempt_count=1,
        status="waiting_user",
        output={
            "success": True,
            "preview": True,
            "requires_user_decision": True,
            "question": "Continue with valid rows?",
            "resume_params": {"valid_rows_only": True},
        },
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        output=copy.deepcopy(step.output),
        status="completed",
        metadata={"attempt_count": 1},
    )
    run = AgentRun(user_id="1", message="preview", status="waiting_user", steps=[step])
    run.tool_calls = [call]
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    plan = PlanGraph(
        plan_id="bound-preview",
        intent="elt_import",
        nodes=[
            WorkflowNode(
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=copy.deepcopy(step.params),
                risk=step.risk,
                depends_on=list(step.depends_on),
            )
        ],
    )
    run.plan_id = plan.plan_id
    run.metadata["plan"] = plan_to_dict(plan)
    # Repository invariants isolate readback; the grant still binds the full real plan.
    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        lambda **kwargs: {
            "status": "verified",
            "code": "result_preview_verified",
            "checks": [
                {
                    "check_id": "preview",
                    "source": "elt_preview",
                    "status": "passed",
                    "evidence": {
                        "scope": "preview_only",
                        "business_effect_verified": False,
                        "resume_params": copy.deepcopy(kwargs["output"]["resume_params"]),
                    },
                }
            ],
        },
    )
    freeze_verification_contract(run, step, call, get_tool_action_spec("elt_import", "preview"), {})
    bind_execution_receipt(call)
    assert verify_step_result(run=run, step=step, call=call, context={})["accepted"]
    _prepare_bound_preview(run)
    return parallel_repository.save(run)


def _prepare_bound_preview(run):
    from app.application.agent_orchestrator.approval_grant import approval_receipt_claims
    from app.application.agent_orchestrator.result_verification import preview_continuation_params
    from app.application.workflow.workflow_types import (
        plan_fingerprint,
        plan_from_dict,
        plan_to_dict,
    )

    step, call = run.steps[0], run.tool_calls[-1]
    proposed = preview_continuation_params(run, step, call)
    assert proposed == {**call.params, **call.output["resume_params"]}
    plan = plan_from_dict(run.metadata["plan"])
    assert plan is not None
    node = next(node for node in plan.nodes if node.node_id == step.node_id)
    step.params = proposed
    node.params = copy.deepcopy(proposed)
    run.metadata["plan"] = plan_to_dict(plan)
    run.metadata["plan_sha256"] = plan_fingerprint(plan)
    run.metadata["approval_receipt"] = {
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        **approval_receipt_claims(run, step),
    }


def _append_approved_preview(run):
    old, step = run.tool_calls[-1], run.steps[0]
    assert step.params == {**old.params, **old.output["resume_params"]}
    step.attempt_count += 1
    step.status = run.status = "running"
    new = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        metadata={"attempt_count": step.attempt_count, "continued_from_call_id": old.call_id},
    )
    freeze_verification_contract(run, step, new, get_tool_action_spec("elt_import", "preview"), {})
    run.tool_calls.append(new)
    return new


def test_approved_preview_adds_a_fresh_call_and_retains_the_original_receipt(
    parallel_repository, monkeypatch
):
    run = _saved_preview(parallel_repository, monkeypatch)
    original = copy.deepcopy(run.tool_calls[0].to_dict())
    new = _append_approved_preview(run)
    stored = parallel_repository.save(run)
    assert len(stored.tool_calls) == 2
    assert stored.tool_calls[0].to_dict() == original
    assert stored.tool_calls[1].call_id == new.call_id
    assert not stored.tool_calls[1].output
    # An omitted continuation pointer is restored, never silently detached.
    run.tool_calls[1].metadata.pop("continued_from_call_id")
    stored = parallel_repository.save(run)
    assert stored.tool_calls[1].metadata["continued_from_call_id"] == original["call_id"]


@pytest.mark.parametrize(
    "change",
    [
        "missing_link",
        "wrong_link",
        "attempt",
        "input_type",
        "premature_output",
        "premature_completion",
        "two_calls",
        "no_approval",
        "stale_approval",
        "contract",
    ],
)
def test_preview_continuation_cannot_replace_receipts_or_invent_an_attempt(
    parallel_repository, monkeypatch, change
):
    run = _saved_preview(parallel_repository, monkeypatch)
    original = copy.deepcopy(run.to_dict())
    new = _append_approved_preview(run)
    if change == "missing_link":
        new.metadata.pop("continued_from_call_id")
    elif change == "wrong_link":
        new.metadata["continued_from_call_id"] = "other-call"
    elif change == "attempt":
        new.metadata["attempt_count"] = run.steps[0].attempt_count = 3
    elif change == "input_type":
        new.params["valid_rows_only"] = 1
    elif change == "premature_output":
        new.output = {"success": True}
    elif change == "premature_completion":
        new.status = "completed"
    elif change == "two_calls":
        extra = copy.deepcopy(new)
        extra.call_id = "another-fresh-call"
        run.tool_calls.append(extra)
    elif change == "no_approval":
        run.metadata.pop("approval_receipt")
    elif change == "stale_approval":
        run.metadata["approval_receipt"]["params_sha256"] = "old-inputs"
    else:
        new.metadata["verification_contract"]["scope"]["owner_id"] = "other"
    with pytest.raises(ValueError, match="verification"):
        parallel_repository.save(run)
    assert parallel_repository.get(run.run_id).to_dict() == original


def test_continuation_must_link_the_latest_saved_preview_and_cannot_change_old_links(
    parallel_repository, monkeypatch
):
    run = _saved_preview(parallel_repository, monkeypatch)
    second = _append_approved_preview(run)
    parallel_repository.save(run)
    step = run.steps[0]
    second.output = {**step.output, "resume_params": {"accept_suggested": True}}
    second.status = "completed"
    step.output = copy.deepcopy(second.output)
    step.status = run.status = "waiting_user"
    bind_execution_receipt(second)
    assert verify_step_result(run=run, step=step, call=second, context={})["accepted"]
    _prepare_bound_preview(run)
    parallel_repository.save(run)
    original = copy.deepcopy(run.to_dict())
    third = _append_approved_preview(run)
    third.metadata["continued_from_call_id"] = run.tool_calls[0].call_id
    with pytest.raises(ValueError, match="verification"):
        parallel_repository.save(run)
    assert parallel_repository.get(run.run_id).to_dict() == original
    for index in (0, 1):
        changed = parallel_repository.get(run.run_id)
        changed.tool_calls[index].metadata["continued_from_call_id"] = "rewritten-history"
        with pytest.raises(ValueError, match="verification"):
            parallel_repository.save(changed)
    assert parallel_repository.get(run.run_id).to_dict() == original


@pytest.mark.parametrize(
    "hold",
    [
        "non_retryable",
        "manual_reconciliation_required",
        "stream_interruption",
        "blocked",
        "paused",
        "unknown",
        "failed",
        "cancelled",
        "completed",
        "rejected",
    ],
)
def test_stale_preview_snapshot_cannot_bypass_a_persisted_hold(
    parallel_repository, monkeypatch, hold
):
    stale = _saved_preview(parallel_repository, monkeypatch)
    held = parallel_repository.get(stale.run_id)
    if hold == "non_retryable":
        held.metadata[hold] = True
    elif hold == "manual_reconciliation_required":
        held.metadata["recovery"] = {"state": hold}
    elif hold == "stream_interruption":
        held.metadata[hold] = {"worker_pending": True, "business_outcome": "unknown"}
    else:
        held.status = hold
    parallel_repository.save(held)
    persisted = parallel_repository.get(stale.run_id).to_dict()
    _append_approved_preview(stale)
    # The stale worker has a valid new grant and has never seen the saved hold.
    assert not stale.metadata.get("non_retryable")
    assert not stale.metadata.get("recovery")
    assert not stale.metadata.get("stream_interruption")
    with pytest.raises(ValueError, match="verification"):
        parallel_repository.save(stale)
    assert parallel_repository.get(stale.run_id).to_dict() == persisted
