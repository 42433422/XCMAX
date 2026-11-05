"""Route a workflow action through an explicit handler table and registered fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, Protocol

logger = logging.getLogger(__name__)
ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class RegisteredToolExecutor(Protocol):
    def __call__(self, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]: ...


def get_tool_registry() -> dict[str, Any]:
    """
    返回工作流工具注册表，供 ai_chat_app_service 使用。
    覆盖报价、主数据、出货、模板与微信辅助等能力，与意图层 tool_key 对齐。
    """
    from app.services.tools_execution.registry import get_workflow_tool_registry

    return get_workflow_tool_registry()


def execute_tool(
    tool_name: str,
    params: dict[str, Any],
    *,
    handlers: Mapping[tuple[str, str], ToolHandler],
    registered: RegisteredToolExecutor,
) -> dict[str, Any]:
    """
    执行指定工具（支持 execute_registered_workflow_tool 注入的 _action）。

    与 get_tool_registry 中的工具 id 一致。
    """
    logger.info("execute_tool called: tool_name=%s, params=%s", tool_name, params)
    merged = dict(params or {})
    merged.pop("_runtime_context", None)
    action = str(merged.pop("_action", "") or "").strip().lower()
    if not action:
        action_defaults: dict[str, str] = {
            "price_list": "export",
            "products": "query",
            "customers": "query",
            "shipment_generate": "generate",
            "shipment_records": "query",
            "shipments": "query",
            "materials": "query",
            "print_label": "generate",
            "excel_decompose": "decompose",
            "template_extract": "extract",
            "excel_schema": "analyze",
            "excel_analysis": "analyze",
            "import_excel": "import",
            "employee": "list",
            "business_db": "read",
        }
        action = action_defaults.get(tool_name, "query")
    handler = handlers.get((tool_name, action))
    if handler is not None:
        return handler(merged)
    result = registered(tool_name, action, merged)
    if not result.get("success") and str(result.get("message", "")).startswith("未注册"):
        return {
            "success": False,
            "message": f"未知工具动作: {tool_name}.{action}",
            "error_code": "unknown_tool_action",
        }
    return result
