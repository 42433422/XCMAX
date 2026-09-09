"""Unit tests for the extended domain query routing (materials/settings/purchase summary)."""

from app.application.workflow.domain_query_planning import domain_query_nodes
from app.application.workflow.inventory_query_planning import low_stock_alert_node
from app.application.workflow.sales_order_query_planning import sales_order_query_node
from app.services.tools_execution.registry import get_workflow_tool_registry

REGISTRY = get_workflow_tool_registry()


def test_materials_list_routes_to_materials():
    route = domain_query_nodes("物料列表", REGISTRY)
    assert route is not None
    intent, _, nodes = route
    assert intent == "materials_query"
    assert nodes[0].tool_id == "materials"
    assert nodes[0].action == "list"


def test_materials_keyword_routes_to_query():
    route = domain_query_nodes("查一下物料 树脂", REGISTRY)
    assert route is not None
    nodes = route[2]
    assert nodes[0].tool_id == "materials"
    assert nodes[0].action == "query"
    assert nodes[0].params["keyword"] == "树脂"


def test_settings_query():
    for message in ("系统设置", "查看公司信息"):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "settings_query"
        assert route[2][0].tool_id == "settings"


def test_purchase_summary_report():
    route = domain_query_nodes("采购汇总", REGISTRY)
    assert route is not None
    assert route[0] == "purchase_summary"
    assert route[2][0].tool_id == "reports"
    assert route[2][0].action == "purchase_summary"


def test_domain_routes_reject_negation():
    assert domain_query_nodes("不要物料列表", REGISTRY) is None
    assert domain_query_nodes("取消系统设置", REGISTRY) is None


def test_low_stock_alert_node():
    node = low_stock_alert_node("哪些产品快没货了")
    assert node is not None
    assert node.tool_id == "inventory"
    assert node.action == "low_stock_alert"
    assert low_stock_alert_node("库存报表") is None


def test_sales_order_query_variants():
    for message in ("本月订单有哪些", "查一下销售单", "销售订单列表", "订单都有哪些"):
        node = sales_order_query_node(message)
        assert node is not None, message
        assert node.tool_id == "sales"
