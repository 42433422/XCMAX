import pytest

from app.application.workflow.read_query_plan import customer_read_node


@pytest.mark.parametrize(
    "message, keyword",
    [
        ("查一下客户 星光贸易 的信息", "星光贸易"),
        ("查询客户蓝天科技的资料", "蓝天科技"),
        ("客户列表", ""),
        ("查看所有客户清单", ""),
        ("请搜索购买单位“明日商贸”", "明日商贸"),
    ],
)
def test_customer_reads_preserve_entity_and_keyword(message, keyword):
    node = customer_read_node(message, {"intent": "customers_query"}, {"customers": {}})
    assert node and node.tool_id == "customers" and node.action == "query"
    assert node.params == {"keyword": keyword}


@pytest.mark.parametrize(
    "message", ["新增客户甲", "查看客户甲的订单", "给客户甲报价", "查询客户的产品", "不要新建客户"]
)
def test_customer_mentions_do_not_replace_other_business_intents(message):
    assert customer_read_node(message, {"intent": "customers_query"}, {"customers": {}}) is None


@pytest.mark.parametrize("message", ["帮我新增一个产品", "请添加一款产品", "新增产品"])
def test_incomplete_catalog_creation_asks_without_creating_customer(message):
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("missing-product", message, get_workflow_tool_registry())
    assert [(node.tool_id, node.action) for node in plan.nodes] == [
        ("clarify", "ask"),
        ("products", "create"),
    ]
    assert plan.nodes[0].params["clarification"]["missing_fields"] == ["name_or_model"]
    assert plan.nodes[1].params == {}


@pytest.mark.parametrize(
    "message, tool, action",
    [
        ("看下运营看板", "reports", "dashboard"),
        ("本月销售汇总", "reports", "sales_summary"),
        ("查询这个月的账本", "finance", "ledger_query"),
    ],
)
def test_report_and_ledger_reads_use_correct_tool_and_month(message, tool, action):
    from datetime import date

    from app.application.workflow.read_query_plan import report_read_node

    node = report_read_node(message, {tool: {}}, today=date(2024, 2, 15))
    assert node and (node.tool_id, node.action) == (tool, action)
    if action != "dashboard":
        assert node.params["start_date"] == "2024-02-01"
        assert node.params["end_date"].startswith("2024-02-29")


def test_report_export_is_not_downgraded_to_read():
    from app.application.workflow.read_query_plan import report_read_node

    assert report_read_node("导出销售报表", {"reports": {}}) is None


@pytest.mark.parametrize("action", ["dashboard", "inventory_summary"])
def test_snapshot_reports_do_not_request_unsupported_period_or_grouping(action):
    from app.application.workflow.clarification_node import detect_erp_clarification
    from app.application.workflow.types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="snapshot",
        intent="report",
        nodes=[WorkflowNode(node_id="read", tool_id="reports", action=action)],
    )
    assert detect_erp_clarification(plan) == []
