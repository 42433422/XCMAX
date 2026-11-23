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
