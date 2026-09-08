from app.application.workflow.shipment_plan import shipment_document_node


def test_shipment_plan_preserves_parser_slots():
    node = shipment_document_node(
        "打印 七彩乐园 的发货单，编号9803，规格12，一共3桶", {"shipment_orders": {}}
    )
    assert node.params == {
        "unit_name": "七彩乐园",
        "products": [{"name": "", "model_number": "9803", "quantity_tins": 3, "tin_spec": 12}],
    }


def test_bare_shipment_request_does_not_guess_data_or_parse_with_llm(monkeypatch):
    def unexpected(*_args):
        raise AssertionError("bare request should not call parser")

    monkeypatch.setattr("app.services.tools_execution.order_parser._parse_order_text", unexpected)
    assert shipment_document_node("打个发货单", {"shipment_orders": {}}).params == {}
    assert shipment_document_node("不要打印发货单", {"shipment_orders": {}}) is None
    assert shipment_document_node("查询发货单", {"shipment_orders": {}}) is None
