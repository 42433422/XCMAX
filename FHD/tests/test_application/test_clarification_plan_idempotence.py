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
