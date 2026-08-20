"""Routing detection and declarative specifications for Excel employees."""

from __future__ import annotations

from typing import Any, Dict

EXCEL_DOC_KEYWORDS = (
    ".xlsx",
    ".xlsm",
    "xlsx",
    "xlsm",
    "excel",
    "电子表格",
    "工作簿",
    "工作表",
    "sheet",
)
EXCEL_READ_ACTION_KEYWORDS = (
    "读取",
    "读出",
    "读入",
    "解析",
    "提取",
    "导入",
    "read",
    "load",
    "表头",
    "单元格",
    "全量",
)
EXCEL_GENERATE_ACTION_KEYWORDS = (
    "生成",
    "写出",
    "导出",
    "写入",
    "转换",
    "write",
    "generate",
    "export",
    "json中介",
    "json 中介",
    "中介是json",
    "转为xlsx",
    "转成xlsx",
    "写xlsx",
    "写 xlsx",
)
EXCEL_GENERATE_EXCLUDE = (
    "仅读取",
    "只读",
    "不要生成",
    "read only",
)

EXCEL_READ_OUTPUT_FIELDS = ("sheets", "headers", "rows", "cells", "meta")
EXCEL_GENERATE_OUTPUT_FIELDS = ("sheets", "columns", "rows", "sheet_count", "meta")


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def _has_excel_signal(brief_lower: str) -> bool:
    if any(keyword in brief_lower for keyword in EXCEL_DOC_KEYWORDS):
        return True
    return "表格" in brief_lower and ("xlsx" in brief_lower or "excel" in brief_lower)


def _is_attendance_transform(brief_lower: str) -> bool:
    return "考勤" in brief_lower and any(
        keyword in brief_lower for keyword in ("规则", "模板", "转换", "考勤表")
    )


def is_excel_generate(brief: str) -> bool:
    """Return whether the brief requests JSON-to-XLSX generation."""
    brief_lower = _brief_lower(brief)
    if (
        any(keyword in brief_lower for keyword in (".csv", "csv文件", "csv 文件"))
        and "csv" in brief_lower
    ):
        return False
    if not _has_excel_signal(brief_lower):
        return False
    if _is_attendance_transform(brief_lower):
        return False
    if any(keyword in brief_lower for keyword in EXCEL_GENERATE_EXCLUDE) and not any(
        keyword in brief_lower for keyword in EXCEL_GENERATE_ACTION_KEYWORDS
    ):
        return False
    return any(keyword in brief_lower for keyword in EXCEL_GENERATE_ACTION_KEYWORDS)


def is_excel_full_read(brief: str) -> bool:
    """Return whether the brief requests complete XLSX/XLSM reading."""
    if is_excel_generate(brief):
        return False
    brief_lower = _brief_lower(brief)
    if (
        any(keyword in brief_lower for keyword in (".csv", "csv文件", "csv 文件"))
        and "csv" in brief_lower
    ):
        return False
    if not _has_excel_signal(brief_lower):
        return False
    if _is_attendance_transform(brief_lower):
        return False
    return any(keyword in brief_lower for keyword in EXCEL_READ_ACTION_KEYWORDS)


def excel_read_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "数据处理 / Excel 全量读取",
        "goal": (brief or "").strip().splitlines()[0][:200]
        or "上传 xlsx 并输出 JSON 中介 workbook.json",
        "input": "用户上传的 .xlsx / .xlsm 文件",
        "output": "outputs/workbook.json（sheets、headers、rows、cells、meta）",
        "output_schema": {
            "fields": list(EXCEL_READ_OUTPUT_FIELDS),
            "json_file": "outputs/workbook.json",
        },
        "constraints": [
            "必须真实解析 xlsx，禁止 LLM 编造单元格",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["excel.full_read", "data.json_export"],
        "suggested_handlers": ["direct_python"],
    }


def excel_generate_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "数据处理 / Excel 生成",
        "goal": (brief or "").strip().splitlines()[0][:200] or "JSON 中介 → 写出 output.xlsx",
        "input": "用户上传的 .json 或 run payload 中的结构化数据",
        "output": "outputs/output.xlsx",
        "output_schema": {
            "fields": list(EXCEL_GENERATE_OUTPUT_FIELDS),
            "xlsx_file": "outputs/output.xlsx",
        },
        "constraints": [
            "必须根据 JSON 的 sheets/columns/rows 真实写出 xlsx",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["data.json_read", "excel.write"],
        "suggested_handlers": ["direct_python"],
    }


def build_excel_read_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".xlsx", ".xlsm"],
        "default_action": "convert",
        "default_output_relpath": "outputs/workbook.json",
        "runtime_kind": "excel_full_read",
        "output_schema": list(EXCEL_READ_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Parse .xlsx/.xlsm with openpyxl; write outputs/workbook.json.",
            "JSON must include sheets[].name, headers, rows, cells (row/col/value/formula), meta.",
            "Never claim success unless workbook.json is actually written.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def build_excel_generate_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".json", ".txt"],
        "default_action": "convert",
        "default_output_relpath": "outputs/output.xlsx",
        "runtime_kind": "excel_generate",
        "output_schema": list(EXCEL_GENERATE_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Read JSON / user_query 纯文本 / .txt; write outputs/output.xlsx via openpyxl.",
            "Support payload.table_json; optional LLM structures plain text to sheets.",
            "Never fabricate rows when inputs/ is empty and payload has no table.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }
