"""DataFrame schema 快照 + LLM 理解桩。

Phase 3B 从 ``app.legacy.excel_schema_understanding_service`` 吸收。
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def dataframe_schema_snapshot(df: pd.DataFrame, sample_rows: int = 3) -> dict[str, Any]:
    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": list(df.columns.astype(str)),
        "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        "sample_rows": df.head(sample_rows).replace({float("nan"): None}).to_dict(orient="records"),
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
        return {
            "file_path": file_path,
            "sheet_name": sheet_name,
            "snapshot": snap,
            "llm_understanding": {
                "table_summary": "自动分析摘要",
                "business_domain": "unknown",
                "columns": [{"name": c} for c in snap["columns"]],
            },
        }


__all__ = ["dataframe_schema_snapshot", "ExcelSchemaUnderstandingService"]
