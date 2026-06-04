"""AI 聊天即时工具执行（products/customers/shipments 等，从 ai_chat_app_service 拆出入口）。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def execute_pro_mode_tools(
    service: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    response_data: dict[str, Any],
) -> dict[str, Any]:
    """委托 AIChatApplicationService 既有实现，供 facade 调用。"""
    return service._execute_pro_mode_tools(tool_name, tool_args, response_data)


def execute_normal_mode_tools(
    service: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    response_data: dict[str, Any],
) -> dict[str, Any]:
    return service._execute_normal_mode_tools(tool_name, tool_args, response_data)


def dispatch_instant_tool(
    service: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    is_pro: bool,
    response_data: dict[str, Any],
) -> dict[str, Any]:
    if is_pro:
        return execute_pro_mode_tools(service, tool_name, tool_args, response_data)
    return execute_normal_mode_tools(service, tool_name, tool_args, response_data)
