"""Security regressions for AIOPEN WebSocket authentication and reply ownership."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.fastapi_routes import ai_open as ai_open_routes
from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub


@pytest.mark.parametrize(
    ("principal", "origin"),
    [
        (None, "http://testserver"),
        (SimpleNamespace(id=1, is_active=False), "http://testserver"),
        (SimpleNamespace(id=1, is_active=True), "https://attacker.example"),
        (SimpleNamespace(id=1, is_active=True), None),
    ],
)
def test_screen_rejects_anonymous_disabled_or_untrusted_origin(monkeypatch, principal, origin):
    monkeypatch.delenv("XCAGI_AIOPEN_WS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setattr(ai_open_routes, "resolve_session_user", lambda ws: principal)
    app = FastAPI()
    app.include_router(ai_open_routes.router)
    headers = {"Origin": origin} if origin else {}
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/aiopen/ws", headers=headers):
                pass


def test_screen_explicit_cross_origin_allowlist(monkeypatch):
    monkeypatch.setenv("XCAGI_AIOPEN_WS_ALLOWED_ORIGINS", "https://frontend.example")
    monkeypatch.setattr(
        ai_open_routes,
        "resolve_session_user",
        lambda ws: SimpleNamespace(id=7, tenant_id=3, is_active=True),
    )
    app = FastAPI()
    app.include_router(ai_open_routes.router)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/aiopen/ws", headers={"Origin": "https://frontend.example"}
        ) as ws:
            assert ws.receive_json()["session_id"].startswith("screen_")


@pytest.mark.asyncio
async def test_screen_acknowledgements_bound_to_own_connection():
    hub = AiOpenCursorHub()

    class FakeSocket:
        sent: str = ""

        async def send_text(self, data: str) -> None:
            self.sent = data

    owner = FakeSocket()
    impostor = FakeSocket()
    await hub.connect("owner", owner)
    await hub.connect("impostor", impostor)
    work = asyncio.create_task(hub.dispatch("snapshot", {}, session_id="owner", timeout=1))
    await asyncio.sleep(0)
    command = json.loads(owner.sent)
    reply = json.dumps({"id": command["id"], "result": {"success": True, "data": "ok"}})
    assert hub.handle_client_message(reply, session_id="impostor") is False
    assert not work.done()
    assert hub.handle_client_message(reply, session_id="owner") is True
    assert (await work)["data"] == "ok"
    await hub.disconnect("owner")
    await hub.disconnect("impostor")


@pytest.mark.asyncio
async def test_disconnected_screen_cannot_leave_pending_command_running():
    hub = AiOpenCursorHub()

    class FakeSocket:
        async def send_text(self, data: str) -> None:
            return None

    await hub.connect("screen", FakeSocket())
    work = asyncio.create_task(hub.dispatch("click", {}, session_id="screen", timeout=5))
    await asyncio.sleep(0)
    await hub.disconnect("screen")
    result = await asyncio.wait_for(work, timeout=1)
    assert result["code"] == "SCREEN_DISCONNECTED"
