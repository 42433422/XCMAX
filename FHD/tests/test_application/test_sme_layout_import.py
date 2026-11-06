"""Synthetic SME workbook layouts for the desktop import path."""

from __future__ import annotations

import zipfile
from io import BytesIO
from uuid import UUID

import pytest
from openpyxl import Workbook

from app.application.elt.parsers import parse_file
from app.application.elt.target_detection import detect_etl_target


@pytest.fixture(autouse=True)
def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))


def _save(book: Workbook, path) -> None:
    book.save(path)
    book.close()


def test_spaced_delivery_header_and_ledger_lines_are_shipments(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "送货"
    sheet["A1"] = "送 货 单"
    sheet["A2"] = "购 货 单 位"
    sheet["B2"] = "甲厂"
    sheet["A3"] = "产 品 名 称"
    sheet["B3"] = "数 量/KG"
    sheet["C3"] = "单 价"
    sheet["A4"] = "清漆"
    sheet["B4"] = 12
    sheet["C4"] = 3
    sheet["A5"] = "面漆"
    sheet["B5"] = 4
    sheet["C5"] = 8
    ledger = book.create_sheet("出货记录")
    ledger.append(["甲厂", "清漆", 2, 10, 20, 5, 100])
    ledger.append(["甲厂", "面漆", 1, 10, 10, 8, 80])
    ledger.append(["甲厂", "底漆", 3, 5, 15, 6, 90])
    path = tmp_path / "delivery.xlsx"
    _save(book, path)

    detection = detect_etl_target(path)
    assert detection["target_type"] == "shipment_records"
    parsed = parse_file(path, target_type="shipment_records")
    kinds = {row.provenance.get("source_kind") for row in parsed.rows}
    assert "delivery_note_region" in kinds
    assert "shipment_history_line" in kinds
    assert sum(1 for row in parsed.rows if row.values.get("product_name")) >= 4
    parsed.close()


def test_factory_product_columns_write_customer_product_fields(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["日期", "厂名", "品名", "数量", "规格", "单价", "金额"])
    sheet.append(["2026-10-02", "甲厂", "树脂", 3, "25kg", 12, 36])
    sheet.append(["2026-10-03", "乙厂", "固化剂", 2, "20kg", 9, 18])
    path = tmp_path / "material.xlsx"
    _save(book, path)
    assert detect_etl_target(path)["target_type"] == "customer_products"
    parsed = parse_file(path, target_type="customer_products")
    pairs = {(row.values.get("customer_name"), row.values.get("name")) for row in parsed.rows}
    assert ("甲厂", "树脂") in pairs
    assert ("乙厂", "固化剂") in pairs
    parsed.close()


def test_sales_factory_column_and_amount_blocks_write_customers(tmp_path):
    sales = Workbook()
    sheet = sales.active
    sheet.append(["日期", "厂名", "单号", "备注"])
    sheet.append(["2026-10-01", "甲厂", "S-1", "记"])
    sheet.append(["2026-10-02", "乙厂", "S-2", "记"])
    sales_path = tmp_path / "sales.xlsx"
    _save(sales, sales_path)
    assert detect_etl_target(sales_path)["target_type"] == "customers"
    assert detect_etl_target(sales_path)["reason"] == "factory_customer_column"
    parsed = parse_file(sales_path, target_type="customers")
    assert {row.values["customer_name"] for row in parsed.rows} == {"甲厂", "乙厂"}
    parsed.close()

    combined = Workbook()
    grid = combined.active
    grid["A4"] = "甲厂"
    grid["E4"] = "乙厂"
    grid["A5"] = "日期"
    grid["B5"] = "单号"
    grid["C5"] = "销售应收款（元）"
    grid["E5"] = "日期"
    grid["F5"] = "单号"
    grid["G5"] = "销售应收款（元）"
    grid["A6"] = "2026-10-01"
    grid["C6"] = 10
    grid["E6"] = "2026-10-02"
    grid["G6"] = 12
    combined_path = tmp_path / "combined.xlsx"
    _save(combined, combined_path)
    blocks = parse_file(combined_path, target_type="customers")
    assert {row.values["customer_name"] for row in blocks.rows} == {"甲厂", "乙厂"}
    blocks.close()


def test_production_order_writes_material_rows(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "生产打印单"
    sheet["A1"] = "生产单"
    sheet["A3"] = "产品编号"
    sheet["B3"] = "P-100"
    sheet["A4"] = "原材料编号"
    sheet["B4"] = "原料数量（KG）"
    sheet["C4"] = "工艺流程"
    sheet["D4"] = "备注"
    sheet["A5"] = "M-1"
    sheet["B5"] = 12
    sheet["C5"] = "混合"
    sheet["A6"] = "M-2"
    sheet["B6"] = 4
    sheet["C6"] = "过滤"
    path = tmp_path / "production.xlsx"
    _save(book, path)
    assert detect_etl_target(path)["reason"] == "production_order_layout"
    parsed = parse_file(path, target_type="products")
    assert {(row.values["name"], row.values["unit"]) for row in parsed.rows} == {
        ("M-1", "P-100"),
        ("M-2", "P-100"),
    }
    parsed.close()


def test_attendance_calendar_grid_writes_marked_days(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "考勤"
    sheet["A1"] = "2026年10月考勤"
    for column, label in enumerate(("日", "一", "二", "三", "四", "五", "六"), start=2):
        sheet.cell(2, column, label)
        sheet.cell(3, column, column - 1)
    sheet["A4"] = "测试甲"
    sheet["C4"] = "√"
    sheet["E4"] = "08:00"
    path = tmp_path / "attendance.xlsx"
    _save(book, path)
    detection = detect_etl_target(path)
    assert detection["target_type"] == "attendance"
    assert detection["reason"] == "attendance_calendar_grid"
    parsed = parse_file(path, target_type="attendance")
    marked = {(row.values["employee_name"], row.values["work_date"]) for row in parsed.rows}
    assert ("测试甲", "2026-10-02") in marked
    assert ("测试甲", "2026-10-04") in marked
    assert any(row.values.get("clock_in") == "08:00" for row in parsed.rows)
    parsed.close()


def test_statement_docx_lines_are_knowledge_content(tmp_path):
    document = tmp_path / "statement.docx"
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>甲厂对账</w:t></w:r></w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>欠款年月</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>欠款金额/元</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>收款金额/元</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>期末欠款金额/元</w:t></w:r></w:p></w:tc>
          </w:tr>
          <w:tr>
            <w:tc><w:p><w:r><w:t>2026-10</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>3</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
      </w:body>
    </w:document>"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", xml)
    document.write_bytes(buffer.getvalue())
    assert detect_etl_target(document)["target_type"] == "knowledge"
    parsed = parse_file(document, target_type="knowledge")
    content = parsed.rows[0].values["content"]
    assert "欠款金额/元:3" in content
    assert parsed.rows[0].provenance["line_count"] == 1
    assert "document_path" in parsed.rows[0].values
    assert parsed.rows[0].values["document_path"] != content
    parsed.close()


def test_generated_auto_ingest_batch_id_is_a_uuid():
    from uuid import uuid4

    from app.application.elt.auto_ingest_service import _valid_batch_id

    assert _valid_batch_id(str(uuid4()))
    assert not _valid_batch_id("aib-" + "ab" * 8)
    UUID(str(uuid4()))
