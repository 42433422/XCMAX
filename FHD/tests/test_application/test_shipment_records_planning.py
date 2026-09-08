"""Unit tests for shipment-records listing routing."""

from app.application.workflow.shipment_records_planning import shipment_records_query_node


def test_today_shipment_records():
    node = shipment_records_query_node("今天的发货记录")
    assert node is not None
    assert node.tool_id == "shipment_records"
    assert node.action == "list"
    assert node.params.get("start_date")
    assert node.params.get("end_date")


def test_bare_records_query():
    node = shipment_records_query_node("看下发货记录")
    assert node is not None
    assert node.params.get("start_date") is None


def test_records_rejects_print_flow():
    assert shipment_records_query_node("打印发货单") is None
    assert shipment_records_query_node("不要删除发货记录") is None
    assert shipment_records_query_node("客户列表") is None
