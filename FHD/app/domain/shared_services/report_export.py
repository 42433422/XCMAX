"""Spreadsheet serialization for report-service results."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import pandas as pd

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def export_report_to_excel(
    report_type: str, data: list[dict[str, Any]], filename: str
) -> dict[str, Any]:
    try:
        frame = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name=report_type)
        output.seek(0)
        return {
            "success": True,
            "file_path": None,
            "data": output.read(),
            "filename": f"{filename}.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    except RECOVERABLE_ERRORS:
        logger.exception("导出Excel失败")
        return {"success": False, "message": "报表导出服务暂时不可用"}


__all__ = ["export_report_to_excel"]
