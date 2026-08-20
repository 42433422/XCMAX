# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.aiopen.service")


async def invoke_tool(
    name: str, args: dict[str, _facade().Any] | None, app: _facade().Any
) -> dict[str, _facade().Any]:
    """统一工具执行入口（MCP tools/call 与 REST invoke 共用）。"""
    args = args if isinstance(args, dict) else {}
    name = str(name or "").strip()
    if name == "api_catalog":
        return _facade()._tool_api_catalog()
    if name == "api_call":
        return _facade()._tool_api_call(app, args)
    if name == "chat":
        return _facade()._tool_chat(app, args)
    if name == "capability_loop":
        return _facade()._tool_capability_loop(app, args)
    if name == "ui_sessions":
        return {
            "success": True,
            "remote_control_enabled": bool(
                _facade().AIOPEN_STATE.get("remote_control_enabled", False)
            ),
            "sessions": _facade().aiopen_cursor_hub.sessions_info(),
        }
    if name in _facade()._UI_ACTIONS:
        if not _facade().AIOPEN_STATE.get("remote_control_enabled", False):
            return {
                "success": False,
                "message": "远程操控总开关已关闭（AIOPEN 面板可开启）",
                "code": "REMOTE_CONTROL_DISABLED",
            }
        session_id = str(args.get("session_id") or "") or None
        params = {k: v for k, v in args.items() if k != "session_id"}
        return await _facade().aiopen_cursor_hub.dispatch(
            _facade()._UI_ACTIONS[name],
            params,
            session_id=session_id,
            timeout=_facade()._UI_TOOL_TIMEOUT_SECONDS,
        )
    return {"success": False, "message": f"未知工具：{name}", "code": "UNKNOWN_TOOL"}
