"""shipment_product_parser — 纯领域匹配与 parsed_products 推导。"""

from __future__ import annotations

from app.domain.shipment.shipment_product_parser import match_product, prepare_parsed_products

_DB = [
    {"name": "锡膏 A", "model_number": "XG-100", "specification": 10.0, "price": 88.0},
    {"name": "锡膏 A 大桶", "model_number": "XG-100", "specification": 20.0, "price": 160.0},
    {"name": "助焊剂", "model_number": "ZH-01", "specification": 5.0, "price": 40.0},
]


def test_match_product_model_exact() -> None:
    hit = match_product("", "XG-100", 10.0, _DB)
    assert hit is not None
    assert hit["specification"] == 10.0


def test_match_product_model_disambiguate_by_spec() -> None:
    hit = match_product("", "XG-100", 20.0, _DB)
    assert hit is not None
    assert hit["name"] == "锡膏 A 大桶"


def test_match_product_name_contains() -> None:
    hit = match_product("助焊", "", None, _DB)
    assert hit is not None
    assert hit["model_number"] == "ZH-01"


def test_match_product_prefers_longest_contained_name() -> None:
    catalog = [
        {"name": "MAC验收0929产品", "model_number": "MAC-0929", "price": 3.5},
        {"name": "MAC验收0929产品13687", "model_number": "M13687", "price": 12.5},
    ]
    hit = match_product("MAC验收0929产品13687 数量2", "", None, catalog)
    assert hit is not None
    assert hit["model_number"] == "M13687"


def test_prepare_parsed_products_accepts_ai_shipment_fields() -> None:
    rows = prepare_parsed_products(
        input_products=[{"product_name": "QA-M4-10006", "quantity": 2, "weight_per_unit": 0.2}],
        db_products=[dict(_DB[0], model_number="QA-M4-10006")],
    )
    row = rows[0]
    assert row["model_number"] == "QA-M4-10006"
    assert row["name"] == "锡膏 A"
    assert row["quantity_kg"] == 0.4
    assert row["tin_spec"] == 0.2
    assert row["amount"] == 35.2
