from unittest.mock import patch

import pytest

from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.product_creation import direct_product_create_node
from app.application.workflow.types import validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry


@pytest.mark.parametrize(
    "text", ["新增产品 型号A100，单价25.5", "请帮我添加产品，型号：a100，价格：25.5"]
)
def test_labelled_product_creates_no_customer(text):
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", text, get_workflow_tool_registry())
    assert validate_plan_graph(plan) is None
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("products", "create")]
    assert plan.nodes[0].params == {"name_or_model": "A100", "model_number": "A100", "price": 25.5}
    assert not plan.nodes[0].idempotent


@pytest.mark.parametrize(
    "text",
    [
        "不要新增产品 型号A100",
        "帮我新增一个产品",
        "新增产品 型号A100，规格大号",
        "新增产品 名称涂料，型号A100",
        "给客户添加产品 型号A100",
        "新增产品 型号A100，然后删除客户",
    ],
)
def test_incomplete_or_compound_requests_remain_for_planning(text):
    assert direct_product_create_node(text) is None


def test_incomplete_product_request_has_no_customer_write_dependency():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", "帮我新增一个产品", get_workflow_tool_registry())
    assert validate_plan_graph(plan) is None
    assert all(node.tool_id != "customers" for node in plan.nodes)
    products = [node for node in plan.nodes if node.tool_id == "products"]
    assert len(products) == 1 and products[0].action == "create"
    assert any(node.tool_id == "clarify" for node in plan.nodes)
