"""DataFrame schema 快照 + LLM 理解桩。

Phase 3B 从 ``legacy-layer.excel_schema_understanding_service`` 吸收。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.infrastructure.excel.date_norm import date_like_columns
from app.utils.json_safe import json_safe


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
