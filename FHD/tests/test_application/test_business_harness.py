from __future__ import annotations

from unittest.mock import Mock, patch

from app.application.agent_orchestrator.business_harness import (
    BUSINESS_HARNESS_PROTOCOL,
    ensure_business_harness_context,
    ensure_terminal_business_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.business_harness_projection import project_terminal_run_to_conversation
from app.fastapi_routes.domains.misc.helpers import _message_to_dict


def test_context_creates_task_and_turn_without_reusing_conversation_id() -> None:
    context = ensure_business_harness_context(
        {"conversation_id": "conv-1", "session_id": "conv-1"},
        message="新增客户",
    )

    assert context["conversation_id"] == "conv-1"
    assert context["task_id"].startswith("task_")
    assert context["turn_id"].startswith("turn_")
    assert context["task_id"] != context["conversation_id"]
    assert context["business_harness_protocol"] == BUSINESS_HARNESS_PROTOCOL


def test_terminal_result_exposes_bounded_business_facts_and_event_identity() -> None:
    run = AgentRun(user_id="7", message="新增客户", status="completed")
    run.metadata["runtime_context"] = {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "task_id": "task-1",
    }
    apply_task_context(run, run.metadata["runtime_context"])
    step = AgentStep(node_id="write", tool_id="business_db", action="write")
    step.output = {"success": True, "message": "客户创建成功", "customer_id": 23}
    step.status = "completed"
    run.steps = [step]
    run.tool_calls = [
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            status="completed",
        )
    ]
    event = run.add_event("run.completed", "完成")

    result = ensure_terminal_business_result(run)

    assert event.data["harness"]["task_id"] == "task-1"
    assert event.data["harness"]["turn_id"] == "turn-1"
    assert result["summary"] == "客户创建成功"
    assert result["facts"]["customer_id"] == 23
    assert result["evidence"]["completed_tool_count"] == 1
    assert result["projection_key"].endswith(f":{run.run_id}:completed")


def test_approval_result_projection_is_idempotency_keyed_and_readable() -> None:
    run = AgentRun(user_id="7", message="新增客户", status="completed")
    run.metadata["runtime_context"] = {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "task_id": "task-1",
    }
    apply_task_context(run, run.metadata["runtime_context"])
    run.final_output = {
        "node_outputs": {"write": {"success": True, "message": "客户创建成功", "customer_id": 23}}
    }
    conversation = Mock()
    conversation.save_message.return_value = 91
    orchestrator = Mock()
    orchestrator.get_run.return_value = run

    with (
        patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator),
        patch("app.services.get_conversation_service", return_value=conversation),
    ):
        message_id = project_terminal_run_to_conversation(
            run.run_id,
            approval_request_id="APR-1",
        )

    assert message_id == 91
    call = conversation.save_message.call_args
    assert call.kwargs["session_id"] == "conv-1"
    assert call.kwargs["intent"] == "business_harness_result"
    assert call.kwargs["idempotency_key"].endswith(f":{run.run_id}:completed")
    assert "客户 ID：23" in call.kwargs["content"]
    assert "审批单：APR-1" in call.kwargs["content"]


def test_conversation_message_envelope_restores_whitelisted_harness_ui() -> None:
    row = _message_to_dict(
        (
            9,
            "conv-1",
            "7",
            "assistant",
            "业务任务已完成",
            "business_harness_result",
            '{"business_harness":{"run_id":"run-1"},"ui":{"businessResult":{"status":"completed"}}}',
            None,
        )
    )

    assert row["business_harness"] == {"run_id": "run-1"}
    assert row["ui_payload"] == {"businessResult": {"status": "completed"}}
