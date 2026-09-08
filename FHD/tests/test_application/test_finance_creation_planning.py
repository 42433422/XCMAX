from unittest.mock import patch

import pytest

from app.application.workflow.finance_creation import direct_finance_create_node
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.types import validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_income_preserves_amount_and_counterparty_without_product_queries():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan(
        "p", "记一笔收入 5000 元，来自星光贸易", get_workflow_tool_registry()
    )
    assert validate_plan_graph(plan) is None
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("finance", "create_transaction")]
    assert plan.nodes[0].params == {
        "transaction_type": "revenue",
        "amount": 5000.0,
        "counterparty_name": "星光贸易",
    }
    assert not plan.nodes[0].idempotent


@pytest.mark.parametrize(
    "text",
    [
        "不要记一笔收入5000元",
        "记一笔收入5000元，之后删除客户",
        "记一笔收入5000元，备注项目款",
        "记一笔收入",
    ],
)
def test_unparsed_details_and_compound_requests_are_not_truncated(text):
    assert direct_finance_create_node(text) is None
