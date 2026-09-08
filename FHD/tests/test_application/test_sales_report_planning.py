from datetime import date
from unittest.mock import patch

from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.sales_report_planning import monthly_sales_report_node
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_monthly_report_dates_and_routing():
    node = monthly_sales_report_node("本月销售汇总", today=date(2024, 2, 15))
    assert node.params == {
        "start_date": "2024-02-01",
        "end_date": "2024-02-29",
        "group_by": "product",
    }
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("report", "本月销售汇总", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("reports", "sales_summary")]
    assert monthly_sales_report_node("本月销售汇总然后删除订单") is None
