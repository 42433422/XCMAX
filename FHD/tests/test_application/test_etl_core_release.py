"""Release regression coverage for the deterministic ETL input boundary.

These checks cover the user-visible import behaviour before a draft can write
anything: unsafe spreadsheet values, deterministic transforms, table shape
detection, and CSV/XLSX/document dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from app.application.etl.errors import EtlError
from app.application.etl.parser_structure import (
    TableLayout,
    clean_cell_text,
    detect_table_layout,
    header_match_score,
    header_semantic_keys,
    is_auxiliary_sheet_name,
    is_footer_or_note_row,
    is_repeated_header,
    semantic_key,
)
from app.application.etl.parsers import (
    _aligned_headers_by_sheet,
    _parse_csv,
    _parse_workbook,
    parse_file,
)
from app.application.etl.transforms import (
    apply_mapping,
    apply_transform,
    neutralize_spreadsheet_formula,
)


def _write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "业务明细"
    sheet.append(["客户信息", None, "产品信息", None])
    sheet.append(["客户名称", "客户编号", "产品名称", "数量"])
    sheet.append(["上海客户", "C-01", "净味漆", 12])
    sheet.append(["客户名称", "客户编号", "产品名称", "数量"])
    sheet.append(["合计", None, None, 12])
    notes = workbook.create_sheet("说明")
    notes.append(["这是说明页"])
    workbook.save(path)


def test_transform_dsl_covers_safe_business_value_conversions() -> None:
    source = {"name": "\ufeff  上海\u3000客户  ", "quantity": "(￥1,200.50元)", "flag": "是"}

    assert neutralize_spreadsheet_formula(" =SUM(A1:A2)") == "' =SUM(A1:A2)"
    assert neutralize_spreadsheet_formula("普通文本") == "普通文本"
    assert neutralize_spreadsheet_formula(12) == 12
    assert apply_transform(source["name"], {"op": "trim"}, source) == "上海 客户"
    assert apply_transform(source["quantity"], {"op": "number"}, source) == "-1200.50"
    assert apply_transform(source["quantity"], {"op": "cast", "type": "float"}, source) == -1200.5
    assert apply_transform("12.9", {"op": "cast", "type": "integer"}, source) == 12
    assert apply_transform(source["flag"], {"op": "cast", "type": "boolean"}, source) is True
    assert apply_transform("否", {"op": "cast", "type": "bool"}, source) is False
    assert apply_transform("20250203", {"op": "date"}, source) == "2025-02-03"
    assert (
        apply_transform("03/02/2025", {"op": "date", "formats": ["%d/%m/%Y"]}, source)
        == "2025-02-03"
    )
    assert apply_transform("", {"op": "default", "value": "未提供"}, source) == "未提供"
    assert apply_transform("华东", {"op": "map", "values": {"华东": "east"}}, source) == "east"
    assert (
        apply_transform("未知", {"op": "lookup", "values": {}, "fallback": "other"}, source)
        == "other"
    )
    assert apply_transform("A|B|C", {"op": "split", "delimiter": "|", "index": -1}, source) == "C"
    assert (
        apply_transform(
            "ignored", {"op": "concat", "fields": ["name", "flag"], "separator": " / "}, source
        )
        == "\ufeff  上海\u3000客户   / 是"
    )


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"op": "formula", "operator": "add", "operands": [2, 3]}, "5"),
        ({"op": "formula", "operator": "sub", "operands": [9, 4]}, "5"),
        ({"op": "formula", "operator": "mul", "operands": [2, 4]}, "8"),
        ({"op": "formula", "operator": "div", "operands": [8, 2]}, "4"),
        (
            {
                "op": "formula",
                "operator": "coalesce",
                "operands": [{"field": "absent"}, {"literal": "fallback"}],
            },
            "fallback",
        ),
    ],
)
def test_transform_formula_operations_are_deterministic(
    rule: dict[str, object], expected: str
) -> None:
    assert apply_transform(None, rule, {"absent": ""}) == expected


@pytest.mark.parametrize(
    "value,rule,code",
    [
        ("x", {"op": "unknown"}, "ETL_TRANSFORM_FORBIDDEN"),
        ("x", {"op": "cast", "type": "imaginary"}, "ETL_TRANSFORM_CAST_UNSUPPORTED"),
        ("maybe", {"op": "cast", "type": "bool"}, "ETL_TRANSFORM_BOOLEAN_INVALID"),
        ("bad-date", {"op": "date"}, "ETL_TRANSFORM_DATE_INVALID"),
        ("x", {"op": "map", "values": []}, "ETL_TRANSFORM_MAP_INVALID"),
        ("x", {"op": "concat", "fields": "name"}, "ETL_TRANSFORM_CONCAT_INVALID"),
        (
            "x",
            {"op": "formula", "operator": "pow", "operands": [2, 3]},
            "ETL_FORMULA_OPERATOR_FORBIDDEN",
        ),
        (
            "x",
            {"op": "formula", "operator": "div", "operands": [1, 0]},
            "ETL_FORMULA_DIVISION_BY_ZERO",
        ),
    ],
)
def test_transform_dsl_rejects_unsafe_or_ambiguous_rules(
    value: object, rule: dict[str, object], code: str
) -> None:
    with pytest.raises(EtlError, match=".+") as exc_info:
        apply_transform(value, rule, {})
    assert exc_info.value.code == code


def test_apply_mapping_chains_source_and_normalized_values() -> None:
    mapped = apply_mapping(
        {"客户": "  上海客户 ", "数量": "2"},
        [
            {"source": "客户", "target": "customer_name", "transforms": [{"op": "trim"}]},
            {
                "source": "数量",
                "target": "quantity",
                "transforms": [{"op": "cast", "type": "integer"}],
            },
            {
                "source": "",
                "target": "quantity_with_fee",
                "transforms": [
                    {
                        "op": "formula",
                        "operator": "add",
                        "operands": [{"field": "quantity"}, {"literal": 1}],
                    }
                ],
            },
        ],
    )
    assert mapped == {"customer_name": "上海客户", "quantity": 2, "quantity_with_fee": "3"}

    with pytest.raises(EtlError) as exc_info:
        apply_mapping({"x": "1"}, [{"source": "x", "target": "x", "transforms": "invalid"}])
    assert exc_info.value.code == "ETL_TRANSFORMS_INVALID"


def test_structure_detection_preserves_context_and_business_row_filters() -> None:
    layout = detect_table_layout(
        [
            ["发货信息", None, "产品信息", None],
            ["客户名称", "客户编号", "产品名称", "数量"],
            ["上海客户", "C-01", "净味漆", 12],
        ],
        header_hints=["客户名称", "产品名称", "数量"],
    )
    assert layout is not None
    assert layout.header_start == 0
    assert layout.header_end == 1
    assert "multi_row_header" in layout.reasons
    assert layout.headers == ["客户名称", "客户编号", "产品名称", "数量"]
    assert header_match_score("产品信息/产品名称", ["产品名称"]) == 0.84
    assert header_match_score("订单日期", ["日期"]) == 0.76
    assert header_match_score("", ["客户名称"]) == 0
    assert semantic_key(" 客户-名称 ") == "客户名称"
    assert "产品名称" in header_semantic_keys("产品信息/产品名称")
    assert clean_cell_text("\ufeff A\u00a0 B ") == "A B"
    assert is_repeated_header(["客户名称", "客户编号", "产品名称", "数量"], layout.headers)
    assert is_footer_or_note_row(["合计", "12"])
    assert is_footer_or_note_row(["备注：测试数据"])
    assert not is_footer_or_note_row(["上海客户", "净味漆", 12])
    assert is_auxiliary_sheet_name("封面与说明")
    assert not is_auxiliary_sheet_name("业务明细")
    assert detect_table_layout([[1], [2]], header_hints=["客户名称"]) is None


def test_workbook_parser_skips_auxiliary_repeated_and_footer_rows(tmp_path: Path) -> None:
    source = tmp_path / "业务导入.xlsx"
    _write_workbook(source)

    dataset = _parse_workbook(source, max_rows=20, target_type="customer_products")

    assert dataset.source_features["kind"] == "workbook"
    assert len(dataset.rows) == 1
    assert dataset.rows[0].values["产品名称"] == "净味漆"
    warning_codes = {item["code"] for item in dataset.warnings}
    assert {
        "ETL_AUXILIARY_SHEETS_SKIPPED",
        "ETL_REPEATED_HEADERS_SKIPPED",
        "ETL_FOOTER_ROWS_SKIPPED",
    } <= warning_codes


def test_header_alignment_reuses_the_first_safe_source_alias() -> None:
    layout = TableLayout(0, 0, ["客户名称", "产品名称"], 0.9, 2, ("target_header_match",))

    class Sheet:
        def __init__(self, title: str) -> None:
            self.title = title

    aligned = _aligned_headers_by_sheet(
        [(Sheet("甲"), layout), (Sheet("乙"), layout)], "customer_products"
    )

    assert aligned == {"甲": ["客户名称", "产品名称"], "乙": ["客户名称", "产品名称"]}


def test_csv_parser_handles_encoding_delimiter_repeated_header_and_limit(tmp_path: Path) -> None:
    utf8_csv = tmp_path / "customers.csv"
    utf8_csv.write_text(
        "客户名称;产品名称;数量\n上海客户;净味漆;12\n客户名称;产品名称;数量\n合计;;12\n",
        encoding="utf-8-sig",
    )
    dataset = _parse_csv(utf8_csv, max_rows=10, target_type="customer_products")
    assert dataset.rows[0].values == {"客户名称": "上海客户", "产品名称": "净味漆", "数量": "12"}
    assert {item["code"] for item in dataset.warnings} == {
        "ETL_REPEATED_HEADERS_SKIPPED",
        "ETL_FOOTER_ROWS_SKIPPED",
    }

    gbk_csv = tmp_path / "gbk.csv"
    gbk_csv.write_bytes("客户名称,产品名称\n广州客户,底漆\n".encode("gb18030"))
    assert (
        _parse_csv(gbk_csv, max_rows=10, target_type="customer_products").rows[0].values["产品名称"]
        == "底漆"
    )

    with pytest.raises(EtlError) as exc_info:
        _parse_csv(utf8_csv, max_rows=0, target_type="customer_products")
    assert exc_info.value.code == "ETL_ROW_LIMIT_EXCEEDED"


def test_parse_file_dispatches_safe_document_and_rejects_invalid_uploads(tmp_path: Path) -> None:
    document = tmp_path / "知识.docx"
    document.write_bytes(b"placeholder")
    assert parse_file(document, target_type="knowledge").source_features["knowledge_only"] is True

    with pytest.raises(EtlError) as exc_info:
        parse_file(document, target_type="customers")
    assert exc_info.value.code == "ETL_KNOWLEDGE_ONLY_FILE"
    with pytest.raises(EtlError) as exc_info:
        parse_file(tmp_path / "missing.csv", target_type="customers")
    assert exc_info.value.code == "ETL_UPLOAD_MISSING"

    unknown = tmp_path / "unsupported.txt"
    unknown.write_text("data", encoding="utf-8")
    with pytest.raises(EtlError) as exc_info:
        parse_file(unknown, target_type="customers")
    assert exc_info.value.code == "ETL_FILE_TYPE_UNSUPPORTED"

    csv_source = tmp_path / "customers.csv"
    csv_source.write_text("客户名称,产品名称\nA,B\n", encoding="utf-8")
    with pytest.raises(EtlError) as exc_info:
        parse_file(csv_source, target_type="customer_products", compatibility_preset_id="legacy")
    assert exc_info.value.code == "ETL_COMPATIBILITY_PRESET_FILE_UNSUPPORTED"

    workbook = tmp_path / "customers.xlsx"
    _write_workbook(workbook)
    with pytest.raises(EtlError) as exc_info:
        parse_file(workbook, target_type="knowledge", compatibility_preset_id="legacy")
    assert exc_info.value.code == "ETL_COMPATIBILITY_PRESET_TARGET_MISMATCH"
