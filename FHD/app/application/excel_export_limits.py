"""Resource guards shared by authenticated and legacy table exports."""

from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import chain
from pathlib import Path
from typing import Any

# Match table readback, reviewed-workbook extent and ELT cell-text budgets.
MAX_EXPORT_ROWS = 50_000
MAX_EXPORT_COLUMNS = 200
MAX_EXPORT_CELLS = 100_000
MAX_EXPORT_CELL_CHARS = 32_767
# A tool-specific input budget, independent of HTTP/upload configuration.
MAX_EXPORT_INPUT_BYTES = 16 * 1024 * 1024
# Match the original-file verifier's artifact budget.
MAX_EXPORT_FILE_BYTES = 32 * 1024 * 1024


class ExcelExportLimitError(ValueError):
    def result(self) -> dict[str, Any]:
        return {
            "success": False,
            "error_code": "excel_export_limit_exceeded",
            "message": str(self),
        }


def _json_size(value: Any, limit: int, depth: int = 0) -> int:
    """Count compact UTF-8 JSON without allocating the complete encoded input."""
    if limit < 0 or depth > 64:
        raise ExcelExportLimitError("导出数据超过序列化内容或嵌套深度预算")
    if isinstance(value, str):
        if len(value) > limit:
            raise ExcelExportLimitError("导出数据超过序列化内容预算")
        size = 2
        # JSONEncoder.iterencode still allocates a complete escaped string scalar.
        for start in range(0, len(value), 8192):
            part = json.dumps(value[start : start + 8192], ensure_ascii=False)
            size += len(part.encode("utf-8")) - 2
            if size > limit:
                raise ExcelExportLimitError("导出数据超过序列化内容预算")
    elif isinstance(value, (dict, list)):
        size = 2 + max(0, len(value) - 1)
        children: Iterator[Any]
        if isinstance(value, dict):
            size += len(value)
            if size > limit:
                raise ExcelExportLimitError("导出数据超过序列化内容预算")
            if any(not isinstance(key, str) for key in value):
                raise TypeError("导出字段名必须是文本")
            children = chain.from_iterable(value.items())
        else:
            children = iter(value)
        if size > limit:
            raise ExcelExportLimitError("导出数据超过序列化内容预算")
        for child in children:
            size += _json_size(child, limit - size, depth + 1)
    else:
        if value is not None and not isinstance(value, (bool, int, float)):
            raise TypeError("导出值必须是 JSON 数据")
        size = len(json.dumps(value))
    if size > limit:
        raise ExcelExportLimitError("导出数据超过序列化内容预算")
    return size


def export_input_error(args: dict[str, Any]) -> dict[str, Any] | None:
    rows = args.get("rows")
    if not isinstance(rows, list) or not rows:
        return {
            "success": False,
            "error_code": "empty_business_result",
            "message": "没有可写入的行",
        }
    file_path = args.get("file_path")
    if not isinstance(file_path, str) or Path(file_path.strip()).suffix.lower() not in {
        ".csv",
        ".xlsx",
    }:
        return {
            "success": False,
            "error_code": "invalid_excel_path",
            "message": "导出文件名必须以 .csv 或 .xlsx 结尾",
        }
    try:
        if len(rows) > MAX_EXPORT_ROWS:
            raise ExcelExportLimitError(f"导出行数超过 {MAX_EXPORT_ROWS}，请拆分导出")
        columns: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                return {
                    "success": False,
                    "error_code": "empty_business_result",
                    "message": "没有可写入的行",
                }
            if len(row) > MAX_EXPORT_COLUMNS:
                raise ExcelExportLimitError(f"导出列数超过 {MAX_EXPORT_COLUMNS}")
            columns.update(row)
            if len(columns) > MAX_EXPORT_COLUMNS:
                raise ExcelExportLimitError(f"导出列数超过 {MAX_EXPORT_COLUMNS}")
            # DataFrame(rows) expands sparse object rows to the union of all keys;
            # the legacy exporter does not project an optional `columns` argument.
            if len(rows) * len(columns) > MAX_EXPORT_CELLS:
                raise ExcelExportLimitError(f"导出单元格数超过 {MAX_EXPORT_CELLS}，请拆分导出")
        _json_size(args, MAX_EXPORT_INPUT_BYTES)
        for row in rows:
            for value in chain.from_iterable(row.items()):
                # Bound nested JSON before pandas converts list/dict cells to text.
                _json_size(value, MAX_EXPORT_CELL_CHARS * 6)
                if len(str(value)) > MAX_EXPORT_CELL_CHARS:
                    raise ExcelExportLimitError(f"单元格内容超过 {MAX_EXPORT_CELL_CHARS} 字符")
    except ExcelExportLimitError as exc:
        return exc.result()
    except (TypeError, ValueError):
        return {"success": False, "error_code": "invalid_export_data", "message": "导出数据无效"}
    return None
