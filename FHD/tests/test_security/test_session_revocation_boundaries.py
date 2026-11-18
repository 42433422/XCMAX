"""HTTP and IM connections must observe account and session revocation."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.application import agent_tool_lifecycle as service
from app.application import task_conversation_store as conversation_store
from app.application.facades import session_facade
from app.db.db_base import Base
from app.db.models import AIConversation, AIConversationSession
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes import im_routes, im_websocket_route
from app.fastapi_routes.agent_tool_lifecycle import router
from app.fastapi_routes.domains.conversation.conversation_routes import (
    router as conversation_router,
)
from app.infrastructure.im.ws_hub import ImWsHub
from app.infrastructure.session import session_manager
from app.infrastructure.tenant_scope import tenant_scope
from app.middleware.csrf import CSRFMiddleware
from app.middleware.industry_context import IndustryContextMiddleware
from app.utils.time import utc_now_naive
from tests.fixtures.agent_tool_lifecycle_support import _base_body


@pytest.fixture
def authorized_http(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            UserSession.__table__,
            AIConversationSession.__table__,
            AIConversation.__table__,
        ],
    )
    with Session(engine) as db:
        db.add(
            User(
                id=1,
                username="tool-admin",
                password="test-only",
                role="admin",
                tier="enterprise",
                tenant_id=10,
                is_active=True,
            )
        )
        db.add(
            UserSession(
                user_id=1,
                session_id="tool-session",
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
        db.commit()

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(session_manager, "get_host_db", database)
    monkeypatch.setattr(session_facade, "get_session_service", session_manager.SessionManager)
    monkeypatch.setattr(conversation_store, "get_db", database)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    monkeypatch.delenv("XCAGI_AGENT_TOOL_HEADER_AUTH", raising=False)
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    registry = tmp_path / "tools.sqlite3"
    service.reset_for_tests(str(registry))
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(router)
    app.include_router(conversation_router)
    app.include_router(im_websocket_route.router)
    # Only schema bootstrapping is excluded; authentication and fanout remain real.
    monkeypatch.setattr(im_routes, "_ensure_schema", lambda: None)
    hub = ImWsHub()
    monkeypatch.setattr(im_routes, "im_ws_hub", hub)
    try:
        with tenant_scope(None), TestClient(app) as client:
            client.get("/api/agent-tools")
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            yield client, engine, registry, hub
    finally:
        service.reset_for_tests(None)
        engine.dispose()


@pytest.mark.parametrize("credential", ["cookie", "session-header", "bearer"])
def test_disabling_account_immediately_blocks_tool_reads_and_writes(
    authorized_http, monkeypatch, credential
):
    client, engine, registry, _ = authorized_http
    if credential == "cookie":
        client.cookies.set("session_id", "tool-session")
    elif credential == "session-header":
        client.headers["X-Session-ID"] = "tool-session"
    else:
        client.headers["Authorization"] = "Bearer tool-session"
    created = client.post("/api/agent-tools", json=_base_body("existing_tool"))
    assert created.status_code == 201, created.text
    assert created.json()["data"]["tenant_id"] == 10
    assert client.get("/api/agent-tools").status_code == 200

    with Session(engine) as db:
        db.get(User, 1).is_active = False
        db.commit()

    # Even an enabled development header must not replace a disabled session.
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HEADER_AUTH", "1")
    client.headers.update({"X-Actor-Role": "admin", "X-Actor-Id": "other-admin"})
    for method, path, body in (
        ("GET", "/api/agent-tools", None),
        ("GET", "/api/agent-tools/audit", None),
        ("GET", "/api/agent-tools/discovery", None),
        ("POST", "/api/agent-tools", _base_body("blocked_tool")),
        ("POST", "/api/agent-tools/employees", {"principal_id": "new", "role": "employee"}),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "account_disabled"
    with sqlite3.connect(registry) as db:
        assert db.execute("SELECT COUNT(*), MIN(tool_key) FROM tools").fetchone() == (
            1,
            "existing_tool",
        )
        assert db.execute("SELECT COUNT(*) FROM principals").fetchone()[0] == 0
    with Session(engine) as db:
        db.get(User, 1).is_active = True
        db.commit()
    assert client.get("/api/agent-tools").status_code == 200


def _revoke(engine, change):
    with Session(engine) as db:
        if change == "disabled":
            db.get(User, 1).is_active = False
        else:
            session = db.query(UserSession).filter_by(session_id="tool-session").one()
            if change == "deleted":
                db.delete(session)
            elif change == "reassigned":
                db.add(User(id=2, username="other", password="test-only", is_active=True))
                session.user_id = 2
            else:
                session.expires_at = utc_now_naive() - timedelta(seconds=1)
        db.commit()


def test_disabled_account_cannot_read_or_delete_durable_history(authorized_http):
    client, engine, _, _ = authorized_http
    client.cookies.set("session_id", "tool-session")
    conversation_store.task_conversation_store.save_message(
        session_id="owned-chat", user_id=1, role="user", content="Private local fixture"
    )
    response = client.get("/api/conversations/owned-chat")
    assert response.status_code == 200 and "Private local fixture" in response.text
    _revoke(engine, "disabled")
    for method in ("GET", "DELETE"):
        response = client.request(method, "/api/conversations/owned-chat")
        assert response.status_code == 403, response.text
    with Session(engine) as db:
        assert db.query(AIConversation).count() == 1


@pytest.mark.parametrize("credential", ["cookie", "query"])
def test_disabled_session_cannot_open_im_connection_or_use_test_identity(
    authorized_http, monkeypatch, credential
):
    client, engine, _, hub = authorized_http
    _revoke(engine, "disabled")
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    path = "/ws/im?user_id=1"
    if credential == "cookie":
        client.cookies.set("session_id", "tool-session")
    else:
        path += "&session_id=tool-session"
    with client.websocket_connect(path) as ws:
        ws.send_text("ping")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 4401
    assert hub.connected_user_ids() == set()


@pytest.mark.parametrize("change", ["disabled", "deleted", "expired", "reassigned"])
@pytest.mark.parametrize("direction", ["ping", "notification"])
def test_existing_im_connection_rechecks_session_before_sending(authorized_http, change, direction):
    client, engine, _, hub = authorized_http
    with client.websocket_connect("/ws/im?session_id=tool-session") as ws:
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}
        _revoke(engine, change)
        if direction == "ping":
            ws.send_text("ping")
        else:
            sent = client.portal.call(hub.send_to_user, 1, {"type": "message", "body": "private"})
            assert sent == 0
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 4401
    assert hub.connected_user_ids() == set()


def test_revoking_one_im_session_preserves_another_session(authorized_http):
    client, engine, _, hub = authorized_http
    with Session(engine) as db:
        db.add(
            UserSession(
                user_id=1,
                session_id="second-session",
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
        db.commit()
    with (
        client.websocket_connect("/ws/im?session_id=tool-session") as first,
        client.websocket_connect("/ws/im?session_id=second-session") as second,
    ):
        for ws in (first, second):
            ws.send_text("ping")
            assert ws.receive_json() == {"type": "pong"}
        _revoke(engine, "deleted")
        payload = {"type": "message", "body": "only for a valid session"}
        assert client.portal.call(hub.send_to_user, 1, payload) == 1
        with pytest.raises(WebSocketDisconnect) as closed:
            first.receive_text()
        assert closed.value.code == 4401
        assert second.receive_json() == payload


async def test_failed_revoked_socket_close_does_not_interrupt_valid_session():
    hub = ImWsHub()
    delivered = []
    close_attempts = []

    async def receive():
        return {"type": "websocket.connect"}

    async def broken_send(message):
        if message["type"] == "websocket.close":
            close_attempts.append(message)
            raise OSError("local disconnected transport fixture")

    async def valid_send(message):
        if message["type"] == "websocket.send":
            delivered.append(message["text"])

    async def deny():
        return False

    async def allow():
        return True

    revoked = WebSocket({"type": "websocket"}, receive=receive, send=broken_send)
    active = WebSocket({"type": "websocket"}, receive=receive, send=valid_send)
    await revoked.accept()
    await active.accept()
    await hub.connect(1, revoked, authorize=deny)
    await hub.connect(1, active, authorize=allow)
    assert await hub.send_to_user(1, {"type": "message"}) == 1
    assert await hub.send_to_user(1, {"type": "message"}) == 1
    assert len(delivered) == 2 and len(close_attempts) == 1
    await hub.disconnect(1, active)
    assert hub.connected_user_ids() == set()
