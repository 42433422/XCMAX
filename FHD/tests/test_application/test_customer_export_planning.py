from unittest.mock import patch

from app.application.workflow.customer_export_planning import customer_export_nodes
from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_customer_export_phrasings_build_query_then_export():
    for message in ("导出客户报表", "导出客户列表", "帮我导出客户", "请导出一下客户清单"):
        nodes = customer_export_nodes(message)
        assert [(n.tool_id, n.action) for n in nodes] == [
            ("customers", "query"),
            ("reports", "export"),
        ], message
        assert nodes[1].depends_on == [nodes[0].node_id]
        assert nodes[1].params["report_type"] == "customers"


def test_non_export_phrasings_not_claimed():
    for message in (
        "客户列表",
        "导出销售报表",
        "不要导出客户",
        "删除客户",
        "你好",
    ):
        assert customer_export_nodes(message) == [], message


def test_fallback_routes_customer_export_not_products():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", "导出客户报表", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [
        ("customers", "query"),
        ("reports", "export"),
    ]
