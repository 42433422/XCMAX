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
    if name in {"api_operations", "api_schema"}:
        from app.application.aiopen.api_contracts import api_operations, api_schema

        return api_operations(app, args) if name == "api_operations" else api_schema(app, args)
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
        identity = {}
        if name in {"ui_files", "ui_set_files"}:
            from app.application.aiopen.software_control import request_screen_owner
            from app.infrastructure.request_context import get_current_request

            identity = request_screen_owner(get_current_request())
            if not identity.get("owner_id") or not identity.get("tenant_id"):
                return {
                    "success": False,
                    "code": "SCREEN_IDENTITY_REQUIRED",
                    "message": "文件操作需要当前账号会话，通用 AIOPEN 令牌不授予文件访问权限",
                }
        return await _facade().aiopen_cursor_hub.dispatch(
            _facade()._UI_ACTIONS[name],
            params,
            session_id=session_id,
            timeout=_facade()._UI_TOOL_TIMEOUT_SECONDS,
            **identity,
        )
    return {"success": False, "message": f"未知工具：{name}", "code": "UNKNOWN_TOOL"}
