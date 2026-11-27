from __future__ import annotations

import asyncio
import json
from copy import copy
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from tests.test_mods._excel_runtime import load_module as _load_module

FHD_ROOT = Path(__file__).resolve().parents[2]

READER_CONVERT = (
    FHD_ROOT / "mods/_employees/excel-full-read-employee/backend/vendor/excel_full_read/convert.py"
)
WRITER_CONVERT = (
    FHD_ROOT
    / "mods/_employees/excel-template-write-employee/backend/vendor/excel_template_write/convert.py"
)
WRITER_EMPLOYEE = (
    FHD_ROOT
    / "mods/_employees/excel-template-write-employee/backend/employees/excel_template_write_employee.py"
)


def _sample_template_workbook(path: Path) -> None:
    """通用模板样例：标题合并、[DBNum1] 格式格、右侧 SUMIF 保护列、多 sheet。"""
    wb = Workbook()
    detail = wb.active
    detail.title = "明细"
    detail["A1"] = "考勤明细模板"
    detail.merge_cells("A1:D1")
    detail.append(["姓名", "部门", "出勤", "工时"])  # row 2 表头
    detail["A3"] = "张三"
    detail["B3"] = "生产部"
    detail["A4"] = "李四"
    detail["B4"] = "仓储部"
    detail["D3"] = 9
    detail["D3"].number_format = "[DBNum1][$-804]General"
    # 右侧 F 列为模板预置 SUMIF 小计（保护区）
    detail["F1"] = "小计"
    detail["F3"] = "=SUMIF(A:A,A3,D:D)"
    detail["F4"] = "=SUMIF(A:A,A4,D:D)"

    monthly = wb.create_sheet("月度统计")
    monthly["A1"] = "姓名"
    monthly["B1"] = "出勤合计"
    monthly["A2"] = "张三"
    monthly["A3"] = "李四"

    wb.create_sheet("草稿")
    wb.save(path)
    wb.close()


def _base_plan() -> dict:
    return {
        "plan_version": 1,
        "template": {"sheet_names": ["明细", "月度统计"]},
        "protected_ranges": ["明细!F:F"],
        "phases": [
            {"phase": "clear_ranges", "ranges": ["明细!C3:D4"]},
            {
                "phase": "cell_writes",
                "writes": [
                    {"sheet": "明细", "row": 3, "col": 3, "value": "√"},
                    {
                        "sheet": "明细",
                        "ref": "D3",
                        "value": "8",
                        "value_type": "number",
                        "number_format": "0.0",
                    },
                    {"sheet": "明细", "ref": "C4", "value": "√"},
                    {"sheet": "明细", "ref": "B6", "value": "2026-03-05", "value_type": "date"},
                ],
            },
            {
                "phase": "formula_writes",
                "writes": [
                    {"sheet": "月度统计", "ref": "B2", "formula": "=SUMIF(明细!A:A,A2,明细!D:D)"},
                ],
            },
            {"phase": "retain_sheets", "names": ["明细", "月度统计"]},
        ],
        "expected": {"cells": 4, "note": "for QC"},
    }


@pytest.fixture
def native_workbook(tmp_path):
    from jsonschema import Draft202012Validator

    contract = _load_module(
        "workbook_write_contract_test", FHD_ROOT / "app/domain/workbook_write_contract.py"
    )
    writer = _load_module("excel_native_writer_test", WRITER_CONVERT)
    qc = _load_module(
        "excel_native_qc_test",
        FHD_ROOT / "mods/_employees/excel-qc-employee/backend/vendor/excel_qc/checks.py",
    )
    template, out = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book = Workbook()
    sales = book.active
    sales.title = "销售明细"
    sales.append(["产品", "数量", "单价", "金额"])
    sales.append(["样品甲", 2, 20, "=ROUND(B2*C2,2)"])
    sales.append(["样品乙", 1, 10, "=ROUND(B3*C3,2)"])
    summary = book.create_sheet("产品汇总")
    summary.append(["产品", "金额合计", "累计占比"])
    summary.append(["样品甲", 40, "=B2/SUM(B$2:B$3)"])
    summary.append(["样品乙", 10, "=SUM(B$2:B3)/SUM(B$2:B$3)"])
    book.save(template)
    book.close()

    def run(phases, protected=()):
        plan = {"plan_version": 1, "phases": phases, "protected_ranges": list(protected)}
        payload = {"template_path": "synthetic-upload", "plan": plan}
        Draft202012Validator(contract.WORKBOOK_WRITE_INPUT).validate(payload)
        writer.convert_file(
            None,
            out,
            template_path=template,
            payload={**payload, "strict_protected": True},
            ctx={},
            rule_spec={},
        )
        return out, plan

    return run, template, qc, writer


def _sales_table_phase():
    return {
        "phase": "create_table",
        "sheet": "销售明细",
        "range": "A1:D3",
        "name": "tblSales",
        "sum_column": "金额",
        "calculated_formula": "=ROUND([@数量]*[@单价],2)",
    }


def _sales_header_style_phase():
    return {
        "phase": "cell_styles",
        "sheet": "销售明细",
        "range": "A1:D1",
        "bold": True,
        "horizontal": "center",
        "vertical": "center",
        "fill_color": "FFF2CC",
    }


def _sales_border_phase():
    return {"phase": "cell_styles", "sheet": "销售明细", "range": "A1:D3", "border": "thin"}


def _sales_chart_phase():
    return {
        "phase": "create_combo_chart",
        "sheet": "销售图表",
        "source_sheet": "产品汇总",
        "categories": "A2:A3",
        "bar_values": "B2:B3",
        "line_values": "C2:C3",
        "title": "各产品销售额与累计占比",
        "bar_title": "销售额",
        "line_title": "累计占比",
    }
