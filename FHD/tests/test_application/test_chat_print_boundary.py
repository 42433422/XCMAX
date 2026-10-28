"""Printing must not outlive a disposable read; approved runs retain actual receipts."""

import asyncio
import threading
from unittest.mock import Mock

import pytest

from app.application import normal_chat_dispatch as dispatch
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_read_slot_never_starts_label_print_even_after_cancel(monkeypatch, cancel):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_route = dispatch._route_with_gate

    def slow_rule(message, fallback):
        started.set()
        try:
            assert release.wait(2)
            return original_route(message, fallback)
        finally:
            finished.set()

    printer = Mock(side_effect=AssertionError("physical print forbidden in read slot"))
    monkeypatch.setattr(dispatch, "_route_with_gate", slow_rule)
    monkeypatch.setattr(dispatch, "_has_pending_workflow", lambda _: False)
    monkeypatch.setattr(dispatch, "build_label_print_response_dict", printer)
    task = asyncio.create_task(dispatch.try_normal_slot_read_payload_async("打印 A001 标签 2 张"))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        release.set()
        if not cancel:
            assert await task is None
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    printer.assert_not_called()


@pytest.mark.parametrize("entry", ["plan", "_fallback_plan"])
@pytest.mark.parametrize(
    "message, available, valid",
    [
        ("打印 A001 标签 2 张", True, True),
        ("打印 A001 标签 100 张", True, True),
        ("打印标签", True, False),
        ("打印 A001 B002 标签", True, False),
        ("打印 A001 标签 0 张", True, False),
        ("打印 A001 标签 101 张", True, False),
        ("打印 A001 标签 -2 张", True, False),
        ("打印 A001 标签 1.5 张", True, False),
        ("打印 A001 标签 2 张", False, False),
    ],
)
def test_label_plan_uses_registered_approval_path_without_model(
    monkeypatch, entry, message, available, valid
):
    from app.application.workflow.workflow_types import validate_plan_graph

    planner = LLMWorkflowPlanner(ai_service=Mock())
    model = Mock(side_effect=AssertionError("model call forbidden"))
    monkeypatch.setattr(planner, "_plan_with_react_multiagent", model)
    monkeypatch.setattr("app.application.llm_intent_gate.llm_route_message", model)
    registry = get_tool_registry() if available else {}
    args = ("synthetic", message, registry)
    plan = getattr(planner, entry)(*args)
    assert validate_plan_graph(plan) is None
    (node,) = plan.nodes
    if valid:
        assert (node.tool_id, node.action, node.risk, node.idempotent) == (
            "print",
            "workflow_label_dispatch",
            "high",
            False,
        )
        assert node.params["model_number"] == "A001"
        assert node.params["quantity"] in (2, 100)
    else:
        assert (node.tool_id, node.action) == ("clarify", "ask")
    model.assert_not_called()


@pytest.mark.parametrize("outcome", ["accepted", "failed", "cancelled"])
def test_print_waits_for_confirmation_and_keeps_success_or_failure_receipt(
    monkeypatch, tmp_path, local_tools, outcome
):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    success = outcome == "accepted"
    receipt = {
        "success": success,
        "message": "synthetic accepted" if success else "synthetic unavailable",
    }
    execute = Mock(return_value=receipt)
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", execute
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.is_llm_repair_enabled", lambda *_: False
    )
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    plan = LLMWorkflowPlanner(ai_service=Mock()).plan(
        "synthetic", "打印 A001 标签 2 张", get_tool_registry()
    )
    waiting = orchestrator.start_run_from_plan(
        user_id="synthetic", message="打印 A001 标签 2 张", plan=plan
    )
    assert waiting.status == "waiting_user"
    assert repo.get(waiting.run_id) is not None
    execute.assert_not_called()
    if outcome == "cancelled":
        assert (
            orchestrator.cancel_run(waiting.run_id, requested_by="synthetic").status == "cancelled"
        )
        assert (
            orchestrator.continue_run(waiting.run_id, approved_by="synthetic").status == "cancelled"
        )
        execute.assert_not_called()
        return
    completed = orchestrator.continue_run(waiting.run_id, approved_by="synthetic")
    assert completed.status == ("completed" if success else "failed")
    assert completed.run_id == waiting.run_id
    assert completed.steps[0].output == receipt
    execute.assert_called_once()
    assert execute.call_args.args[:2] == ("print", "workflow_label_dispatch")
    assert {
        "step.waiting_user",
        "step.approved",
        "tool.completed" if success else "tool.failed",
    } <= {event.event_type for event in completed.events}
