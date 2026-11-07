"""A07: legitimate false values are data, not missing values."""

from decimal import Decimal

import pytest

from app.application.elt.service_support import apply_validation_rules


@pytest.mark.parametrize("value", [0, False, Decimal("0"), 0.0, "0", "False", "中文"])
def test_false_values_preserve_their_text_length(value):
    size = len(str(value))
    assert (
        apply_validation_rules(
            {"value": value},
            [
                {"field": "value", "op": "min_length", "value": size},
                {"field": "value", "op": "max_length", "value": size},
            ],
        )
        == []
    )
    assert (
        len(
            apply_validation_rules(
                {"value": value}, [{"field": "value", "op": "max_length", "value": size - 1}]
            )
        )
        == 1
    )


@pytest.mark.parametrize("data", [{}, {"value": None}, {"value": ""}])
def test_missing_and_empty_values_keep_empty_length(data):
    assert apply_validation_rules(data, [{"field": "value", "op": "max_length", "value": 0}]) == []
    assert (
        len(apply_validation_rules(data, [{"field": "value", "op": "min_length", "value": 1}])) == 1
    )


@pytest.mark.parametrize("value", [0, False, Decimal("0"), 0.0, "0", "False", "中文", None, ""])
def test_mapping_split_concat_and_validation_share_value_fidelity(value):
    from app.application.elt.transforms import apply_mapping

    output = apply_mapping(
        {"raw": value},
        [
            {"source": "raw", "target": "split", "transforms": [{"op": "split"}]},
            {
                "source": "raw",
                "target": "joined",
                "transforms": [
                    {"op": "concat", "fields": ["raw", "missing", "split"], "separator": "|"}
                ],
            },
        ],
    )
    text = "" if value is None else str(value)
    assert output == {"split": text, "joined": text + "||" + text}
    assert (
        apply_validation_rules(
            output,
            [
                {"field": "split", "op": "min_length", "value": len(text)},
                {"field": "split", "op": "max_length", "value": len(text)},
            ],
        )
        == []
    )


def test_b33_b42_cleaning_keeps_business_values(tmp_path):
    """B33-B42: blanks stay blank, falsy data stays data, codes/dates/numbers stay exact."""
    from datetime import datetime, time

    from openpyxl import Workbook

    from app.application.elt.parsers import _parse_csv, _parse_workbook
    from app.application.elt.product_identity import model_token
    from app.application.elt.targets.helpers import optional_text
    from app.application.elt.transforms import apply_transform

    book = Workbook()
    sheet = book.active
    sheet.append(["产品名称", "型号", "编码", "价格", "启用"])
    sheet.append(["甲", "SKU/0", 123, 0, False])
    sheet.append(["乙", None, 7, 1.5, True])
    sheet["C2"].number_format = "00000"
    xlsx = tmp_path / "b.xlsx"
    book.save(xlsx)
    rows = list(_parse_workbook(xlsx, 10, "products").rows)
    assert rows[0].values == {"产品名称": "甲", "型号": "SKU/0", "编码": "00123", "价格": 0, "启用": False}
    assert "型号" not in rows[1].values and rows[1].values["编码"] == 7

    csv_path = tmp_path / "b.csv"
    csv_path.write_text("产品名称,型号,价格\n丙,,0\n", encoding="utf-8")
    assert list(_parse_csv(csv_path, 10, "products").rows)[0].values == {
        "产品名称": "丙",
        "型号": "",
        "价格": "0",
    }

    assert (optional_text(None), optional_text(""), optional_text(0)) == (None, "", "0")
    assert model_token(0) == "0"
    assert apply_transform(46301, {"op": "date"}, {}) == "2026-10-06"
    assert apply_transform(datetime(2026, 10, 5, 8, 30), {"op": "datetime"}, {}) == "2026-10-05 08:30:00"
    assert apply_transform("2026/10/05 08:30", {"op": "datetime"}, {}) == "2026-10-05 08:30:00"
    assert apply_transform(time(8, 30), {"op": "time"}, {}) == "08:30:00"
    assert apply_transform("12.5%", {"op": "number"}, {}) == "0.125"
    assert apply_transform(0.1 + 0.2, {"op": "number"}, {}) == "0.3"
    assert apply_transform(None, {"op": "number"}, {}) is None


def test_b42_targets_reject_unauthorized_rounding():
    from app.application.elt.errors import EltError
    from app.application.elt.targets.orders import ShipmentAdapter
    from app.application.elt.targets.products import ProductAdapter
    from app.application.elt.transforms import apply_transform

    base = {"unit": "客户", "name": "漆"}
    assert ProductAdapter().validate({**base, "price": "12.35"}) == []
    assert ProductAdapter().validate({**base, "price": 12.35}) == []
    codes = [i["code"] for i in ProductAdapter().validate({**base, "price": "12.345"})]
    assert codes == ["ELT_NUMBER_PRECISION_EXCEEDED"]
    codes = [i["code"] for i in ProductAdapter().validate({**base, "price": True})]
    assert codes == ["ELT_NUMBER_INVALID"]
    shipment = {"purchase_unit": "客户", "product_name": "漆", "quantity_tins": "2.5"}
    assert [i["field"] for i in ShipmentAdapter().validate(shipment)] == ["quantity_tins"]
    with pytest.raises(EltError):
        apply_transform("2.5", {"op": "cast", "type": "integer"}, {})
