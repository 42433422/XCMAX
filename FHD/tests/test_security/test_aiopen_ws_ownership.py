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
        self.messages: list[dict] = []

    async def send_text(self, data: str) -> None:
        self.sent = data
        self.messages.append(json.loads(data))


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


@pytest.mark.parametrize(
    ("origin", "host", "expected"),
    [
        # 本地开发：浏览器 42423，后端（或代理改写后）42422，同属回环
        ("http://127.0.0.1:42423", "127.0.0.1:42422", True),
        ("http://localhost:5173", "localhost:5100", True),
        ("http://[::1]:5173", "[::1]:5100", True),
        # 非回环地址的不同端口仍按跨源处理
        ("http://192.168.1.10:5173", "192.168.1.10:5100", False),
        ("http://evil.example", "127.0.0.1:42422", False),
    ],
)
def test_screen_origin_allows_loopback_cross_port_only(monkeypatch, origin, host, expected):
    monkeypatch.delenv("XCAGI_AIOPEN_WS_ALLOWED_ORIGINS", raising=False)
    websocket = SimpleNamespace(
        headers={"origin": origin, "host": host},
        url=SimpleNamespace(scheme="ws"),
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


@pytest.mark.asyncio
async def test_timeout_cancels_exact_command_and_reports_unknown_outcome():
    hub, socket = AiOpenCursorHub(), _Sock()
    await hub.connect("owner", socket, _meta(OWNER))
    with screen_principal_scope(OWNER):
        result = await hub.dispatch("click", {"ref": "e1"}, timeout=0.01)
    command, cancellation = socket.messages
    assert command["timeout_ms"] == 10
    assert cancellation == {"type": "cancel", "id": command["id"]}
    assert result == {
        "success": False,
        "code": "SCREEN_COMMAND_TIMEOUT",
        "message": "虚拟光标回执超时（0s），请先读取页面状态确认结果，勿重复写入",
        "action": "click",
        "request_id": command["id"],
        "outcome": "unknown",
        "retryable": False,
    }
    assert not hub._pending
    assert not hub.handle_client_message(
        json.dumps({"id": command["id"], "result": {"success": True}}), session_id="owner"
    )


@pytest.mark.asyncio
async def test_caller_cancellation_reaches_screen_and_releases_pending_receipt():
    hub, socket = AiOpenCursorHub(), _Sock()
    await hub.connect("owner", socket, _meta(OWNER))
    with screen_principal_scope(OWNER):
        work = asyncio.create_task(hub.dispatch("type", {"text": "private-value"}))
        await asyncio.sleep(0)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert hub.recent_commands()[0]["params"] == {"text": "[REDACTED]"}
    assert socket.messages[1] == {"type": "cancel", "id": socket.messages[0]["id"]}
    assert not hub._pending
    assert not hub._pending_sessions


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [{}, {"success": "true"}, {"success": 1}, ["done"], None])
async def test_malformed_receipt_never_becomes_success(receipt):
    hub, socket = AiOpenCursorHub(), _Sock()
    await hub.connect("owner", socket, _meta(OWNER))
    with screen_principal_scope(OWNER):
        work = asyncio.create_task(hub.dispatch("click", {"ref": "e1"}))
        await asyncio.sleep(0)
        request_id = socket.messages[0]["id"]
        hub.handle_client_message(
            json.dumps({"id": request_id, "result": receipt}), session_id="owner"
        )
        result = await work
    assert result == {
        "success": False,
        "code": "INVALID_SCREEN_RECEIPT",
        "outcome": "unknown",
        "session_id": "owner",
        "request_id": request_id,
    }


@pytest.mark.asyncio
async def test_receipt_cannot_replace_server_bound_session_or_request_identity():
    hub, socket = AiOpenCursorHub(), _Sock()
    await hub.connect("owner", socket, _meta(OWNER))
    with screen_principal_scope(OWNER):
        work = asyncio.create_task(hub.dispatch("verify"))
        await asyncio.sleep(0)
        request_id = socket.messages[0]["id"]
        hub.handle_client_message(
            json.dumps(
                {
                    "id": request_id,
                    "result": {"success": False, "session_id": "foreign", "request_id": "foreign"},
                }
            ),
            session_id="owner",
        )
        result = await work
    assert result == {"success": False, "session_id": "owner", "request_id": request_id}
