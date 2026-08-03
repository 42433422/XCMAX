"""Deterministic selection for the built-in office employee function tools.

The model may plan an ERP task, but it must not invent XML or a fake completion
for an explicit document operation.  Once a document format and operation are
unambiguous, select the installed employee's OpenAI function name and let the
normal tool loop execute and audit the call.
"""

from __future__ import annotations

import re
from typing import Any

_FORMATS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ppt", ("ppt", "pptx", "幻灯", "演示文稿", "演示稿")),
    ("pdf", ("pdf", "可移植文档")),
    ("csv", ("csv", "逗号分隔")),
    ("excel", ("excel", "xlsx", "xls", "表格", "工作簿", "报价单", "报表")),
    ("word", ("word", "docx", "文档", "合同", "协议", "函", "通知", "说明书")),
)
_GENERATE_RE = re.compile(r"(生成|创建|制作|起草|写一份|写个|导出)", re.IGNORECASE)
_READ_RE = re.compile(r"(读取|解析|查看|分析|总结|提取|识别|打开)", re.IGNORECASE)


def select_document_employee_tool(
    message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    available_tool_names: set[str] | None = None,
) -> str | None:
    """Return one installed document employee tool for an explicit request.

    Ambiguous chat remains normal chat.  Returning a function name does not
    execute anything by itself; the normal structured tool loop still validates,
    invokes, records, and feeds the result back to the model.
    """
    text = str(message or "").strip().lower()
    if not text:
        return None
    context = runtime_context if isinstance(runtime_context, dict) else {}
    has_attached_excel = bool(context.get("excel_file_path") or context.get("excel_file_paths"))
    action = "generate" if _GENERATE_RE.search(text) else "read" if _READ_RE.search(text) else ""
    if not action and has_attached_excel and "excel" in text:
        action = "read"
    if not action:
        return None

    for format_name, markers in _FORMATS:
        if not any(marker in text for marker in markers):
            continue
        tool_name = f"{format_name}-{'generate' if action == 'generate' else 'full-read'}-employee"
        if available_tool_names is not None and tool_name not in available_tool_names:
            return None
        return tool_name
    return None


def forced_document_tool_choice(
    message: str,
    tools: list[dict[str, Any]],
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build the OpenAI-compatible forced function choice for a document task."""
    available = {
        str((tool.get("function") or {}).get("name") or "").strip()
        for tool in tools
        if isinstance(tool, dict)
    }
    tool_name = select_document_employee_tool(
        message,
        runtime_context=runtime_context,
        available_tool_names=available,
    )
    if not tool_name:
        return None
    return {"type": "function", "function": {"name": tool_name}}


__all__ = ["forced_document_tool_choice", "select_document_employee_tool"]
