from unittest.mock import patch

from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.sales_order_query_planning import sales_order_query_node
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_sales_order_list_phrasings_route_to_sales_query():
    for message in ("销售订单列表", "订单清单", "查一下订单", "订单有哪些", "列出销售订单"):
        node = sales_order_query_node(message)
        assert node is not None, message
        assert (node.tool_id, node.action) == ("sales", "query")
        assert node.risk == "low" and node.idempotent


def test_creation_and_compound_phrasings_not_claimed():
    for message in (
        "给客户星光贸易下订单，产品A100，数量10",
        "查一下订单，然后删除客户",
        "不要查询订单",
        "查一下产品 A100",
        "你好",
    ):
        assert sales_order_query_node(message) is None, message


def test_fallback_prefers_sales_query_over_products_catchall():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", "销售订单列表", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("sales", "query")]
