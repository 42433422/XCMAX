from app.application.sales_quote_inputs import missing_quote_fields
from app.application.workflow.sales_quote_plan import sales_quote_node


def test_english_sell_routes_to_create_order() -> None:
    node = sales_quote_node("SELL 2 P006 TO A006", {"sales": object()})

    assert node is not None
    assert node.action == "create_order"
    assert node.params == {
        "customer_name": "A006",
        "price_source": "catalog",
        "items": [{"model_number": "P006", "quantity": 2.0}],
    }


def test_chinese_quote_pattern_is_unchanged() -> None:
    node = sales_quote_node("给 A006 的产品 P006 报价，数量 2，单价 10", {"sales": object()})

    assert node is not None
    assert node.action == "quote"
    assert node.params["items"] == [{"model_number": "P006", "quantity": 2.0, "unit_price": 10.0}]


def test_catalog_price_model_item_may_omit_price_but_name_item_may_not() -> None:
    assert missing_quote_fields(
        {
            "customer_name": "A006",
            "price_source": "catalog",
            "items": [{"model_number": "P006", "quantity": 2}],
        }
    ) == []
    assert missing_quote_fields(
        {
            "customer_name": "A006",
            "price_source": "catalog",
            "items": [{"product_name": "BOX", "quantity": 2}],
        }
    ) == ["items.0.unit_price"]
    assert missing_quote_fields(
        {"customer_name": "A006", "items": [{"model_number": "P006", "quantity": 2}]}
    ) == ["items.0.unit_price"]
