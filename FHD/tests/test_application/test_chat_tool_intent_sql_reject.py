"""Deterministic SQL denial and fail-closed model planning contracts."""

from unittest.mock import Mock, patch

from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.sql_execution_policy import rejected_sql_plan


def test_explicit_sql_execution_is_rejected_before_model_planning():
    model = Mock(side_effect=AssertionError("SQL execution requests must stop before the model"))
    with patch("app.application.workflow.planner.get_ai_conversation_service"), patch(
        "app.application.workflow.planner.request_planner_completion", model
    ):
        planner = LLMWorkflowPlanner(completion=model)
        plan = planner.plan("owner", "执行 DELETE FROM customers", {}, {})

    assert plan.nodes == []
    assert plan.metadata["refusal_code"] == "raw_sql_execution_not_supported"
    model.assert_not_called()


def test_unavailable_model_never_synthesizes_a_business_tool_plan():
    with patch("app.application.workflow.planner.get_ai_conversation_service"):
        planner = LLMWorkflowPlanner()
    with patch.object(planner, "_plan_with_llm", return_value=None):
        plan = planner.plan(
            "owner",
            "查一下客户列表",
            {"customers": {"actions": {"query": {"risk": "low", "idempotent": True}}}},
            {},
        )

    assert plan.nodes == []
    assert plan.metadata["planning_rejected"] is True


def test_raw_sql_policy_does_not_misclassify_business_requests():
    assert rejected_sql_plan("查一下客户列表", "plan-1") is None
