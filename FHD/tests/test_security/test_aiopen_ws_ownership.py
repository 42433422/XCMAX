"""Security regressions for AIOPEN WebSocket authentication and reply ownership."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.domain.aiopen.principal import ScreenPrincipal
from app.fastapi_routes import ai_open as ai_open_routes
from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub
from app.infrastructure.aiopen.principal_context import screen_principal_scope

OWNER = ScreenPrincipal("owner", "tenant-a")


def _meta(p: ScreenPrincipal) -> dict[str, str]:
    return {"principal_id": p.principal_id, "tenant_id": p.tenant_id}


class _Sock:
    def __init__(self) -> None:
        self.sent = ""

    async def send_text(self, data: str) -> None:
        self.sent = data


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
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/aiopen/ws", headers=headers):
            pass


@pytest.mark.parametrize(
    ("request_scheme", "origin", "expected"),
    [
        ("ws", "http://testserver", True),
        ("wss", "https://testserver", True),
        ("ws", "https://testserver", False),
        ("wss", "http://testserver", False),
    ],
)
def test_screen_origin_scheme_must_match_transport_scheme(
    monkeypatch, request_scheme, origin, expected
):
    monkeypatch.delenv("XCAGI_AIOPEN_WS_ALLOWED_ORIGINS", raising=False)
    websocket = SimpleNamespace(
        headers={"origin": origin, "host": "testserver"},
        url=SimpleNamespace(scheme=request_scheme),
    )
    assert ai_open_routes._trusted_screen_origin(websocket) is expected


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
    hub, owner, impostor = AiOpenCursorHub(), _Sock(), _Sock()
    await hub.connect("owner", owner, _meta(OWNER))
    await hub.connect("impostor", impostor, _meta(ScreenPrincipal("impostor", "tenant-a")))
    with screen_principal_scope(OWNER):
        work = asyncio.create_task(hub.dispatch("snapshot", {}, session_id="owner", timeout=1))
        await asyncio.sleep(0)
        reply = json.dumps(
            {"id": json.loads(owner.sent)["id"], "result": {"success": True, "data": "ok"}}
        )
        assert hub.handle_client_message(reply, session_id="impostor") is False
        assert not work.done()
        assert hub.handle_client_message(reply, session_id="owner") is True
        assert (await work)["data"] == "ok"
    await hub.disconnect("owner")
    await hub.disconnect("impostor")


@pytest.mark.asyncio
async def test_disconnected_screen_cannot_leave_pending_command_running():
    hub, screen = AiOpenCursorHub(), ScreenPrincipal("screen", "tenant-a")
    await hub.connect("screen", _Sock(), _meta(screen))
    with screen_principal_scope(screen):
        work = asyncio.create_task(hub.dispatch("click", {}, session_id="screen", timeout=5))
        await asyncio.sleep(0)
        await hub.disconnect("screen")
        result = await asyncio.wait_for(work, timeout=1)
    assert result["code"] == "SCREEN_DISCONNECTED"
