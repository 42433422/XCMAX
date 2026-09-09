from unittest.mock import patch

from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_repeated_decoration_keeps_one_question_per_target():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = PlanGraph(
        plan_id="p",
        intent="create_product",
        nodes=[
            WorkflowNode(
                node_id="create", tool_id="products", action="create", params={}, risk="medium"
            )
        ],
    )
    registry = get_workflow_tool_registry()
    planner._apply_clarify_rules(plan, registry)
    original = [n.node_id for n in plan.nodes if n.tool_id == "clarify"]
    assert len(original) == 1
    for _ in range(3):
        planner._decorate_plan(plan, "新增产品", registry)
    assert [n.node_id for n in plan.nodes if n.tool_id == "clarify"] == original
    assert validate_plan_graph(plan) is None


def test_distinct_targets_keep_separate_questions():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = PlanGraph(
        plan_id="p",
        intent="create_products",
        nodes=[
            WorkflowNode(
                node_id=node_id, tool_id="products", action="create", params={}, risk="medium"
            )
            for node_id in ("one", "two")
        ],
    )
    registry = get_workflow_tool_registry()
    planner._apply_clarify_rules(plan, registry)
    planner._apply_clarify_rules(plan, registry)
    assert {n.params["target_node_id"] for n in plan.nodes if n.tool_id == "clarify"} == {
        "one",
        "two",
    }
    assert len([n for n in plan.nodes if n.tool_id == "clarify"]) == 2


def test_chat_gate_reuses_planned_node_and_pauses_without_dispatch():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.application.ai_chat_app_service_aichatapplicationservice_mixin03 import (
        _AIChatApplicationServicePart03Mixin,
    )
    from app.application.workflow.engine import WorkflowEngine

    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    registry = get_workflow_tool_registry()
    plan = planner._fallback_plan("p", "帮我新增一个产品", registry)
    assert not any(n.tool_id == "customers" for n in plan.nodes)
    existing = next(n for n in plan.nodes if n.tool_id == "clarify")
    dispatch = Mock(side_effect=AssertionError("must wait for clarification"))
    service = SimpleNamespace(
        workflow_engine=WorkflowEngine(dispatch),
        workflow_checkpointer=None,
        _pending_workflows={},
        _persist_plan_state=Mock(),
    )
    context = {}
    response = _AIChatApplicationServicePart03Mixin._open_clarification_gate(
        service,
        user_id="u",
        plan=plan,
        tool_registry=registry,
        runtime_context=context,
        thinking_steps="",
        message="新增产品",
    )
    assert response["data"]["action"] == "clarification_required"
    assert len([n for n in plan.nodes if n.tool_id == "clarify"]) == 1
    assert context["_clarify_node_id"] == existing.node_id
    assert service._pending_workflows["u"]["clarify_node_id"] == existing.node_id
    assert existing.params["answer_key"] == "name_or_model"
    dispatch.assert_not_called()
