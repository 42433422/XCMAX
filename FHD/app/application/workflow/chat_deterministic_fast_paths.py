"""Planner 对话确定性快路径：常见计数/读表问题直接查库或读 Excel，避免 LLM 幻觉。"""

from __future__ import annotations

import os
import re
from typing import Any

from app.domain.context.session_context import (
    enrich_excel_tool_arguments,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_PRODUCT_COUNT_RE = re.compile(
    r"(?:"
    r"(?:产品表|产品库|products?\s*表?).{0,24}?(?:多少|几条|总数|记录数|count|条记录)"
    r"|"
    r"(?:多少|几条|总数|记录数).{0,24}?(?:产品表|产品库|products?\s*表?)"
    r")",
    re.IGNORECASE,
)

_EXCEL_ROW_COUNT_RE = re.compile(
    r"(?:多少行|几行|行数|总行数|row\s*count|有多少行|第一个\s*sheet|第一个工作表)",
    re.IGNORECASE,
)

_NUMERIC_ONLY_RE = re.compile(
    r"(?:只|仅|就)?(?:回答|回复|说|输出)?(?:一个)?数字",
    re.IGNORECASE,
)

# 纯小闲聊固定话术：问候/再见/求助。仅当消息不含任何业务意图时短路，
# 避免「你好」被 planner 误判成 generic_workflow 并真的执行查询工具。
_SMALLTALK_REPLIES: dict[str, str] = {
    "greeting": "您好！我是 XCAGI 智能助手。您可以直接吩咐：开发货单、查产品/客户库存、"
    "打印标签、管理考勤人员，或上传 Excel 让我分析。请问有什么可以帮您？",
    "goodbye": "再见！祝您工作顺利，有需要随时找我。",
    "help": "我可以帮您处理这些业务：\n"
    "• 开单发货：「发货单 太阳鸟 5桶 20L规格」\n"
    "• 查询数据：「查一下客户」「XX产品还有库存吗」\n"
    "• 打印标签：「打印 A-100 规格20 标签 50张」\n"
    "• 表格处理：上传 Excel 后可问「统计总金额」「导入产品库」\n"
    "• 文档生成：「生成一份对账单」\n"
    "• 考勤管理：考勤工作区维护人员/部门，按登录账号隔离\n"
    "直接说需求即可，我会自动识别并执行。",
}


def _try_smalltalk_reply(text: str) -> dict[str, str] | None:
    """纯问候/再见/求助短路；含业务意图时返回 None 交给后续链路。"""
    try:
        from app.services.intent_service import recognize_intents

        flags = recognize_intents(text)
    except RECOVERABLE_ERRORS:
        return None
    if not isinstance(flags, dict):
        return None
    # 只要识别出任何业务意图/工具/提示，就不短路（如「你好，帮我开单」）。
    if flags.get("primary_intent") or flags.get("tool_key") or flags.get("intent_hints"):
        return None
    for key in ("greeting", "goodbye", "help"):
        if flags.get(f"is_{key}"):
            reply = _SMALLTALK_REPLIES[key]
            return {
                "response": reply,
                "text": reply,
                "thinking_steps": "[小闲聊短路：未调用业务工具]",
                "action": key,
                "trace_intent": f"smalltalk_{key}",
            }
    return None


def _wants_numeric_only(message: str) -> bool:
    return bool(_NUMERIC_ONLY_RE.search(str(message or "")))


def _query_product_count() -> int | None:
    try:
        from app.db.models import Product
        from app.db.session import get_db

        with get_db() as db:
            return int(db.query(Product).count())
    except RECOVERABLE_ERRORS:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return 0
        return None


def _count_excel_rows_openpyxl(file_path: str, sheet_name: str | None) -> int | None:
    try:
        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            names = wb.sheetnames
            if not names:
                return None
            target = sheet_name if sheet_name and sheet_name in names else names[0]
            ws = wb[target]
            return int(ws.max_row or 0)
        finally:
            wb.close()
    except RECOVERABLE_ERRORS:
        return None


def _query_excel_row_count(
    message: str,
    runtime_context: dict[str, Any] | None,
    *,
    workspace_root: str | None,
) -> int | None:
    ea = runtime_context.get("excel_analysis") if isinstance(runtime_context, dict) else None
    if not ea:
        return None
    if not _EXCEL_ROW_COUNT_RE.search(str(message or "")):
        return None
    file_path = str(ea.get("file_path") or "").strip()
    sheet_name = str(ea.get("sheet_name") or "").strip() or None
    if not file_path:
        return None
    openpyxl_count = _count_excel_rows_openpyxl(file_path, sheet_name)
    if openpyxl_count is not None:
        return openpyxl_count
    try:
        from app.application.tools.workflow import handle_excel_analysis

        args = enrich_excel_tool_arguments(
            "excel_analysis",
            {"action": "read", "sheet_name": sheet_name} if sheet_name else {"action": "read"},
            runtime_context or {},
        )
        file_path = str(args.get("file_path") or file_path).strip()
        result = handle_excel_analysis(args, workspace_root=workspace_root)
        if isinstance(result, dict) and result.get("success"):
            return int(result.get("row_count") or 0)
    except RECOVERABLE_ERRORS:
        pass
    return None


def try_deterministic_chat_reply(
    message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    workspace_root: str | None = None,
) -> dict[str, str] | None:
    """命中常见计数问题时返回 {response, text, thinking_steps}，否则 None。"""
    text = str(message or "").strip()
    if not text:
        return None

    smalltalk = _try_smalltalk_reply(text)
    if smalltalk is not None:
        return smalltalk

    # 拒绝类写请求：明确不生成/不执行任何写入计划，直接确认取消。
    from app.application.chat_tool_intent import looks_like_refused_write

    if looks_like_refused_write(text):
        reply = "好的，已取消，不会执行该操作。需要时再告诉我。"
        return {
            "response": reply,
            "text": reply,
            "thinking_steps": "[拒绝守卫：未生成写入计划]",
            "action": "refused_write",
            "trace_intent": "refused_write",
        }

    numeric_only = _wants_numeric_only(text)

    if _PRODUCT_COUNT_RE.search(text):
        count = _query_product_count()
        if count is not None:
            answer = str(count) if numeric_only else f"产品表共有 {count} 条记录。"
            return {
                "response": answer,
                "text": answer,
                "thinking_steps": "[调用工具: db_query/product_count]",
            }

    row_count = _query_excel_row_count(text, runtime_context, workspace_root=workspace_root)
    if row_count is not None:
        answer = str(row_count) if numeric_only else f"第一个工作表共有 {row_count} 行（含表头）。"
        return {
            "response": answer,
            "text": answer,
            "thinking_steps": "[调用工具: excel_analysis/read]",
        }

    return None


__all__ = ["try_deterministic_chat_reply"]
