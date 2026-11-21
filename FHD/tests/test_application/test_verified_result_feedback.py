"""Only committed verified receipts can teach the original task's memory."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.result_verification import (
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_planning import RunPlanning
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.application.agent_orchestrator.trace_payloads import agent_node_output
from tests.test_application.test_result_verification_engine import _passed, _receipt
from tests.test_services.test_conversation_service_push import storage as storage


def verified_run(monkeypatch):
    run, step, call, context = _receipt(output={"success": True, "summary": "Created A"})
    run.metadata["task_context"] = {
        "task_id": "task-original",
        "root_run_id": "root-original",
        "turn_id": "turn-original",
    }
    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        lambda **_: _passed(),
    )
    assert verify_step_result(run=run, step=step, call=call, context=context)["accepted"]
    run.status = "completed"
    run.final_output = {"node_outputs": {step.node_id: copy.deepcopy(step.output)}}
    return run


@pytest.fixture
def remember(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.application.agent_runtime.pipeline.agent_runtime_hooks_enabled", lambda: True
    )
    monkeypatch.setattr(
        "app.application.agent_runtime.pipeline.remember_run_outcome",
        lambda **kw: calls.append(kw) or True,
    )
    return calls


def test_verified_feedback_keeps_original_identity_and_deduplicates(monkeypatch, remember):
    run = verified_run(monkeypatch)
    repository = InMemoryAgentRunRepository()
    repository.save(run)
    planning = RunPlanning(repository)
    planning.remember_run_outcome_for(run)
    planning.remember_run_outcome_for(run)
    assert len(remember) == 1
    assert remember[0]["success"] is True
    metadata = remember[0]["metadata"]
    assert metadata["run_id"] == run.run_id
    assert metadata["task_id"] == "task-original"
    assert metadata["root_run_id"] == "root-original"
    assert metadata["turn_id"] == "turn-original"
    assert metadata["tenant_id"] == "7"
    assert metadata["verification_status"] == "verified"
    assert len(metadata["evidence_sha256"]) == 64
    assert run.metadata["memory_feedback"]["remembered"] is True


@pytest.mark.parametrize("state", ["running", "queued", "waiting_user", "blocked"])
def test_pending_result_never_becomes_failure_or_success_memory(monkeypatch, remember, state):
    run = verified_run(monkeypatch)
    run.status = state
    RunPlanning(InMemoryAgentRunRepository()).remember_run_outcome_for(run)
    assert not remember
    assert run.events[-1].data["reason"] == "execution_not_terminal"


def test_uncommitted_terminal_result_never_writes_memory(monkeypatch, remember):
    run = verified_run(monkeypatch)
    RunPlanning(InMemoryAgentRunRepository()).remember_run_outcome_for(run)
    assert not remember
    assert run.events[-1].data["reason"] == "terminal_receipt_not_committed"


def test_uncommitted_verification_observation_never_writes_memory(monkeypatch, remember):
    run = verified_run(monkeypatch)
    repository = InMemoryAgentRunRepository()
    repository.save(run)
    assert verify_step_result(
        run=run,
        step=run.steps[0],
        call=run.tool_calls[0],
        context=run.metadata["runtime_context"],
    )["accepted"]
    RunPlanning(repository).remember_run_outcome_for(run)
    assert not remember
    assert run.events[-1].data["reason"] == "terminal_receipt_not_committed"


def test_changed_verification_evidence_cannot_teach_success(monkeypatch, remember):
    run = verified_run(monkeypatch)
    run.tool_calls[0].metadata["verification"]["checks"][0]["evidence"]["row_id"] = 999
    repository = InMemoryAgentRunRepository()
    repository.save(run)
    RunPlanning(repository).remember_run_outcome_for(run)
    assert not remember
    assert run.events[-1].data["reason"] == "result_not_verified"


def test_failed_run_memory_uses_the_failure_not_an_earlier_success(monkeypatch, remember):
    run = verified_run(monkeypatch)
    run.status, run.error = "failed", "Export failed after customer creation"
    repository = InMemoryAgentRunRepository()
    repository.save(run)
    RunPlanning(repository).remember_run_outcome_for(run)
    assert remember[0]["success"] is False
    assert remember[0]["summary"] == "Export failed after customer creation"
    assert remember[0]["metadata"]["status"] == "failed"


def test_receipt_projection_preserves_identity_and_negative_verification(monkeypatch):
    run = verified_run(monkeypatch)
    run.metadata["verification"] = {"status": "inconclusive", "accepted": False}
    result = agent_node_output(run, run.steps[0].node_id)
    assert result["success"] is False
    assert result["task_id"] == "task-original"
    assert result["run_id"] == run.run_id
    assert result["turn_id"] == "turn-original"
    result["verification"]["status"] = "forged"
    assert run.metadata["verification"]["status"] == "inconclusive"


def test_missing_node_receipt_cannot_be_invented_from_completed_status(monkeypatch):
    run = verified_run(monkeypatch)
    result = agent_node_output(run, "missing")
    assert result["success"] is False
    assert result["error_code"] == "execution_receipt_missing"


def test_verification_binds_original_credential_and_rechecks_revocation(monkeypatch):
    run, step, call, context = _receipt(read_only=True)
    credential = {"kind": "aiopen", "credential_id": "original", "scopes": ["*"]}
    context["_credential_authorization"] = credential
    run.metadata["runtime_context"] = copy.deepcopy(context)
    spec = ToolActionSpecV2(tool_id=step.tool_id, action=step.action, read_only=True)
    freeze_verification_contract(run, step, call, spec, context)
    monkeypatch.setattr(
        "app.application.aiopen.service.api_key_permits_execution", lambda *_: False
    )
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["code"] == "verification_credential_denied"
    assert result["accepted"] is False
    context["_credential_authorization"] = {**credential, "credential_id": "replacement"}
    result = verify_step_result(run=run, step=step, call=call, context=context)
    assert result["code"] == "verification_binding_invalid"


def test_feedback_retry_keeps_one_original_conversation_receipt(monkeypatch, storage):
    from app.application.agent_runtime.pipeline import remember_run_outcome
    from app.db.models import AIConversation, AIConversationSession

    _, factory, push = storage
    vector_writes = []
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: SimpleNamespace(
            ingest_chunks=lambda owner, chunks: (
                vector_writes.append((owner, chunks)) or {"success": True}
            )
        ),
    )
    metadata = {
        "feedback_id": "original-evidence-digest",
        "run_id": "original-run",
        "task_id": "original-task",
        "status": "completed",
        "verification_status": "verified",
    }
    for _ in range(2):
        assert remember_run_outcome(
            user_id="42",
            task="Create A",
            summary="Created A",
            session_id="original-conversation",
            metadata=metadata,
        )
    with factory() as db:
        rows = db.query(AIConversation).order_by(AIConversation.id).all()
        assert [(row.role, row.content) for row in rows] == [
            ("user", "Create A"),
            ("assistant", "Created A"),
        ]
        assert db.query(AIConversationSession).one().message_count == 2
        assert all(
            json.loads(row.conversation_metadata)["task_id"] == "original-task" for row in rows
        )
    push.assert_called_once()
    assert len(vector_writes) == 2
    assert vector_writes[0][0] == vector_writes[1][0] == "42"
    assert vector_writes[0][1][0].chunk_id == vector_writes[1][1][0].chunk_id
