"""模型可调用的附件只读工具。"""

from __future__ import annotations

from typing import Any

from app.application.attachment_artifacts.models import SheetInfo
from app.application.attachment_artifacts.store import ArtifactStore

MAX_SLICE_ROWS = 200
MAX_SEARCH_ROWS = 50
_AGGREGATE_OPS = {"count", "sum", "avg", "min", "max"}


def _not_found() -> dict[str, Any]:
    return {"ok": False, "error": "not_found"}


def _find_sheet(record_sheets: list[SheetInfo], sheet: str) -> SheetInfo | None:
    return next((item for item in record_sheets if item.name == sheet), None)


def list_attachments(store: ArtifactStore) -> dict[str, Any]:
    """列出全部已入库附件。"""
    return {
        "ok": True,
        "attachments": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "sheets": item.get("sheets", 0),
                "row_count": item.get("row_count", 0),
            }
            for item in store.list_all()
        ],
    }


def describe_attachment(store: ArtifactStore, artifact_id: str) -> dict[str, Any]:
    """查看附件的每个 sheet 名称、列名与行数。"""
    record = store.get(artifact_id)
    if record is None:
        return _not_found()
    return {
        "ok": True,
        "id": record.id,
        "name": record.name,
        "sheets": [
            {"name": sheet.name, "columns": sheet.columns, "row_count": sheet.row_count}
            for sheet in record.sheets
        ],
    }


def read_slice(
    store: ArtifactStore,
    artifact_id: str,
    sheet: str,
    start: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """按行窗口读取某个 sheet，limit 上限 200。"""
    record = store.get(artifact_id)
    if record is None:
        return _not_found()
    rows = store.load_rows(artifact_id).get(sheet)
    if rows is None:
        return {
            "ok": False,
            "error": "sheet_not_found",
            "sheets": [item.name for item in record.sheets],
        }
    start = max(int(start), 0)
    limit = max(1, min(int(limit), MAX_SLICE_ROWS))
    window = rows[start : start + limit]
    return {
        "ok": True,
        "sheet": sheet,
        "start": start,
        "rows": window,
        "total_rows": len(rows),
        "truncated": start + len(window) < len(rows),
    }


def search_rows(
    store: ArtifactStore,
    artifact_id: str,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """在单元格文本中做不区分大小写的包含匹配，limit 上限 50。"""
    record = store.get(artifact_id)
    if record is None:
        return _not_found()
    needle = str(query or "").strip().lower()
    if not needle:
        return {"ok": False, "error": "empty_query"}
    limit = max(1, min(int(limit), MAX_SEARCH_ROWS))
    matches: list[dict[str, Any]] = []
    for sheet, rows in store.load_rows(artifact_id).items():
        for row_number, row in enumerate(rows, start=2):  # 表头占第 1 行
            if any(needle in cell.lower() for cell in row):
                matches.append({"sheet": sheet, "row": row_number, "values": row})
                if len(matches) >= limit:
                    return {"ok": True, "query": query, "matches": matches, "truncated": True}
    return {"ok": True, "query": query, "matches": matches, "truncated": False}


def aggregate_rows(
    store: ArtifactStore,
    artifact_id: str,
    sheet: str,
    column: str,
    op: str,
) -> dict[str, Any]:
    """按列做 count/sum/avg/min/max，非数值行计入 skipped_rows。"""
    record = store.get(artifact_id)
    if record is None:
        return _not_found()
    if op not in _AGGREGATE_OPS:
        return {"ok": False, "error": "unsupported_op", "supported": sorted(_AGGREGATE_OPS)}
    info = _find_sheet(record.sheets, sheet)
    if info is None:
        return {
            "ok": False,
            "error": "sheet_not_found",
            "sheets": [item.name for item in record.sheets],
        }
    rows = store.load_rows(artifact_id).get(sheet)
    if rows is None:
        return {"ok": False, "error": "sheet_not_found", "sheets": [info.name]}
    try:
        column_index = info.columns.index(column)
    except ValueError:
        return {"ok": False, "error": "column_not_found", "columns": info.columns}

    values: list[float] = []
    skipped = 0
    for row in rows:
        text = row[column_index].strip() if column_index < len(row) else ""
        try:
            values.append(float(text))
        except ValueError:
            skipped += 1

    if op == "count":
        value: float | None = float(len(values))
    elif op == "sum":
        value = float(sum(values))
    elif op == "avg":
        value = (sum(values) / len(values)) if values else None
    elif op == "min":
        value = min(values) if values else None
    else:
        value = max(values) if values else None
    return {
        "ok": True,
        "sheet": sheet,
        "column": column,
        "op": op,
        "value": value,
        "used_rows": len(values),
        "skipped_rows": skipped,
    }


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_attachments",
        "description": "列出当前会话可用的附件工件（id、文件名、sheet 数、数据行总数）。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "describe_attachment",
        "description": "查看指定附件的每个工作表名称、列名与数据行数。",
        "parameters": {
            "type": "object",
            "properties": {"artifact_id": {"type": "string", "description": "附件工件 id"}},
            "required": ["artifact_id"],
        },
    },
    {
        "name": "read_slice",
        "description": "按行窗口读取某个工作表的数据行，limit 最大 200 行。",
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string", "description": "附件工件 id"},
                "sheet": {"type": "string", "description": "工作表名称"},
                "start": {"type": "integer", "description": "起始数据行下标，默认 0"},
                "limit": {
                    "type": "integer",
                    "description": "返回行数，默认 50，最大 200",
                },
            },
            "required": ["artifact_id", "sheet"],
        },
    },
    {
        "name": "search_rows",
        "description": "在附件所有工作表的单元格文本中做不区分大小写的包含匹配。",
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string", "description": "附件工件 id"},
                "query": {"type": "string", "description": "要查找的文本"},
                "limit": {"type": "integer", "description": "命中上限，默认 20，最大 50"},
            },
            "required": ["artifact_id", "query"],
        },
    },
    {
        "name": "aggregate_rows",
        "description": "按列做数值聚合：count/sum/avg/min/max，非数值行自动跳过。",
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string", "description": "附件工件 id"},
                "sheet": {"type": "string", "description": "工作表名称"},
                "column": {"type": "string", "description": "列名（表头文本）"},
                "op": {
                    "type": "string",
                    "enum": sorted(_AGGREGATE_OPS),
                    "description": "聚合方式",
                },
            },
            "required": ["artifact_id", "sheet", "column", "op"],
        },
    },
]

_HANDLERS = {
    "list_attachments": list_attachments,
    "describe_attachment": describe_attachment,
    "read_slice": read_slice,
    "search_rows": search_rows,
    "aggregate_rows": aggregate_rows,
}


def execute_tool(name: str, args: dict[str, Any], store: ArtifactStore) -> dict[str, Any]:
    """按工具名分发；参数错误与未知工具都以 ok=False 返回。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown_tool"}
    try:
        return handler(store, **(args or {}))
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": "bad_arguments", "message": str(exc)}
