"""Real host SQL credentials and external HTTP/command ownership boundaries."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.application.aiopen.service import (
    AIOPEN_STATE,
    generate_api_key,
    invoke_tool,
    verify_api_key,
)
from app.db.models.user import Session, User
from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub
from app.infrastructure.request_context import reset_current_request, set_current_request


def request_for(**headers):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/aiopen/invoke",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "query_string": b"",
        }
    )


@pytest.fixture
def host(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'host.sqlite'}")
    factory = sessionmaker(bind=engine)
    User.__table__.create(engine)
    Session.__table__.create(engine)
    with factory.begin() as db:
        for owner, tenant in [(3, 7), (4, 7), (5, 8)]:
            db.add(
                User(
                    id=owner,
                    username=f"u{owner}",
                    password="test",
                    tenant_id=tenant,
                    is_active=True,
                )
            )
            db.add(
                Session(
                    id=owner,
                    session_id=f"login-{owner}",
                    user_id=owner,
                    expires_at=datetime.now(UTC) + timedelta(days=2),
                )
            )
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    monkeypatch.setattr("app.infrastructure.session.session_manager.get_host_db", factory)
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id", lambda sid: None
    )
    monkeypatch.setitem(AIOPEN_STATE, "runtime_keys", {})
    monkeypatch.setitem(AIOPEN_STATE, "remote_control_enabled", True)
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(host, monkeypatch):
    from app.fastapi_routes import ai_open

    app = FastAPI()
    app.include_router(ai_open.router)
    monkeypatch.setattr(ai_open, "_trace_aiopen_control_result", lambda result, **kwargs: result)
    monkeypatch.setattr(ai_open, "_trace_aiopen_tool_call", lambda **kwargs: "")

    @app.middleware("http")
    async def context(request, call_next):
        token = set_current_request(request)
        try:
            return await call_next(request)
        finally:
            reset_current_request(token)

    with TestClient(app) as result:
        yield result


def test_http_issuance_listing_revocation_and_expiry(client, host):
    assert client.post("/api/aiopen/keys", json={}).status_code == 401
    response = client.post(
        "/api/aiopen/keys",
        headers={"X-Session-Id": "login-3"},
        json={"owner_id": "5", "tenant_id": "8", "label": "owner3"},
    )
    assert response.status_code == 200
    payload = response.json()
    key = payload["key"]
    grant = AIOPEN_STATE["runtime_keys"][key]["screen_grant"]
    assert grant["owner_id"] == "3" and grant["tenant_id"] == "7"
    assert "login-3" not in json.dumps(AIOPEN_STATE)
    assert "session_digest" not in payload
    assert 86000 < payload["expires_at"] - datetime.now(UTC).timestamp() <= 86400
    assert verify_api_key(key)
    assert client.get("/api/aiopen/keys", headers={"X-Session-Id": "login-4"}).json()["keys"] == []
    own = client.get("/api/aiopen/keys", headers={"X-Session-Id": "login-3"}).json()["keys"]
    assert len(own) == 1 and key not in json.dumps(own)
    assert not client.request(
        "DELETE", "/api/aiopen/keys", headers={"X-Session-Id": "login-4"}, json={"key": key}
    ).json()["success"]
    assert client.request(
        "DELETE", "/api/aiopen/keys", headers={"X-Session-Id": "login-3"}, json={"key": key}
    ).json()["success"]
    result = client.post(
        "/api/aiopen/invoke",
        headers={"X-AIOPEN-Key": key, "X-Session-Id": "login-4"},
        json={"tool": "ui_sessions"},
    ).json()
    assert not result["success"]  # revoked key cannot fall back to login-4


@pytest.mark.parametrize(
    "change", ["disabled", "tenant", "expired", "logout", "replaced", "grant_expired"]
)
def test_existing_key_rechecks_current_host_state(host, change):
    key = generate_api_key(request=request_for(**{"X-Session-Id": "login-3"}))["key"]
    with host.begin() as db:
        if change == "disabled":
            db.get(User, 3).is_active = False
        elif change == "tenant":
            db.get(User, 3).tenant_id = 8
        elif change == "expired":
            db.get(Session, 3).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif change == "logout":
            db.delete(db.get(Session, 3))
        elif change == "replaced":
            db.get(Session, 3).session_id = "replacement-login"
        else:
            AIOPEN_STATE["runtime_keys"][key]["screen_grant"]["expires_at"] = 0
    assert not verify_api_key(key)


def test_http_mcp_and_panel_hide_peer_windows(client, monkeypatch):
    hub = AiOpenCursorHub()
    hub._session_meta.update(
        {
            "own": {"session_id": "own", "owner_id": "3", "tenant_id": "7"},
            "peer": {"session_id": "peer", "owner_id": "4", "tenant_id": "7"},
            "tenant": {"session_id": "tenant", "owner_id": "3", "tenant_id": "8"},
        }
    )
    hub._log_command({"session_id": "peer", "text": "private peer activity"})
    hub._log_command({"session_id": "own", "action": "click"})
    monkeypatch.setattr("app.application.aiopen.service.aiopen_cursor_hub", hub)
    monkeypatch.setattr("app.fastapi_routes.ai_open.aiopen_cursor_hub", hub)
    key = client.post("/api/aiopen/keys", headers={"X-Session-Id": "login-3"}, json={}).json()[
        "key"
    ]
    response = client.post(
        "/api/aiopen/mcp",
        headers={"X-AIOPEN-Key": key},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "ui_sessions", "arguments": {}},
        },
    )
    assert response.status_code == 200
    assert "own" in response.text and "peer" not in response.text
    panel = client.get("/api/aiopen/panel", headers={"X-Session-Id": "login-3"}).json()
    assert [s["session_id"] for s in panel["screen_sessions"]] == ["own"]
    assert panel["recent_commands"] == [{"session_id": "own", "action": "click"}]
    assert client.get("/api/aiopen/panel").json()["screen_sessions"] == []


@pytest.mark.asyncio
async def test_external_key_only_lists_and_controls_owned_windows(host, monkeypatch):
    key = generate_api_key(request=request_for(**{"X-Session-Id": "login-3"}))["key"]
    hub = AiOpenCursorHub()
    own, peer = AsyncMock(), AsyncMock()
    await hub.connect("own", own, {"owner_id": "3", "tenant_id": "7"})
    await hub.connect("peer", peer, {"owner_id": "4", "tenant_id": "7"})
    monkeypatch.setattr("app.application.aiopen.service.aiopen_cursor_hub", hub)
    commands = []

    async def receipt(raw):
        command = json.loads(raw)
        commands.append(command)
        hub.handle_client_message(
            json.dumps({"type": "result", "id": command["id"], "result": {"success": True}}),
            session_id="own",
        )

    own.send_text.side_effect = receipt
    token = set_current_request(request_for(**{"X-AIOPEN-Key": key, "X-Session-Id": "login-4"}))
    try:
        listing = await invoke_tool("ui_sessions", {}, None)
        assert [row["session_id"] for row in listing["sessions"]] == ["own"]
        denied = await invoke_tool(
            "ui_click", {"session_id": "peer", "owner_id": "4", "selector": "#save"}, None
        )
        assert not denied["success"]
        peer.send_text.assert_not_called()
        done = await invoke_tool("ui_click", {"session_id": "own", "selector": "#save"}, None)
        assert done["success"] and len(commands) == 1
    finally:
        reset_current_request(token)


@pytest.mark.asyncio
async def test_shared_key_does_not_grant_screen_authority(host, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "shared-key")
    token = set_current_request(
        request_for(**{"X-AIOPEN-Key": "shared-key", "X-Session-Id": "login-3"})
    )
    try:
        assert verify_api_key("shared-key")
        for tool in ("ui_sessions", "ui_snapshot", "ui_set_files", "ui_navigate"):
            assert (await invoke_tool(tool, {}, None))["code"] == "SCREEN_IDENTITY_REQUIRED"
    finally:
        reset_current_request(token)
