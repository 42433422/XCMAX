"""Intake entity counts come from written rows, never from a column title."""

from app.application.elt.intake_entities import count_import_entities


def test_delivery_rows_count_units_products_and_lines_not_a_header():
    counts = count_import_entities(
        [
            ("new", {"customer_name": "产品名称", "product_name": "数量"}),
            ("new", {"purchase_unit": "演示客户乙", "product_name": "演示物料-螺母"}),
            ("update", {"purchase_unit": "演示客户乙", "product_name": "演示物料-弹垫"}),
            ("skip", {"purchase_unit": "演示客户乙", "product_name": "不应计入"}),
            ("error", {"customer_name": "产品名称"}),
        ]
    )
    assert counts == {"customers": 0, "purchase_units": 1, "products": 2, "records": 2}


def test_customer_row_is_both_a_customer_and_a_purchase_unit():
    counts = count_import_entities([("new", {"customer_name": "演示客户乙"})])
    assert counts == {"customers": 1, "purchase_units": 1, "products": 0, "records": 1}


def test_empty_preview_states_zero():
    assert count_import_entities([]) == {
        "customers": 0,
        "purchase_units": 0,
        "products": 0,
        "records": 0,
    }
