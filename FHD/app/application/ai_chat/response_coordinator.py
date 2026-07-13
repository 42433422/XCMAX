"""AI chat response and confirmation coordination."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AIChatResponseCoordinator:
    def __init__(
        self,
        *,
        ai_service: Any,
        instant_tools: Any,
        is_pro_source: Callable[[str | None], bool],
    ) -> None:
        self.ai_service = ai_service
        self._instant_tools = instant_tools
        self._is_pro_source = is_pro_source

    def _handle_confirmation_flow(
        self, user_id: str, message: str, file_context: dict[str, Any] | None
    ) -> None:
        """处理确认流程"""
        if not file_context:
            return

        if message not in ("是", "好的", "确认", "yes", "ok", "好"):
            return

        saved_name = file_context.get("saved_name")
        unit_name = file_context.get("unit_name_guess") or file_context.get("unit_name", "")
        suggested_use = file_context.get("suggested_use", "")

        if saved_name and suggested_use == "unit_products_db" and unit_name:
            self.ai_service.set_pending_confirmation(
                user_id,
                {
                    "type": "import_unit_products",
                    "tool_key": "sqlite_import_unit_products",
                    "params": {
                        "saved_name": saved_name,
                        "unit_name": unit_name,
                    },
                    "description": f"导入 {unit_name} 的产品",
                },
            )
            logger.info("用户 %s 确认导入文件：%s -> %s", user_id, saved_name, unit_name)

    def _build_response(
        self, ai_result: dict[str, Any], source: str | None, original_message: str = ""
    ) -> dict[str, Any]:
        """构建响应数据"""
        response_data = {
            "success": True,
            "message": "处理完成",
            "data": {
                "text": ai_result.get("text", ""),
                "action": ai_result.get("action", ""),
                "data": ai_result.get("data", {}) or {},
            },
        }
        response_data["response"] = ai_result.get("text", "")

        action = ai_result.get("action")
        result_data = ai_result.get("data") or {}

        if action == "tool_call" and result_data:
            response_data = self._handle_tool_call(
                response_data, ai_result, result_data, source, original_message
            )
        else:
            if action == "followup":
                response_data["followup"] = result_data
            if action == "auto_action" and result_data:
                response_data["autoAction"] = result_data

        return response_data

    def _handle_tool_call(
        self,
        response_data: dict[str, Any],
        ai_result: dict[str, Any],
        result_data: dict[str, Any],
        source: str | None,
        original_message: str = "",
    ) -> dict[str, Any]:
        """处理工具调用响应"""
        tool_key = result_data.get("tool_key")
        parsed_params = result_data.get("params") or {}
        slots = result_data.get("slots", {})

        if not tool_key:
            response_data["response"] = ai_result.get("text", "")
            response_data["data"]["data"] = result_data.get("data", {}) or {}
            return response_data

        if self._is_pro_source(source):
            response_data = self._instant_tools._execute_pro_mode_tools(
                response_data, tool_key, slots, parsed_params, ai_result, original_message
            )
        else:
            response_data = self._instant_tools._execute_normal_mode_tools(
                response_data, tool_key, parsed_params, ai_result, result_data
            )

        return response_data


__all__ = ["AIChatResponseCoordinator"]
