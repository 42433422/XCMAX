"""Typed input for the existing deterministic template-writing employee.

The plan describes cells and formulas chosen by the caller; it infers no business
rules. Formula text is preserved, never reported as a recalculated value.
"""

from __future__ import annotations

from typing import Any

WORKBOOK_WRITER = "excel-template-write-employee"
WORKBOOK_QC = "excel-qc-employee"
_TEXT = {"type": "string", "minLength": 1}
_TARGET = {
    "sheet": _TEXT,
    "ref": {"type": "string", "pattern": "^[A-Za-z]{1,3}[1-9][0-9]*$"},
    "row": {"type": "integer", "minimum": 1, "maximum": 1048576},
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


def _phase(name: str, field: str, schema: dict) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["phase", field],
        "properties": {"phase": {"const": name}, field: schema},
    }


def _flat_phase(name: str, /, **fields: dict) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["phase", *fields],
        "properties": {"phase": {"const": name}, **fields},
    }


_RANGE = {
    "type": "string",
    "pattern": r"^\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}(:\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})?$",
}
_TABLE = _flat_phase(
    "create_table",
    sheet=_TEXT,
    range={**_RANGE, "description": "含标题和数据行，不含下一行合计"},
    name={
        "type": "string",
        "pattern": r"^[A-Za-z_][A-Za-z0-9_.]{0,254}$",
        "description": "Excel 表名须以字母或下划线开头，只含 ASCII 字母数字下划线（不支持中文）",
    },
    sum_column=_TEXT,
    calculated_formula={"type": "string", "pattern": "^=.", "maxLength": 8192},
)
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
_ROW = {"type": "integer", "minimum": 1, "maximum": 1048576}
_INSERT_ROWS = _flat_phase(
    "insert_rows",
    sheet=_TEXT,
    row=_ROW,
    count={"type": "integer", "minimum": 1, "maximum": 10000},
)
_MERGE_CELLS = _flat_phase("merge_cells", sheet=_TEXT, range=_RANGE)
_SET_ROW_HEIGHT = _flat_phase(
    "set_row_height",
    sheet=_TEXT,
    row=_ROW,
    height={"type": "number", "minimum": 0.25, "maximum": 409},
)
_FREEZE_PANES = _flat_phase(
    "freeze_panes",
    sheet=_TEXT,
    ref={"type": "string", "pattern": "^[A-Za-z]{1,3}[1-9][0-9]*$"},
)
_CELL_STYLES = {
    "type": "object",
    "additionalProperties": False,
    "required": ["phase", "sheet", "range"],
    "anyOf": [
        {"required": ["bold"]},
        {"required": ["horizontal"]},
        {"required": ["vertical"]},
        {"required": ["fill_color"]},
        {"required": ["border"]},
        {"required": ["font_size"]},
    ],
    "properties": {
        "phase": {"const": "cell_styles"},
        "sheet": _TEXT,
        "range": {**_RANGE, "description": "应用样式的连续区域，如 A1:F1 或 A1:F20"},
        "bold": {"type": "boolean"},
        "font_size": {"type": "number", "minimum": 1, "maximum": 409},
        "horizontal": {"enum": ["left", "center", "right"]},
        "vertical": {"enum": ["top", "center", "bottom"]},
        "fill_color": {"type": "string", "pattern": "^[0-9A-Fa-f]{6}$"},
        "border": {"const": "thin", "description": "区域内每格四边细边框"},
    },
}
WORKBOOK_NATIVE_PHASES = frozenset({"create_table", "create_combo_chart"})
WORKBOOK_STRUCTURAL_PHASES = frozenset(
    {"insert_rows", "merge_cells", "set_row_height", "freeze_panes"}
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
                            _phase("clear_ranges", "ranges", _NAMES),
                            _phase("cell_writes", "writes", _writes(formula=False)),
                            _phase("formula_writes", "writes", _writes(formula=True)),
                            _phase("retain_sheets", "names", _NAMES),
                            _phase("remove_sheets", "names", _NAMES),
                            _TABLE,
                            _COMBO_CHART,
                            _CELL_STYLES,
                            _INSERT_ROWS,
                            _MERGE_CELLS,
                            _SET_ROW_HEIGHT,
                            _FREEZE_PANES,
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
