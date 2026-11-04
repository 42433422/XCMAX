from app.application.workflow.sales_quote_plan import sales_quote_node


def test_explicit_quote_keeps_customer_model_and_terms():
    node = sales_quote_node("给星光贸易的产品ABC-1报价，数量2，单价5元", {"sales": {}})
    assert node and node.action == "quote"
    assert node.params == {
        "customer_name": "星光贸易",
        "items": [{"model_number": "ABC-1", "quantity": 2.0, "unit_price": 5.0}],
    }


def test_labeled_order_preserves_fields_and_ignores_total_amount():
    node = sales_quote_node(
        "创建销售订单：客户A，产品B，型号ABC-1，数量2件，单价5元，总金额10元。",
        {"sales": {}},
    )
    assert node and node.action == "create_order"
    assert node.params == {
        "customer_name": "A",
        "items": [
            {"model_number": "ABC-1", "product_name": "B", "quantity": 2.0, "unit_price": 5.0}
        ],
    }


def test_labeled_order_accepts_colon_delimited_fields():
    node = sales_quote_node(
        "请创建销售订单：客户名称：星光贸易，型号：ABC-1，数量：2，单价：5元",
        {"sales": {}},
    )
    assert node and node.params["customer_name"] == "星光贸易"
    assert node.params["items"][0]["model_number"] == "ABC-1"


def test_planner_rejects_overlong_text_before_parsing():
    assert sales_quote_node("创建销售订单：" + "型号ABC-1，" * 700, {"sales": {}}) is None
