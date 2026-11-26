"""DataFrame schema 快照 + LLM 理解桩。

Phase 3B 从 ``legacy-layer.excel_schema_understanding_service`` 吸收。
"""

from __future__ import annotations

import json
from typing import Any, cast

import pandas as pd
from jsonschema import Draft202012Validator

from app.infrastructure.excel.date_norm import date_like_columns
from app.utils.json_safe import json_safe

MAX_QUERY_PLAN_LENGTH = 12_000
_COLUMN_NAMES = {"type": "array", "maxItems": 64, "uniqueItems": True, "items": {"type": "string"}}
QUERY_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query_expression": {"type": "string", "maxLength": 2048},
        "columns": _COLUMN_NAMES,
        "group_by": _COLUMN_NAMES,
        "metrics": {
            "type": "array",
            "maxItems": 32,
            "items": {
                "type": "object",
                "required": ["column", "op"],
                "additionalProperties": False,
                "properties": {
                    "column": {"type": "string"},
                    "op": {"type": "string", "enum": ["sum", "mean", "count", "min", "max"]},
                },
            },
        },
        "conversions": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "type": "object",
                "required": ["column", "kind"],
                "additionalProperties": False,
                "properties": {
                    "column": {"type": "string"},
                    "kind": {"type": "string", "enum": ["date", "number"]},
                    "default_year": {"type": "integer", "minimum": 1900, "maximum": 2200},
                },
            },
        },
        "sort_by": _COLUMN_NAMES,
        "ascending": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 0, "maximum": 5000},
        "unsupported_reason": {"type": "string", "maxLength": 500},
    },
}


def load_query_plan(value: str) -> dict[str, Any]:
    """Validate the complete model plan again at execution, without evaluating code."""
    if not value or not value.strip():
        raise ValueError("empty query plan")
    if len(value) > MAX_QUERY_PLAN_LENGTH:
        raise ValueError("query plan exceeds maximum length")
    try:
        plan = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("query plan must be JSON, not Python code") from exc
    problem = next(Draft202012Validator(QUERY_PLAN_SCHEMA).iter_errors(plan), None)
    if problem is not None:
        raise ValueError(f"invalid query plan: {problem.message}")
    # JSON Schema treats 1.0 as an integer; pandas/datetime require Python ints.
    if "limit" in plan:
        plan["limit"] = int(plan["limit"])
    for conversion in plan.get("conversions", []):
        if "default_year" in conversion:
            conversion["default_year"] = int(conversion["default_year"])
    return cast(dict[str, Any], plan)


def dataframe_schema_snapshot(df: pd.DataFrame, sample_rows: int = 3) -> dict[str, Any]:
    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": list(df.columns.astype(str)),
        "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        # 日期列会给出 Timestamp/NaT，必须先转成 JSON 安全值，否则下游回执序列化失败。
        "sample_rows": json_safe(
            df.head(sample_rows).replace({float("nan"): None}).to_dict(orient="records")
        ),
    }


class ExcelSchemaUnderstandingService:
    def understand_dataframe(
        self,
        df: pd.DataFrame,
        *,
        file_path: str,
        sheet_name: str | None = None,
    ) -> dict[str, Any]:
        snap = dataframe_schema_snapshot(df)
        dtypes = snap["dtypes"]
        return {
            "success": True,
            "file_path": file_path,
            "sheet_name": sheet_name,
            "snapshot": snap,
            "structure": {
                "row_count": snap["row_count"],
                "column_count": snap["column_count"],
                "columns": [
                    {"name": column, "dtype": dtypes.get(column)} for column in snap["columns"]
                ],
                "numeric_columns": [
                    str(name) for name in df.select_dtypes(include="number").columns
                ],
                "date_like_columns": date_like_columns(df),
            },
        }


__all__ = ["dataframe_schema_snapshot", "ExcelSchemaUnderstandingService"]
