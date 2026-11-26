"""Typed input for the existing deterministic template-writing employee.

The plan describes cells and formulas chosen by the caller; it infers no business
rules. Formula text is preserved, never reported as a recalculated value.
"""

from __future__ import annotations

from typing import Any

WORKBOOK_READER = "excel-full-read-employee"
WORKBOOK_WRITER = "excel-template-write-employee"
WORKBOOK_QC = "excel-qc-employee"
WORKBOOK_WRITE_REVIEW = "_workbook_write_review"
WORKBOOK_BANDED_TABLE_STYLE = "TableStyleMedium2"
_TEXT = {"type": "string", "minLength": 1}
_ROW = {"type": "integer", "minimum": 1, "maximum": 1048576}
_REF = {"type": "string", "pattern": "^[A-Za-z]{1,3}[1-9][0-9]*$"}
_COLUMN = {"type": "string", "pattern": "^[A-Za-z]{1,3}$"}
_COLOR = {"type": "string", "pattern": "^[0-9A-Fa-f]{6}$"}
_TARGET = {
    "sheet": _TEXT,
    "ref": _REF,
    "row": _ROW,
    "col": {"type": "integer", "minimum": 1, "maximum": 16384},
    "number_format": {"type": "string"},
}


def _writes(*, formula: bool) -> dict[str, Any]:
    fields = (
        {"formula": {"type": "string", "pattern": "^=", "maxLength": 8192}}
        if formula
        else {
            "value": {"type": ["string", "number", "boolean", "null"]},
            "value_type": {"enum": ["auto", "string", "str", "number", "date", "datetime"]},
        }
    )
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": 10000,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["sheet", "formula" if formula else "value"],
            "anyOf": [{"required": ["ref"]}, {"required": ["row", "col"]}],
            "properties": {**_TARGET, **fields},
        },
    }


def _flat_phase(name: str, /, *, optional: dict | None = None, **fields: dict) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["phase", *fields],
        "properties": {"phase": {"const": name}, **fields, **(optional or {})},
    }


_RANGE = {
    "type": "string",
    "pattern": r"^\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}(:\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})?$",
}
_SHEET_AREA = {"sheet": _TEXT, "range": _RANGE}
_TABLE = _flat_phase(
    "create_table",
    sheet=_TEXT,
    range={**_RANGE, "description": "含标题和数据行；sum_column 另占下一行"},
    name={
        **_TEXT, "maxLength": 255,
        "description": "Excel 表名以字母、下划线或反斜杠开头，其余可用字母、数字、下划线和点",
    },
    optional={
        "sum_column": {**_TEXT, "description": "需要合计行时提供求和列标题"},
        "calculated_column": {**_TEXT, "description": "需要计算列时提供列标题"},
        "calculated_formula": {
            "type": "string", "pattern": "^=.", "maxLength": 8192,
            "description": "计算列公式；没有 calculated_column 时沿用 sum_column",
        },
        "banded_rows": {"type": "boolean", "description": "开启可打印且随表格扩展的隔行底纹"},
    },
)
_TABLE["dependentRequired"] = {"calculated_column": ["calculated_formula"]}
_TABLE["if"] = {"required": ["calculated_formula"]}
_TABLE["then"] = {"anyOf": [{"required": ["calculated_column"]}, {"required": ["sum_column"]}]}
_COMBO_CHART = _flat_phase(
    "create_combo_chart",
    sheet={**_TEXT, "description": "图表所在的新工作表"},
    source_sheet=_TEXT,
    categories=_RANGE,
    bar_values=_RANGE,
    line_values={**_RANGE, "description": "累计占比所在的单列范围（0 到 1 表示 0% 到 100%）"},
    title=_TEXT,
    bar_title=_TEXT,
    line_title=_TEXT,
)
_INSERT_ROWS = _flat_phase(
    "insert_rows",
    sheet=_TEXT,
    row=_ROW,
    count={"type": "integer", "minimum": 1, "maximum": 10000},
)
_MERGE_CELLS = _flat_phase("merge_cells", **_SHEET_AREA)
_SET_ROW_HEIGHT = _flat_phase(
    "set_row_height",
    sheet=_TEXT,
    row=_ROW,
    height={"type": "number", "minimum": 0.25, "maximum": 409},
)
_SET_COLUMN_WIDTH = _flat_phase(
    "set_column_width",
    sheet=_TEXT,
    column=_COLUMN,
    width={"type": "number", "exclusiveMinimum": 0, "maximum": 255},
)
_FREEZE_PANES = _flat_phase("freeze_panes", sheet=_TEXT, ref=_REF)
_STYLE_FIELDS = {
    "number_format": _TEXT,
    "bold": {"type": "boolean"},
    "horizontal": {"enum": ["left", "center", "right"]},
    "vertical": {"enum": ["top", "center", "bottom"]},
    "fill_color": _COLOR,
    "border": {"const": "thin", "description": "区域内每格四边细边框"},
    "font_size": {"type": "number", "minimum": 1, "maximum": 409},
}
_CELL_STYLES = _flat_phase(
    "cell_styles",
    sheet=_TEXT,
    range={**_RANGE, "description": "应用样式的连续区域，如 A1:F1 或 A1:F20"},
    optional=_STYLE_FIELDS,
)
_CELL_STYLES["anyOf"] = [{"required": [field]} for field in _STYLE_FIELDS]
_NUMBER = {"type": "number"}
_INTEGER = {"type": "integer"}
_TOP_PERCENT = _flat_phase(
    "conditional_format",
    **_SHEET_AREA,
    rule={"const": "top_percent"},
    percent={"type": "integer", "minimum": 1, "maximum": 100},
    color=_COLOR,
)
_LESS_THAN = _flat_phase(
    "conditional_format",
    **_SHEET_AREA,
    rule={"const": "less_than"},
    threshold=_NUMBER,
    color=_COLOR,
)
_DUPLICATE_ROWS = _flat_phase(
    "conditional_format",
    **_SHEET_AREA,
    rule={"const": "duplicate_rows"},
    key_column=_COLUMN,
    color=_COLOR,
)
_LIST_VALIDATION = _flat_phase(
    "data_validation",
    **_SHEET_AREA,
    rule={"const": "list"},
    source_sheet=_TEXT,
    source_range=_RANGE,
    name={
        "type": "string",
        "pattern": r"^[A-Za-z_][A-Za-z0-9_]{0,254}$",
    },
    error=_TEXT,
)
_WHOLE_VALIDATION = _flat_phase(
    "data_validation",
    **_SHEET_AREA,
    rule={"const": "whole"},
    minimum=_INTEGER,
    maximum=_INTEGER,
    error=_TEXT,
)
_PRINT_LAYOUT = _flat_phase(
    "print_layout",
    **_SHEET_AREA,
    orientation={"enum": ["portrait", "landscape"]},
    paper={"enum": ["A4", "letter"]},
    margins={"enum": ["normal", "narrow", "wide"]},
    title_first_row=_ROW,
    title_last_row=_ROW,
    fit_width={"type": "integer", "minimum": 1, "maximum": 10},
    footer={**_TEXT, "description": "居中页脚，&P 表示当前页，&N 表示总页数"},
)
WORKBOOK_CONTROL_PHASES = frozenset({"conditional_format", "data_validation", "print_layout"})
WORKBOOK_NATIVE_PHASES = WORKBOOK_CONTROL_PHASES | {"create_table", "create_combo_chart"}
WORKBOOK_STRUCTURAL_PHASES = frozenset(
    {"insert_rows", "merge_cells", "set_row_height", "set_column_width", "freeze_panes"}
)


_NAMES = {"type": "array", "items": _TEXT, "minItems": 1, "maxItems": 1000}
WORKBOOK_WRITE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["template_path", "plan"],
    "properties": {
        "template_path": {
            **_TEXT,
            "description": "当前账号的上传 ID/文件名，或同原任务已核验的工作簿产物 URI",
        },
        "output_name": {
            "type": "string",
            "maxLength": 255,
            "pattern": r'^[^/\\\x00-\x1f\x7f<>:"|?*]+\.[xX][lL][sS][xXmM]$',
            "description": "下载文件名，不含路径，扩展名与模板完全同类",
        },
        "user_request": {"type": "string"},
        "plan": {
            "type": "object",
            "additionalProperties": False,
            "required": ["plan_version", "phases"],
            "properties": {
                "plan_version": {"const": 1},
                "template": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"sheet_names": _NAMES},
                },
                "protected_ranges": {"type": "array", "items": _TEXT, "maxItems": 1000},
                "phases": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {
                        "oneOf": [
                            _flat_phase("clear_ranges", ranges=_NAMES),
                            _flat_phase("cell_writes", writes=_writes(formula=False)),
                            _flat_phase("formula_writes", writes=_writes(formula=True)),
                            _flat_phase("retain_sheets", names=_NAMES),
                            _flat_phase("remove_sheets", names=_NAMES),
                            _TABLE,
                            _COMBO_CHART,
                            _CELL_STYLES,
                            _INSERT_ROWS,
                            _MERGE_CELLS,
                            _SET_ROW_HEIGHT,
                            _SET_COLUMN_WIDTH,
                            _FREEZE_PANES,
                            _TOP_PERCENT,
                            _LESS_THAN,
                            _DUPLICATE_ROWS,
                            _LIST_VALIDATION,
                            _WHOLE_VALIDATION,
                            _PRINT_LAYOUT,
                        ]
                    },
                },
                "expected": {
                    "type": "object",
                    "description": "原 QC 独立比对的计划格数/数值合计；不声明公式已重算",
                },
            },
        },
    },
}
