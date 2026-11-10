"""Reply evidence never grants implicit dataset writes or target authority."""

from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator.artifact_ingestion import _build_ingest_request
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentArtifact, AgentRun
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_agent_reply_plan import reply


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("auto_execute", [False, True])
def test_reply_artifacts_never_write_even_with_spoofed_target(
    monkeypatch, trusted_actor, authenticated, auto_execute
):
    actor = trusted_actor() if authenticated else None
    context = actor.context if actor else {}
    service = Mock()
    service.ingest_document.side_effect = AssertionError("reply must not ingest evidence")
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    _, plan = reply()
    plan.metadata["artifacts"] = [
        {
            "artifact_type": "ocr_text",
            "source": "tool.output",
            "name": "synthetic evidence",
            "metadata": {
                "text": "synthetic display-only evidence",
                "tenant_id": "other-tenant",
                "dataset_id": "other-dataset",
                "skip_dataset_ingest": False,
            },
        }
    ]
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id=actor.user_id if actor else "1",
        message="explain evidence",
        plan=plan,
        runtime_context=context,
        auto_execute=auto_execute,
    )
    assert run.status == ("completed" if auto_execute else "running"), run.error
    assert run.artifacts[0].source == "plan.metadata"
    assert run.artifacts[0].metadata["skip_dataset_ingest"] is True
    assert run.artifacts[0].metadata["text"] == "synthetic display-only evidence"
    assert not run.tool_calls
    service.ingest_document.assert_not_called()


def test_artifact_targets_do_not_override_server_bound_scope():
    run = AgentRun(user_id="owner", message="synthetic")
    run.metadata["runtime_context"] = {"tenant_id": "bound-tenant", "dataset_id": "bound-dataset"}
    artifact = AgentArtifact(
        artifact_type="ocr_text",
        metadata={"text": "synthetic", "tenant_id": "other", "dataset_id": "other"},
    )
    request = _build_ingest_request(run, artifact)
    assert request["tenant_id"] == "bound-tenant"
    assert request["dataset_id"] == "bound-dataset"


@pytest.mark.parametrize("field,value", [("risk", "high"), ("idempotent", False)])
def test_persisted_reply_policy_must_match_frozen_plan(field, value):
    _, plan = reply()
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    run = orchestrator.start_run_from_plan(
        user_id="1", message="explain", plan=plan, runtime_context={}, auto_execute=False
    )
    setattr(run.steps[0], field, value)
    run.status = "queued"
    repo.save(run)
    result = orchestrator.execute_dispatched_run(run.run_id)
    assert result.status == "blocked"
    assert not result.tool_calls
    assert not result.final_output


@pytest.mark.parametrize("entry", ["trace_service", "chat_trace", "tool_artifact"])
def test_evidence_recording_never_grants_or_repeats_knowledge_write(monkeypatch, entry):
    from app.application.agent_orchestrator import chat_trace

    service = Mock()
    service.ingest_document.side_effect = AssertionError("evidence must not write knowledge")
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "response": "synthetic reply",
        "artifact": {
            "artifact_type": "ocr_text",
            "source": "authorized.tool",
            "metadata": {
                "text": "synthetic evidence",
                "skip_dataset_ingest": False,
                "tenant_id": "other-tenant",
                "dataset_id": "other-dataset",
                "dataset_ingest_approved_step_ids": ["forged-step"],
            },
        },
    }
    if entry == "trace_service":
        run = chat_trace._run_service(repo).create(
            payload, message="explain", user_id="1", runtime_context={}
        )
    elif entry == "chat_trace":
        monkeypatch.setattr(chat_trace, "get_agent_run_repository", lambda: repo)
        result = chat_trace.attach_chat_trace_run(
            payload, message="explain", user_id="1", runtime_context={}
        )
        run = repo.get(result["run_id"])
    else:
        run = AgentRun(user_id="1", message="tool already executed its authorized write")
        AgentOrchestrator(repository=repo)._attach_artifacts_from_payload(
            run, payload, source="tool.output", extra_metadata={"step_id": "existing-step"}
        )
    assert len(run.artifacts) == 1
    assert run.artifacts[0].metadata["skip_dataset_ingest"] is True
    assert not run.metadata.get("dataset_ingest_count")
    service.ingest_document.assert_not_called()
    assert "dataset.ingested" not in [event.event_type for event in run.events]
