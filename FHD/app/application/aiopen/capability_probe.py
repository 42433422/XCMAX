"""Capability-loop verification over explicitly supplied tool operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp

from .protocols import CursorHub, ToolCall
from .runtime import RuntimeState


class CapabilityProbe:
    def __init__(
        self,
        state: RuntimeState,
        catalog: Callable[[], dict[str, Any]],
        select_path: Callable[[list[dict[str, Any]], str], str | None],
        api_call: ToolCall,
        chat: ToolCall,
        cursor: Callable[[], CursorHub],
    ) -> None:
        self._state = state
        self._catalog = catalog
        self._select_path = select_path
        self._api_call = api_call
        self._chat = chat
        self._cursor = cursor

    def run(self, app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
        """catalog → api_call → chat → ui_sessions 闭环自检。"""

        def _step_http_ok(res: dict[str, Any]) -> bool:
            code = res.get("status_code")
            try:
                status = int(code) if code is not None else 599
            except (TypeError, ValueError):
                status = 599
            return bool(res.get("success")) and status < 400

        steps: list[dict[str, Any]] = []
        catalog = self._catalog()
        routes: list[dict[str, Any]] = [
            item for item in catalog.get("routes") or [] if isinstance(item, dict)
        ]
        enabled_count = sum(1 for r in routes or [] if isinstance(r, dict) and r.get("enabled"))
        steps.append(
            {
                "step": "api_catalog",
                "ok": bool(catalog.get("success")),
                "enabled_count": enabled_count,
                "total_count": len(routes or []),
            }
        )
        probe = self._select_path(routes, str(args.get("probe_path") or ""))
        if probe:
            call_res = self._api_call(app, {"path": probe, "method": "GET"})
            steps.append(
                {
                    "step": "api_call",
                    "ok": _step_http_ok(call_res),
                    "path": probe,
                    "status_code": call_res.get("status_code"),
                    "message": call_res.get("message"),
                }
            )
        else:
            steps.append(
                {
                    "step": "api_call",
                    "ok": False,
                    "message": "无已启用白名单路径可探测；请先 seed 全能力白名单",
                }
            )
        msg = str(args.get("message") or "").strip() or "AIOPEN 全调用闭环探测"
        chat_res = self._chat(app, {"message": msg})
        steps.append(
            {
                "step": "chat",
                "ok": _step_http_ok(chat_res),
                "status_code": chat_res.get("status_code"),
                "message": chat_res.get("message"),
            }
        )
        sessions = self._cursor().sessions_info()
        remote_on = bool(self._state.remote_control_enabled)
        steps.append(
            {
                "step": "ui_sessions",
                "ok": True,
                "remote_control_enabled": remote_on,
                "session_count": len(sessions),
                "ui_ready": remote_on and len(sessions) > 0,
            }
        )
        core_ok = all(
            bool(s.get("ok")) for s in steps if s.get("step") in {"api_catalog", "api_call", "chat"}
        )
        return {
            "success": core_ok,
            "closed_loop": core_ok,
            "ui_loop_ready": remote_on and len(sessions) > 0,
            "steps": steps,
            "hint": "API/对话闭环已通"
            + ("；虚拟光标已就绪" if remote_on and sessions else "；UI 闭环需面板开启「本页待命」")
            if core_ok
            else "闭环未通过：请检查白名单、鉴权与 unified_chat 是否可写",
        }
