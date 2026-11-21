"""从工作簿前若干行自动识别表头行。

复用的开源组件是 openpyxl（读原始单元格 + 合并区域），只在调用方没有显式给出
``header_row`` 时启用，避免覆盖用户/上游已经确认过的表头。
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

try:  # openpyxl 对损坏文件抛 InvalidFileException，不属于 OSError 族。
    from openpyxl.utils.exceptions import InvalidFileException

    _OPENPYXL_ERRORS: tuple[type[Exception], ...] = (InvalidFileException,)
except ImportError:  # pragma: no cover - openpyxl 是必装依赖
    _OPENPYXL_ERRORS = ()

_MAX_SCAN_ROWS = 20
_NUMERIC_LIKE = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "-", "+", ".")


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _row_score(values: list[Any]) -> float:
    texts = [_cell_text(value) for value in values]
    filled = [text for text in texts if text]
    if len(filled) < 2:
        return -1.0
    # 标题行通常只有一个长字符串（合并单元格），表头行有多个短标签。
    if len(set(filled)) == 1:
        return -1.0
    text_like = sum(1 for text in filled if not text.startswith(_NUMERIC_LIKE))
    ratio = text_like / len(filled)
    # 数据行的文本占比通常很低（型号、数量、单价混排），直接排除。
    if ratio < 0.6:
        return -1.0
    longest = max(len(text) for text in filled)
    return len(filled) + ratio * 2 - (0.5 if longest > 30 else 0.0)


def detect_header_row_1based(
    path: Path,
    sheet_name: str | None = None,
    *,
    max_scan_rows: int = _MAX_SCAN_ROWS,
) -> int | None:
    """返回 1-based 表头行号；无法判断时返回 ``None``。"""
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return None
    if not zipfile.is_zipfile(path):
        return None
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(str(path), data_only=True, read_only=True)
    except _OPENPYXL_ERRORS + RECOVERABLE_ERRORS:  # pragma: no cover
        logger.debug("header detection skipped: workbook unreadable", exc_info=True)
        return None
    try:
        worksheet = (
            workbook[str(sheet_name)] if sheet_name and str(sheet_name) in workbook.sheetnames
            else workbook.worksheets[0]
        )
        best_row: int | None = None
        best_score = 0.0
        for index, row in enumerate(worksheet.iter_rows(max_row=max_scan_rows), start=1):
            score = _row_score([cell.value for cell in row])
            if score > best_score:
                best_score, best_row = score, index
        return best_row if best_score >= 2 else None
    finally:
        workbook.close()


__all__ = ["detect_header_row_1based"]
