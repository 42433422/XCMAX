"""AIOPEN 虚拟光标 WS 会话池。

前端（screen 端）通过 ``WS /api/aiopen/ws`` 连入并登记为一个 screen 会话；
外部 AI Agent 通过 MCP / REST 调 ``ui_*`` 工具时，由本 Hub 将指令下发到
目标会话，并以 request/response（按 ``id`` 关联）等待前端回执。

仿 :mod:`app.infrastructure.im.ws_hub` 的进程内连接池实现，无持久化。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MAX_COMMAND_LOG = 200


class AiOpenCursorHub:
    """进程内虚拟光标会话池：screen 会话注册 + 指令下发 + 回执关联。"""

    def __init__(self) -> None:
        self._sessions: dict[str, WebSocket] = {}
        self._session_meta: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._command_log: list[dict[str, Any]] = []

    # ---- 会话管理 -------------------------------------------------

    async def connect(
        self, session_id: str, ws: WebSocket, meta: dict[str, Any] | None = None
    ) -> None:
        async with self._lock:
            self._sessions[session_id] = ws
            self._session_meta[session_id] = {
                "session_id": session_id,
                "connected_at": time.time(),
                **(meta or {}),
            }
        logger.info("aiopen cursor ws connect session=%s total=%s", session_id, len(self._sessions))

    async def disconnect(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
            self._session_meta.pop(session_id, None)
        logger.info(
            "aiopen cursor ws disconnect session=%s total=%s", session_id, len(self._sessions)
        )

    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def sessions_info(self) -> list[dict[str, Any]]:
        return [dict(meta) for meta in self._session_meta.values()]

    # ---- 指令下发与回执 -------------------------------------------

    async def dispatch(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """向 screen 会话下发指令并等待回执。

        ``session_id`` 为空时取第一个在线会话。返回前端回传的 ``result`` 字典；
        无会话 / 超时 / 发送失败统一返回 ``{"success": False, "message": ...}``。
        """
        target = session_id or (self.session_ids()[0] if self._sessions else None)
        if not target or target not in self._sessions:
            return {
                "success": False,
                "message": "没有在线的虚拟光标会话；请在 XCAGI 前端 AIOPEN 面板开启「远程操控」。",
                "online_sessions": self.session_ids(),
            }
        ws = self._sessions[target]
        req_id = uuid.uuid4().hex
        payload = {
            "type": "command",
            "id": req_id,
            "action": action,
            "params": params or {},
        }
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        self._log_command(
            {
                "id": req_id,
                "session_id": target,
                "action": action,
                "params": params or {},
                "ts": time.time(),
            }
        )
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except RECOVERABLE_ERRORS as err:
            self._pending.pop(req_id, None)
            await self.disconnect(target)
            return {"success": False, "message": f"指令下发失败：{err}"}
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            return {
                "success": False,
                "message": f"虚拟光标回执超时（{timeout:.0f}s）",
                "action": action,
            }
        finally:
            self._pending.pop(req_id, None)
        if isinstance(result, dict):
            result.setdefault("success", True)
            result.setdefault("session_id", target)
            return result
        return {"success": True, "session_id": target, "result": result}

    def handle_client_message(self, raw: str) -> bool:
        """处理 screen 端回传的消息；命中 pending 回执返回 True。"""
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return False
        if not isinstance(msg, dict):
            return False
        req_id = str(msg.get("id") or "")
        fut = self._pending.get(req_id)
        if fut is None or fut.done():
            return False
        fut.set_result(msg.get("result") if isinstance(msg.get("result"), dict) else msg)
        return True

    # ---- 指令日志 -------------------------------------------------

    def _log_command(self, entry: dict[str, Any]) -> None:
        self._command_log.append(entry)
        overflow = len(self._command_log) - _MAX_COMMAND_LOG
        if overflow > 0:
            del self._command_log[:overflow]

    def recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._command_log[-max(1, int(limit)) :])


aiopen_cursor_hub = AiOpenCursorHub()
