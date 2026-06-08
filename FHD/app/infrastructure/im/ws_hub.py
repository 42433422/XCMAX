"""IM WebSocket 连接池（进程内广播）。"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ImWsHub:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[user_id].add(ws)
        logger.info("im ws connect user_id=%s total=%s", user_id, len(self._connections[user_id]))

    def connected_user_ids(self) -> set[int]:
        return set(self._connections.keys())

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns and ws in conns:
                conns.discard(ws)
            if conns is not None and len(conns) == 0:
                self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            targets = list(self._connections.get(user_id, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except OPERATIONAL_ERRORS:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)

    async def broadcast_members(self, user_ids: list[int], payload: dict[str, Any]) -> None:
        for uid in user_ids:
            await self.send_to_user(uid, payload)


im_ws_hub = ImWsHub()
