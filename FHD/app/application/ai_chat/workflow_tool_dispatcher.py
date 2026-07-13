"""Adapter from workflow engine calls to the registered tool facade."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class AIChatWorkflowToolDispatcher:
    def dispatch(self, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool

            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except RECOVERABLE_ERRORS as err:
            logger.error(
                "workflow 工具调度失败 tool=%s action=%s err=%s",
                tool_id,
                action,
                err,
                exc_info=True,
            )
            return {"success": False, "message": str(err)}

    _dispatch_workflow_tool = dispatch


__all__ = ["AIChatWorkflowToolDispatcher"]
