"""Async tool routing, with blocking HTTP operations isolated in workers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from starlette.types import ASGIApp

from .ports import CursorHub, ToolCall
from .runtime import RuntimeState


def call_chat(app: ASGIApp, args: dict[str, Any], api_call: ToolCall) -> dict[str, Any]:
    message = str(args.get("message") or "").strip()
    if not message:
        return {"success": False, "message": "message 不能为空"}
    return api_call(
        app,
        {
            "path": "/api/ai/unified_chat",
            "method": "POST",
            "body": {"message": message, "source": "aiopen"},
        },
    )


class ToolDispatcher:
    def __init__(
        self,
        state: RuntimeState,
        catalog: Callable[[], dict[str, Any]],
        blocking: Mapping[str, ToolCall],
        cursor: Callable[[], CursorHub],
        actions: Callable[[], Mapping[str, str]],
        timeout: Callable[[], float],
    ) -> None:
        self._state = state
        self._catalog = catalog
        self._blocking = blocking
        self._cursor = cursor
        self._actions = actions
        self._timeout = timeout

    async def invoke(self, name: str, args: dict[str, Any] | None, app: ASGIApp) -> dict[str, Any]:
        arguments = args if isinstance(args, dict) else {}
        name = str(name or "").strip()
        if name == "api_catalog":
            return self._catalog()
        operation = self._blocking.get(name)
        if operation is not None:
            # to_thread copies the caller's contextvars. Cancellation releases
            # the async caller but cannot stop an already running HTTP operation.
            return await asyncio.to_thread(operation, app, arguments)
        if name == "ui_sessions":
            return {
                "success": True,
                "remote_control_enabled": self._state.remote_control_enabled,
                "sessions": self._cursor().sessions_info(),
            }
        actions = self._actions()
        if name in actions:
            if not self._state.remote_control_enabled:
                return {
                    "success": False,
                    "message": "远程操控总开关已关闭（AIOPEN 面板可开启）",
                    "code": "REMOTE_CONTROL_DISABLED",
                }
            session_id = str(arguments.get("session_id") or "") or None
            params = {key: value for key, value in arguments.items() if key != "session_id"}
            return await self._cursor().dispatch(
                actions[name], params, session_id=session_id, timeout=self._timeout()
            )
        return {"success": False, "message": f"未知工具：{name}", "code": "UNKNOWN_TOOL"}
