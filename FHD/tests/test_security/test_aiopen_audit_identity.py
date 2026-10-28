"""Authenticated actors, never payload identities, own AIOPEN audit records."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import ai_open, ai_qclaw
from app.fastapi_routes.aiopen_route_support import trace_control_result, trace_tool_call


@pytest.fixture
def capture(monkeypatch):
    recorder = Mock(return_value=SimpleNamespace(run_id="audit-test"))
    for route in (ai_open, ai_qclaw):
        monkeypatch.setattr(route, "create_chat_trace_run", recorder)
        monkeypatch.setattr(route, "verify_api_key", lambda key: key == "fixture-key")
    monkeypatch.setattr(ai_open, "invoke_tool", AsyncMock(return_value={"success": True}))
    monkeypatch.setattr(ai_open, "AIOPEN_STATE", {})
    monkeypatch.setattr(ai_qclaw, "_QCLOW_RUNTIME_STATE", {})
    return recorder


@pytest.mark.parametrize("field", ["user_id", "userId"])
@pytest.mark.parametrize("explicit", ["", "verified-actor"])
def test_trace_helpers_never_trust_payload_actor(field, explicit):
    recorder = Mock(return_value=SimpleNamespace(run_id="audit-test"))
    common = {
        "create_trace_run": recorder,
        "logger": logging.getLogger(__name__),
        "user_id": explicit,
    }
    payload = {"success": True}
    forged = {field: "forged-admin"}
    trace_tool_call(
        route="/api/aiopen/invoke",
        channel="aiopen_rest",
        tool="chat",
        args=forged,
        result=payload,
        **common,
    )
    assert recorder.call_args.kwargs["user_id"] == (explicit or "aiopen-api-key")
    trace_control_result(
        payload, route="/api/aiopen/control", action="update", body=forged, **common
    )
    assert recorder.call_args.kwargs["user_id"] == (explicit or "aiopen-control")
    assert forged == {field: "forged-admin"}
    assert payload == {"success": True}


@pytest.mark.parametrize(
    "route,path,body",
    [
        (ai_open, "/api/aiopen/control", {"enabled": True}),
        (ai_open, "/api/aiopen/config", {"base_url": "http://localhost:9999"}),
        (ai_open, "/api/aiopen/whitelist", {"path": "/fixture", "enabled": True}),
        (ai_qclaw, "/api/ai/qclaw/wechat-gateway", {"enabled": True}),
        (ai_qclaw, "/api/ai/qclaw/openclaw/config", {"base_url": "http://localhost:9999"}),
        (ai_qclaw, "/api/ai/qclaw/whitelist", {"path": "/fixture", "enabled": True}),
    ],
)
def test_control_routes_use_verified_admin(route, path, body, capture):
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[route.require_admin_user] = lambda: SimpleNamespace(id=73)
    original = {**body, "user_id": "victim", "userId": "other-victim"}
    with TestClient(app) as client:
        response = client.post(path, json=original)
    assert response.status_code == 200
    assert response.json()["run_id"] == "audit-test"
    assert capture.call_args.kwargs["user_id"] == "73"


@pytest.mark.parametrize("mcp", [False, True])
def test_key_only_tool_calls_do_not_impersonate_users(mcp, capture):
    app = FastAPI()
    app.include_router(ai_open.router)
    args = {"message": "fixture", "user_id": "victim", "userId": "other-victim"}
    if mcp:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "chat", "arguments": args},
            "user_id": "admin",
        }
        path = "/api/aiopen/mcp"
    else:
        body = {"tool": "chat", "args": args, "user_id": "admin", "userId": "root"}
        path = "/api/aiopen/invoke"
    with TestClient(app) as client:
        response = client.post(path, json=body, headers={"X-AIOPEN-Key": "fixture-key"})
    assert response.status_code == 200
    assert capture.call_args.kwargs["user_id"] == "aiopen-api-key"
    ai_open.invoke_tool.assert_awaited_once()


@pytest.mark.parametrize(
    "route,path",
    [
        (ai_open, "/api/aiopen/openclaw/chat"),
        (ai_qclaw, "/api/ai/qclaw/openclaw/chat"),
    ],
)
def test_proxy_chat_never_uses_body_actor(route, path, capture, monkeypatch):
    attach = Mock(side_effect=lambda payload, **kwargs: payload)
    monkeypatch.setattr(route, "attach_chat_trace_run", attach)
    monkeypatch.setattr(route, "openclaw_chat_proxy", lambda msg: ({"success": True}, 200))
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        response = client.post(
            path,
            json={"message": "fixture", "user_id": "victim"},
            headers={"X-AIOPEN-Key": "fixture-key"},
        )
    assert response.status_code == 200
    assert attach.call_args.kwargs["user_id"] == "aiopen-api-key"
