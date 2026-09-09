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


def test_receivable_payable_bare_nouns():
    for message, account in (("应收账款明细", "receivable"), ("应付账款", "payable")):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "finance_aging_report"
        assert route[2][0].params["account_type"] == account


def test_money_question_routes_to_ledger():
    for message in ("这个月收入", "花了多少钱"):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "finance_ledger_query"
        assert route[2][0].tool_id == "finance"


def test_order_status_filter():
    route = domain_query_nodes("未发货的订单", REGISTRY)
    assert route is not None
    node = route[2][0]
    assert node.tool_id == "sales"
    assert node.params["status"] == "confirmed"
    done = domain_query_nodes("已完成的订单", REGISTRY)
    assert done is not None and done[2][0].params["status"] == "delivered"


def test_sales_ranking_routes_to_summary():
    for message in ("销量排行", "卖得最好的产品", "哪个产品卖得最多"):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "sales_ranking"
        assert route[2][0].tool_id == "reports"


def test_period_sales_routes_to_summary():
    for message in ("今天营业额", "昨日销售", "本周销量"):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "sales_report"
        node = route[2][0]
        assert node.params["start_date"] <= node.params["end_date"]


def test_mrp_order_query():
    for message in ("工单列表", "生产计划"):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "mrp_order_query"
        assert route[2][0].tool_id == "mrp"


def test_missing_slot_writes_clarify():
    for message in ("新建客户", "添加供应商", "开发票", "回款登记"):
        route = domain_query_nodes(message, REGISTRY)
        assert route is not None, message
        assert route[0] == "clarify_missing_slots"
        assert route[2][0].tool_id == "clarify"


def test_named_customer_create_not_intercepted():
    assert domain_query_nodes("新增客户 星光贸易", REGISTRY) is None
