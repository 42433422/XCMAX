"""IM websocket route."""

from __future__ import annotations

import importlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from app.infrastructure.auth.agent_stream import STREAM_AUTH_ERRORS

logger = logging.getLogger("app.fastapi_routes.im_routes")
router = APIRouter()


def _facade():
    return importlib.import_module("app.fastapi_routes.im_routes")


@router.websocket("/ws/im")
async def im_websocket(ws: WebSocket):
    host = _facade()
    host._ensure_schema()
    await ws.accept()
    uid = await run_in_threadpool(host._resolve_ws_user_id, ws)
    if uid is None:
        await ws.close(code=4401, reason="unauthorized")
        return

    async def authorize() -> bool:
        try:
            return bool(await run_in_threadpool(host._resolve_ws_user_id, ws) == uid)
        except STREAM_AUTH_ERRORS:
            return False

    await host.im_ws_hub.connect(uid, ws, authorize=authorize)
    try:
        while True:
            raw = await ws.receive_text()
            if not await authorize():
                await ws.close(code=4401, reason="unauthorized")
                return
            if raw.strip().lower() in {"ping", '{"type":"ping"}'}:
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # Fanout can close a revoked socket while this receive loop is active.
        if ws.application_state != WebSocketState.DISCONNECTED:
            raise
    finally:
        await host.im_ws_hub.disconnect(uid, ws)
