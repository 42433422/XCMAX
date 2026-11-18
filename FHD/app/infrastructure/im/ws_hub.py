"""IM WebSocket 连接池（进程内广播）。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ImWsHub:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._authorizers: dict[WebSocket, Callable[[], Awaitable[bool]]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, user_id: int, ws: WebSocket, *, authorize: Callable[[], Awaitable[bool]] | None = None
    ) -> None:
        async with self._lock:
            self._connections[user_id].add(ws)
            if authorize is not None:
                self._authorizers[ws] = authorize
        logger.info("im ws connect user_id=%s total=%s", user_id, len(self._connections[user_id]))

    def connected_user_ids(self) -> set[int]:
        return set(self._connections.keys())

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns and ws in conns:
                conns.discard(ws)
            self._authorizers.pop(ws, None)
            if conns is not None and len(conns) == 0:
                self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> int:
        text = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            targets = [(ws, self._authorizers.get(ws)) for ws in self._connections.get(user_id, ())]
        dead: list[WebSocket] = []
        sent = 0
        for ws, authorize in targets:
            try:
                if authorize is not None and await authorize() is not True:
                    await ws.close(code=4401, reason="unauthorized")
                    dead.append(ws)
                    continue
                await ws.send_text(text)
                sent += 1
            except RECOVERABLE_ERRORS + (WebSocketDisconnect,):
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)
        return sent

    async def broadcast_members(self, user_ids: list[int], payload: dict[str, Any]) -> int:
        sent = 0
        for uid in dict.fromkeys(user_ids):
            sent += await self.send_to_user(uid, payload)
        return sent


im_ws_hub = ImWsHub()
