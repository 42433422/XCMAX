from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.application.etl.parsers import parse_file
from app.application.etl.service import EtlService
from app.application.etl.targets import get_adapter
from app.application.etl.transforms import apply_mapping
from app.application.shipment_excel_etl_ocr import _guess_meta_lines


def _save_workbook(path: Path, build) -> Path:
    workbook = Workbook()
    build(workbook)
    workbook.save(path)
    workbook.close()
    return path


def test_complex_header_skips_preamble_repeated_header_and_footer(tmp_path, monkeypatch):
    path = tmp_path / "complex-customer-products.xlsx"

    def build(workbook):
        sheet = workbook.active
        sheet.title = "业务明细"
        sheet.append(["2026 年客户产品资料导入"])
        sheet.append(["客户信息", None, None, "产品信息", None, None])
        sheet.merge_cells("A2:C2")
        sheet.merge_cells("D2:F2")
        sheet.append(["名称", "电话", "地址", "名称", "型号", "单价"])
        sheet.append([" 甲公司 ", " 13800000000 ", " 上海 ", " 底漆 ", " P-1 ", "￥ 1,200 元"])
        sheet.append(["名称", "电话", "地址", "名称", "型号", "单价"])
        sheet.append(["合计", None, None, None, None, 1200])
        notes = workbook.create_sheet("导入说明")
        notes.append(["请使用标准模板"])
        notes.append(["红色字段为必填"])

    _save_workbook(path, build)
    monkeypatch.setattr(
        "app.application.etl.shipment_compat_parser.parse_delivery_note_with_compat_profile",
        lambda *_args, **_kwargs: None,
    )

    dataset = parse_file(path, target_type="customer_products")

    assert len(dataset.rows) == 1
    assert dataset.rows[0].row_number == 4
    assert "客户信息/名称" in dataset.headers
    assert "产品信息/名称" in dataset.headers
    assert dataset.source_features["sheets"][0]["header_depth"] == 2
    assert dataset.source_features["skipped_sheets"] == [
        {"name": "导入说明", "reason": "no_tabular_header"}
    ]
    warning_codes = {warning["code"] for warning in dataset.warnings}
    assert "ETL_REPEATED_HEADERS_SKIPPED" in warning_codes
    assert "ETL_FOOTER_ROWS_SKIPPED" in warning_codes

    mappings = EtlService()._suggest_mappings(
        dataset,
        get_adapter("customer_products"),
    )
    by_target = {mapping["target"]: mapping for mapping in mappings}
    assert by_target["customer_name"]["source"] == "客户信息/名称"
    assert by_target["name"]["source"] == "产品信息/名称"
    assert by_target["price"]["source"] == "单价"
    assert by_target["customer_name"]["confidence"] >= 0.95


def test_multi_sheet_keeps_business_sheets_and_skips_instructions(tmp_path, monkeypatch):
    path = tmp_path / "regions.xlsx"

    def build(workbook):
        east = workbook.active
        east.title = "华东"
        east.append(["客户名称", "产品名称", "型号"])
        east.append(["甲公司", "底漆", "P-1"])
        south = workbook.create_sheet("华南")
        south.append(["客户名称", "产品名称", "型号"])
        south.append(["乙公司", "面漆", "P-2"])
        notes = workbook.create_sheet("README")
        notes.append(["文件填写说明"])

    _save_workbook(path, build)
    monkeypatch.setattr(
        "app.application.etl.shipment_compat_parser.parse_delivery_note_with_compat_profile",
        lambda *_args, **_kwargs: None,
    )

    dataset = parse_file(path, target_type="customer_products")

    assert [(row.sheet, row.values["客户名称"]) for row in dataset.rows] == [
        ("华东", "甲公司"),
        ("华南", "乙公司"),
    ]
    assert [sheet["name"] for sheet in dataset.source_features["sheets"]] == ["华东", "华南"]
    assert dataset.source_features["skipped_sheets"][0]["name"] == "README"


def test_csv_preamble_and_dirty_values_are_normalized_deterministically(tmp_path):
    path = tmp_path / "dirty.csv"
    path.write_text(
        "客户产品导出\n"
        "导出时间,2026-07-27\n"
        "客户名称,单价,日期\n"
        '\ufeff\u200b 甲\u3000公司 , "￥ 1,234.50 元" ,20260727\n',
        encoding="utf-8",
    )

    dataset = parse_file(path, target_type="customer_products")

    assert dataset.source_features["header_row"] == 3
    assert dataset.rows[0].row_number == 4
    normalized = apply_mapping(
        dataset.rows[0].values,
        [
            {"source": "客户名称", "target": "customer", "transforms": [{"op": "trim"}]},
            {"source": "单价", "target": "price", "transforms": [{"op": "number"}]},
            {"source": "日期", "target": "date", "transforms": [{"op": "date"}]},
        ],
    )
    assert normalized == {
        "customer": "甲 公司",
        "price": "1234.50",
        "date": "2026-07-27",
    }
    assert dataset.rows[0].provenance["original_fragment"]["客户名称"].startswith("\ufeff")


def test_ocr_provenance_uses_cell_coordinates_for_repeated_text(tmp_path, monkeypatch):
    source = tmp_path / "scan.png"
    source.write_bytes(b"placeholder")
    derived = tmp_path / "ocr-derived.xlsx"

    def build(workbook):
        sheet = workbook.active
        sheet.title = "scan_P1"
        sheet.append(["客户名称", "电话"])
        sheet.append(["同名", "同名"])

    _save_workbook(derived, build)
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_ocr.ocr_source_to_workbook",
        lambda *_args, **_kwargs: {
            "success": True,
            "file_path": str(derived),
            "block_count": 4,
            "meta_lines": [],
            "pages": [
                {
                    "sheet_name": "scan_P1",
                    "page_number": 1,
                    "data_start_row": 1,
                    "blocks": [
                        {"text": "同名", "confidence": 0.99, "left": 999},
                    ],
                    "grid_cells": [
                        {
                            "workbook_row": 2,
                            "workbook_column": 1,
                            "text": "同名",
                            "confidence": 0.95,
                            "left": 10,
                        },
                        {
                            "workbook_row": 2,
                            "workbook_column": 2,
                            "text": "同名",
                            "confidence": 0.6,
                            "left": 100,
                        },
                    ],
                }
            ],
        },
    )

    dataset = parse_file(source, target_type="customers")
    provenance = dataset.rows[0].provenance

    assert provenance["cells"]["客户名称"]["confidence"] == 0.95
    assert provenance["cells"]["客户名称"]["position"]["left"] == 10
    assert provenance["cells"]["电话"]["confidence"] == 0.6
    assert provenance["cells"]["电话"]["position"]["left"] == 100
    assert provenance["low_confidence_fields"] == ["电话"]
    assert provenance["requires_confirmation"] is True


def test_ocr_metadata_detection_does_not_remove_business_header():
    grid = [
        ["客户：甲公司", "日期：2026-07-27", ""],
        ["客户名称", "产品名称", "单价"],
        ["甲公司", "底漆", "100"],
    ]

    assert _guess_meta_lines(grid) == ["客户：甲公司 日期：2026-07-27"]
