"""Plan mode is a host decision: it binds runs, persists per turn and blocks writes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_requested_mode_prefers_execution_and_ignores_plain_continuation():
    from app.domain.task_lifecycle.execution_mode import requested_mode_from_text

    assert requested_mode_from_text("按方案执行") == "execute"
    assert requested_mode_from_text("给我一个预算方案") == "plan"
    assert requested_mode_from_text("先不执行，只评估一下") == "plan"
    assert requested_mode_from_text("继续细化") is None


def test_stored_plan_cannot_be_released_by_request_fields():
    from app.domain.task_lifecycle.execution_mode import ExecutionModeError, tighten

    with pytest.raises(ExecutionModeError):
        tighten("plan", "execute")
    assert tighten("plan", None) == "plan"
    assert tighten("execute", "plan") == "plan"


def test_user_text_may_release_plan_but_forged_context_may_not():
    from app.application.ai_chat.dialogue_memory import apply_turn_execution_mode
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    data = {"execution_mode": "plan"}
    context = {}
    assert apply_turn_execution_mode(data, context, "继续细化") == "plan"
    assert apply_turn_execution_mode(data, context, "直接执行") == "execute"

    data = {"execution_mode": "plan"}
    with pytest.raises(ConversationRevisionError):
        apply_turn_execution_mode(data, {"_runtime_execution_mode": "execute"}, "")


def test_plan_mode_denies_writes_and_allows_read_only():
    from app.domain.task_lifecycle.execution_mode import deny_reason

    def lookup_spec(tool_id, action):
        return SimpleNamespace(read_only=action == "list")

    assert deny_reason("plan", "products", "list", {}, lookup_spec=lookup_spec) == ""
    assert "方案模式" in deny_reason("plan", "products", "create", {}, lookup_spec=lookup_spec)
    assert deny_reason("execute", "products", "create", {}, lookup_spec=lookup_spec) == ""


def test_unknown_tool_stays_blocked_in_plan_mode():
    from app.domain.task_lifecycle.execution_mode import deny_reason

    assert "方案模式" in deny_reason("plan", "unknown_tool", "run", {}, lookup_spec=lambda *_: None)


def test_tool_executor_refuses_plan_mode_before_dispatch():
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    step = AgentStep(node_id="n", tool_id="unknown_tool", action="run")
    result = AgentToolExecutor().execute(
        step, runtime_context={"_runtime_execution_mode": "plan", "tenant_id": "t"}
    )
    assert result["error_code"] == "execution_mode_plan_blocked"
    assert result["execution_status"] == "not_started"
    assert result["retryable"] is False
