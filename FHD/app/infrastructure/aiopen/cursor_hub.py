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
from collections.abc import Callable
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
        self._session_loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._session_auth: dict[str, Callable[[], bool]] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_sessions: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._command_log: list[dict[str, Any]] = []

    # ---- 会话管理 -------------------------------------------------

    async def connect(
        self,
        session_id: str,
        ws: WebSocket,
        meta: dict[str, Any] | None = None,
        *,
        authorize: Callable[[], bool] | None = None,
    ) -> None:
        async with self._lock:
            if session_id in self._sessions:
                raise ValueError("screen session already connected")
            self._sessions[session_id] = ws
            self._session_loops[session_id] = asyncio.get_running_loop()
            if authorize is not None:
                self._session_auth[session_id] = authorize
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
            self._session_loops.pop(session_id, None)
            self._session_auth.pop(session_id, None)
            for req_id, target in list(self._pending_sessions.items()):
                if target == session_id:
                    future = self._pending.get(req_id)
                    if future is not None and not future.done():
                        future.set_result(
                            {
                                "success": False,
                                "code": "SCREEN_DISCONNECTED",
                                "message": "操作窗口已断开；重新连接后回读状态，不能直接重试写操作",
                            }
                        )
        logger.info(
            "aiopen cursor ws disconnect session=%s total=%s", session_id, len(self._sessions)
        )

    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def sessions_info(
        self, *, owner_id: str | None = None, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            dict(meta)
            for meta in list(self._session_meta.values())
            if (owner_id is None or str(meta.get("owner_id") or "") == owner_id)
            and (tenant_id is None or str(meta.get("tenant_id") or "") == tenant_id)
        ]

    def dispatch_sync(
        self,
        action: str,
        params: dict[str, Any],
        *,
        owner_id: str,
        tenant_id: str,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Bridge synchronous task workers to the screen's owning ASGI loop."""
        candidates = self.sessions_info(owner_id=owner_id, tenant_id=tenant_id)
        ids = [str(item["session_id"]) for item in candidates]
        if session_id and session_id not in ids:
            return {
                "success": False,
                "code": "SCREEN_NOT_OWNED",
                "message": "目标窗口不属于当前账号或已离线",
            }
        if not session_id and len(ids) != 1:
            return {
                "success": False,
                "code": "SCREEN_SELECTION_REQUIRED",
                "message": "请开启软件控制并选择一个当前账号的在线窗口",
                "sessions": candidates,
            }
        target = session_id or ids[0]
        loop = self._session_loops.get(target)
        if loop is None or not loop.is_running():
            return {"success": False, "code": "SCREEN_OFFLINE", "message": "窗口控制通道不可用"}
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            return {
                "success": False,
                "code": "SCREEN_ASYNC_CONTEXT",
                "message": "同步任务需在工作线程执行，未下发操作",
            }
        future = asyncio.run_coroutine_threadsafe(
            self.dispatch(
                action,
                params,
                session_id=target,
                timeout=timeout,
                owner_id=owner_id,
                tenant_id=tenant_id,
            ),
            loop,
        )
        try:
            return future.result(timeout=timeout + 1)
        except TimeoutError:
            future.cancel()
            return {"success": False, "code": "SCREEN_RECEIPT_TIMEOUT", "outcome": "unknown"}

    # ---- 指令下发与回执 -------------------------------------------

    async def dispatch(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 10.0,
        owner_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """向 screen 会话下发指令并等待回执。

        ``session_id`` 为空时取第一个在线会话。返回前端回传的 ``result`` 字典；
        无会话 / 超时 / 发送失败统一返回 ``{"success": False, "message": ...}``。
        """
        if not session_id and len(self._sessions) > 1:
            return {
                "success": False,
                "code": "SCREEN_SELECTION_REQUIRED",
                "message": "多个窗口在线，请指定 session_id",
                "online_sessions": self.session_ids(),
            }
        target = session_id or (self.session_ids()[0] if self._sessions else None)
        if not target or target not in self._sessions:
            return {
                "success": False,
                "message": "没有在线的虚拟光标会话；请在 XCAGI 前端 AIOPEN 面板开启「远程操控」。",
                "online_sessions": self.session_ids(),
            }
        ws = self._sessions[target]
        authorize = self._session_auth.get(target)
        if authorize is not None and not authorize():
            await self.disconnect(target)
            return {
                "success": False,
                "code": "SCREEN_SESSION_EXPIRED",
                "message": "窗口登录会话已失效，请重新登录并连接控制通道",
            }
        meta = self._session_meta.get(target, {})
        if (owner_id is not None and str(meta.get("owner_id") or "") != owner_id) or (
            tenant_id is not None and str(meta.get("tenant_id") or "") != tenant_id
        ):
            return {
                "success": False,
                "code": "SCREEN_NOT_OWNED",
                "message": "窗口身份不匹配，未执行",
            }
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
        self._pending_sessions[req_id] = target
        self._log_command(
            {
                "id": req_id,
                "session_id": target,
                "action": action,
                "params": {
                    key: value
                    for key, value in (params or {}).items()
                    if key not in {"text", "value", "values"}
                },
                "ts": time.time(),
            }
        )
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except RECOVERABLE_ERRORS as err:
            self._pending.pop(req_id, None)
            self._pending_sessions.pop(req_id, None)
            await self.disconnect(target)
            return {"success": False, "message": f"指令下发失败：{err}"}
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            return {
                "success": False,
                "message": f"虚拟光标回执超时（{timeout:.0f}s）",
                "action": action,
                "code": "SCREEN_RECEIPT_TIMEOUT",
                "outcome": "unknown",
            }
        finally:
            self._pending.pop(req_id, None)
            self._pending_sessions.pop(req_id, None)
        if isinstance(result, dict):
            result.setdefault("success", False)
            result["session_id"] = target
            return result
        return {"success": False, "session_id": target, "code": "INVALID_SCREEN_RESULT"}

    def handle_client_message(self, raw: str, *, session_id: str) -> bool:
        """处理 screen 端回传的消息；命中 pending 回执返回 True。"""
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return False
        if not isinstance(msg, dict):
            return False
        req_id = str(msg.get("id") or "")
        if self._pending_sessions.get(req_id) != session_id:
            return False
        result = msg.get("result")
        if (
            msg.get("type") != "result"
            or not isinstance(result, dict)
            or not isinstance(result.get("success"), bool)
        ):
            return False
        fut = self._pending.get(req_id)
        if fut is None or fut.done():
            return False
        fut.set_result(result)
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
