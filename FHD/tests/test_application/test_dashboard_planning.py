from unittest.mock import patch

from app.application.workflow.dashboard_planning import dashboard_query_node
from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_explicit_dashboard_routes_without_business_writes():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("dashboard", "看下运营看板", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("reports", "dashboard")]
    assert plan.nodes[0].risk == "low" and plan.nodes[0].idempotent
    for text in ("不要打开运营看板", "打开运营看板然后删除客户", "修改经营看板"):
        assert dashboard_query_node(text) is None


def test_dashboard_alias_phrasings():
    assert dashboard_query_node("仪表盘数据") is not None
    assert dashboard_query_node("看下仪表盘") is not None
