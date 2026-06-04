"""Excel 导入行提取门面。"""

from __future__ import annotations

from typing import Any


def extract_excel_import_records(
    service: Any,
    excel_analysis: dict[str, Any],
    request_context: dict[str, Any] | None = None,
    *,
    user_message: str = "",
) -> tuple[list[dict[str, Any]], str | None]:
    return service._extract_excel_import_records(
        excel_analysis, request_context, user_message=user_message
    )
