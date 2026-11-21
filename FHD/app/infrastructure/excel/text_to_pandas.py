"""Compatibility names for the validated, read-only dataframe query-plan boundary.

The retired Python executor is deliberately unavailable: callers must provide a
JSON plan consumed by the existing filter and aggregation operations.
"""

from __future__ import annotations

import pandas as pd

from app.infrastructure.excel.schema_service import MAX_QUERY_PLAN_LENGTH, load_query_plan

MAX_CODE_LENGTH = MAX_QUERY_PLAN_LENGTH


def _validate_generated_code(code: str) -> str | None:
    try:
        load_query_plan(code)
    except ValueError as exc:
        return str(exc)
    return None


def _safe_exec_pandas(code: str, df: pd.DataFrame) -> pd.DataFrame:
    from app.application.tools.workflow_tools.excel_analysis import execute_query_plan

    return execute_query_plan(code, df)


__all__ = ["_validate_generated_code", "_safe_exec_pandas"]
