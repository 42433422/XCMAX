"""Frozen verification evidence survives stale and conflicting repository writes."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2


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
