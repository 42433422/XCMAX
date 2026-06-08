"""WebSocket 长连接：站内通知、后续可扩展其它推送。

路径 ``/api/realtime/ws`` 不落在 ``PROXY_PREFIXES``，始终由本 FastAPI 进程处理。
鉴权：查询参数 ``token``（与 HTTP Bearer 相同的 JWT access）。

**应用层心跳**：前端约每 50s 发送 ``{"type":"ping","t":...}``，本服务回复 ``pong``
（参见 ``market/src/realtimeClient.ts``）。反向代理 ``proxy_read_timeout`` / ``proxy_send_timeout``
须大于心跳间隔并留余量，否则空闲 TCP 可能被切断；见 ``docs/runbooks/websocket-proxy-timeouts.md``。

**空闲回收**：若在约 ``_IDLE_RECV_TIMEOUT_SEC`` 内未收到任意客户端文本帧（含 ping），服务端主动关闭，
避免僵尸连接占满 worker。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from modstore_server.auth_service import decode_access_token, get_user_by_id
from modstore_server.metrics import observe_realtime_ws_event

logger = logging.getLogger(__name__)

# 与 market/src/realtimeClient.ts 中 ping 间隔 (~50s) 对齐：超时须显著大于该间隔
_IDLE_RECV_TIMEOUT_SEC = 130.0

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


class _ConnectionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sockets: dict[int, set[WebSocket]] = defaultdict(set)

    async def register(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._sockets[user_id].add(ws)

    async def unregister(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._sockets.get(user_id)
            if not conns:
                return
            conns.discard(ws)
            if not conns:
                del self._sockets[user_id]

    async def send_json_to_user(self, user_id: int, payload: dict[str, Any]) -> int:
        """推送给该用户所有已连接；返回成功送达的套接字数。"""
        data = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            conns = list(self._sockets.get(user_id, ()))
        n = 0
        for ws in conns:
            try:
                await ws.send_text(data)
                n += 1
            except Exception as e:
                logger.debug("WebSocket 发送失败 user_id=%s: %s", user_id, e)
        return n


_manager = _ConnectionManager()


def schedule_push_to_user(user_id: int, payload: dict[str, Any]) -> None:
    """在同步上下文中安全调度推送（如创建通知时）；无运行中的事件循环则忽略。"""
    if not user_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _go() -> None:
        try:
            await _manager.send_json_to_user(int(user_id), payload)
        except Exception as e:
            logger.debug("realtime 推送任务失败: %s", e)

    loop.create_task(_go())


@router.websocket(
    "/ws",
    name="realtime_ws_channel",
)
async def websocket_channel(
    websocket: WebSocket,
    token: str = Query(
        "",
        description="与 HTTP ``Authorization: Bearer`` 相同的 JWT access token。",
    ),
) -> None:
    """建立用户级 WebSocket；服务端推送 ``notification`` 等 JSON。客户端可发 JSON ping 维持连接。"""
    await websocket.accept()
    raw = (token or "").strip()
    if not raw:
        observe_realtime_ws_event("auth_fail")
        await websocket.close(code=1008)
        return
    pl = decode_access_token(raw)
    if not pl:
        observe_realtime_ws_event("auth_fail")
        await websocket.close(code=1008)
        return
    try:
        user_id = int(pl.get("sub") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id or not get_user_by_id(user_id):
        observe_realtime_ws_event("auth_fail")
        await websocket.close(code=1008)
        return

    observe_realtime_ws_event("accepted")
    await _manager.register(user_id, websocket)
    try:
        await websocket.send_text(
            json.dumps({"type": "ready", "user_id": user_id}, ensure_ascii=False)
        )
    except Exception:
        await _manager.unregister(user_id, websocket)
        observe_realtime_ws_event("ready_send_fail")
        return

    observe_realtime_ws_event("ready")
    try:
        while True:
            try:
                msg = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=_IDLE_RECV_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                observe_realtime_ws_event("idle_timeout")
                try:
                    await websocket.close(code=1000)
                except Exception:
                    pass
                break
            except WebSocketDisconnect:
                break
            try:
                body = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if body.get("type") == "ping":
                observe_realtime_ws_event("ping")
                t = body.get("t")
                await websocket.send_json({"type": "pong", "t": t})
    finally:
        await _manager.unregister(user_id, websocket)
        observe_realtime_ws_event("unregister")
