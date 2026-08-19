# ruff: noqa
"""IM websocket route."""
from __future__ import annotations
import importlib
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
logger = logging.getLogger('app.fastapi_routes.im_routes')
router = APIRouter()

def _facade():
    return importlib.import_module('app.fastapi_routes.im_routes')

@router.websocket('/ws/im')
async def im_websocket(ws: WebSocket):
    _facade()._ensure_schema()
    await ws.accept()
    uid = _facade()._resolve_ws_user_id(ws)
    if uid is None:
        await ws.close(code=4401, reason='unauthorized')
        return
    await _facade().im_ws_hub.connect(uid, ws)
    try:
        while True:
            raw = await ws.receive_text()
            if raw.strip().lower() in {'ping', '{"type":"ping"}'}:
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        await _facade().im_ws_hub.disconnect(uid, ws)
