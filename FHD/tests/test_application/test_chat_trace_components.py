"""Trace services own only the persistence and side effects explicitly supplied to them."""

from copy import deepcopy
from unittest.mock import Mock

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.trace_approval import resolve_legacy_approval
from app.application.agent_orchestrator.trace_model_usage import ModelUsageRecorder
from app.application.agent_orchestrator.trace_recording import TraceRecorder
from app.application.agent_orchestrator.trace_runs import TraceRunService


def test_observed_results_use_injected_sinks_once_without_replaying_the_write():
    repository = InMemoryAgentRunRepository()
    ledger = Mock(return_value=None)
    ingest = Mock(return_value=None)
    recording = TraceRecorder(ModelUsageRecorder(ledger, Mock()), ingest, Mock(return_value=None))
    execute = Mock(side_effect=AssertionError("observed writes must never be executed again"))
    service = TraceRunService(repository, recording, execute)
    artifact = {"artifact_type": "document", "name": "receipt", "uri": "receipt.txt"}
    payload = {
        "success": True,
        "legacy_tool_records": [
            {
                "tool_id": "sales",
                "action": "create_order",
                "params": {"quantity": 2},
                "output": {"success": True, "data": {"order_id": 4}, "artifacts": [artifact]},
            }
        ],
        "artifacts": [artifact],
        "llm_trace": {"model": "test", "total_tokens": 3, "cost_units": 1},
        "chunks": [{"text": "confirmed source"}],
        "user_memory_rag_summary": "confirmed preference",
    }
    original = deepcopy(payload)

    run = service.create(
        payload, message="创建订单", user_id="untrusted", runtime_context={"local_user_id": "owner"}
    )

    assert run.user_id == "owner" and run.status == "completed"
    assert repository.get(run.run_id) is not None
    assert len(run.tool_calls) == 1 and run.tool_calls[0].output["data"] == {"order_id": 4}
    assert len(run.artifacts) == run.final_output["artifact_count"] == 1
    assert len(run.llm_calls) == len(run.final_output["llm_calls"]) == 1
    assert len(run.retrieval_calls) == len(run.final_output["retrieval_calls"]) == 1
    assert len(run.memory_references) == len(run.final_output["memory_references"]) == 1
    ledger.assert_called_once_with(run, run.llm_calls[0])
    ingest.assert_called_once_with(run, run.artifacts[0])
    execute.assert_not_called()
    assert payload == original


def test_approval_resolution_updates_only_the_injected_repository():
    primary, other = InMemoryAgentRunRepository(), InMemoryAgentRunRepository()
    recording = TraceRecorder(ModelUsageRecorder(Mock(), Mock()), Mock(), Mock(return_value=None))
    service = TraceRunService(primary, recording, Mock())
    context = {"local_user_id": "owner", "tenant_id": "tenant", "session_id": "session"}
    run = service.create(
        {
            "success": True,
            "legacy_tool_records": [
                {
                    "tool_id": "sales",
                    "action": "create_order",
                    "output": {
                        "pending_approval": True,
                        "approval": {"approval_request_ids": ["request"]},
                    },
                }
            ],
        },
        message="创建订单",
        runtime_context=context,
    )
    other.save(deepcopy(run))
    context["agent_run_id"] = run.run_id

    resolved = resolve_legacy_approval("request", context, repository=primary, recording=recording)

    assert resolved == run.run_id
    primary_run, other_run = primary.get(run.run_id), other.get(run.run_id)
    assert isinstance(primary_run, AgentRun) and primary_run.status == "cancelled"
    assert isinstance(other_run, AgentRun) and other_run.status == "waiting_user"
    assert other_run.tool_calls[0].output["pending_approval"] is True
