"""Unit tests for supplier/purchase domain routing planners."""

from app.application.workflow.supplier_purchase_planning import (
    purchase_order_create_nodes,
    purchase_order_query_node,
    supplier_query_node,
)


def test_supplier_list_routes_to_suppliers_query():
    node = supplier_query_node("供应商列表")
    assert node is not None
    assert node.tool_id == "suppliers"
    assert node.action == "query_suppliers"


def test_supplier_variants():
    for message in ("查一下供应商", "看看供应商名单", "供应商都有哪些"):
        node = supplier_query_node(message)
        assert node is not None, message
        assert node.tool_id == "suppliers"


def test_supplier_planner_rejects_unrelated():
    assert supplier_query_node("客户列表") is None
    assert supplier_query_node("产品 A100") is None


def test_purchase_order_query():
    node = purchase_order_query_node("采购订单有哪些")
    assert node is not None
    assert node.tool_id == "purchase"
    assert node.action == "query_orders"


def test_purchase_order_query_variants():
    for message in ("看下采购单", "查询采购订单列表", "采购订单都有哪些"):
        node = purchase_order_query_node(message)
        assert node is not None, message


def test_purchase_order_create_clarifies():
    nodes = purchase_order_create_nodes("开一张采购单")
    assert len(nodes) == 1
    assert nodes[0].tool_id == "clarify"
    assert nodes[0].action == "ask"


def test_purchase_order_create_rejects_negation():
    assert purchase_order_create_nodes("不要开采购单") == []
    assert purchase_order_create_nodes("客户列表") == []
