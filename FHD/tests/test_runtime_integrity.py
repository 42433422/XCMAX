from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.fastapi_routes.mounts import health
from app.fastapi_routes.mounts.health import register_health_routes
from app.mod_sdk.deliverable_status import build_deliverable_status
from app.runtime_integrity import (
    clear_runtime_issue,
    neuro_degraded_reasons,
    record_runtime_component,
    record_runtime_issue,
    runtime_integrity_snapshot,
)


@pytest.mark.parametrize("lite", [True, False])
def test_required_runtime_failure_degrades_health_and_blocks_delivery(monkeypatch, lite):
    app = FastAPI(version="1.0.0")
    record_runtime_component(
        app,
        "desktop_runtime_routes",
        ok=False,
        required=True,
        detail="module missing",
    )
    monkeypatch.setattr("app.runtime_integrity.neuro_degraded_reasons", lambda _: ["offline"])
    register_health_routes(app)

    body = TestClient(app).get("/api/health", params={"lite": lite}).json()
    assert body["status"] == "unhealthy"
    assert "module missing" in body["degradedReasons"]
    assert ("offline" in body["degradedReasons"]) is (not lite)

    monkeypatch.setattr("app.mod_sdk.deliverable_status._mods_routes_loaded", lambda _app: True)
    data = build_deliverable_status([], app=app)
    assert data["deliverable"] is False
    assert any(b["code"] == "RUNTIME_COMPONENT_UNAVAILABLE" for b in data["blockers"])


def test_optional_process_issue_is_degraded_not_blocking():
    key = "test:optional-runtime"
    try:
        record_runtime_issue(key, "optional integration unavailable", ttl_seconds=30)
        state = runtime_integrity_snapshot()
        assert state["status"] == "degraded"
        assert state["blockers"] == []
    finally:
        clear_runtime_issue(key)


def test_neuro_llm_and_evolution_unavailable_are_not_reported_healthy():
    reasons = neuro_degraded_reasons(
        {
            "status": "healthy",
            "running": True,
            "cognition": {
                "cognition": {"llm_port_available": False},
                "evolution": {"error": "unavailable"},
            },
        }
    )
    assert "LLM_RUNTIME_UNAVAILABLE" in reasons
    assert "NEURO_EVOLUTION_UNAVAILABLE" in reasons


def _model_probe(monkeypatch, *, proxy_result=None, proxy=None):
    from app.fastapi_routes import market_account as market
    from app.infrastructure.auth import dependencies as auth

    calls = []
    owners = {"A": 11, "B": 22}
    monkeypatch.setattr(
        auth,
        "resolve_session_user",
        lambda request: (
            SimpleNamespace(
                id=owners.get(auth.session_id_from_request(request)),
                is_active=True,
            )
            if auth.session_id_from_request(request) in owners
            else None
        ),
    )
    monkeypatch.setattr(market, "_user_id_from_session", owners.get)
    monkeypatch.setattr(
        market,
        "session_market_token",
        lambda sid: {"A": "synthetic-A", "B": "synthetic-B"}.get(sid, ""),
    )
    monkeypatch.setattr(
        market,
        "latest_session_market_token",
        lambda *a, **k: pytest.fail("must not borrow another login"),
    )

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return await proxy() if proxy else proxy_result

    monkeypatch.setattr(market, "_proxy_json", request)
    return calls


def _request(sid=""):
    return Request({"type": "http", "headers": [(b"x-session-id", sid.encode())] if sid else []})


def test_session_health_resolves_each_exact_login_without_global_provider(monkeypatch):
    calls = _model_probe(
        monkeypatch,
        proxy_result={"ok": True, "provider": "configured-provider", "model": "configured-model"},
    )
    for sid in ("A", "B"):
        assert asyncio.run(health._session_model_health(_request(sid))) == {
            "status": "configured",
            "completion": "not_tested",
        }
    assert [call[2]["authorization"] for call in calls] == ["synthetic-A", "synthetic-B"]
    assert all(call[0:2] == ("GET", "/api/llm/resolve-chat-default") for call in calls)
    assert all(call[2]["timeout"] == 2.0 and call[2]["retries"] == 1 for call in calls)


def test_anonymous_invalid_and_owner_mismatched_health_never_queries_model(monkeypatch):
    calls = _model_probe(monkeypatch)
    assert asyncio.run(health._session_model_health(_request())) is None
    assert asyncio.run(health._session_model_health(_request("expired"))) is None
    monkeypatch.setattr("app.fastapi_routes.market_account._user_id_from_session", lambda _: 99)
    assert asyncio.run(health._session_model_health(_request("A"))) is None
    assert calls == []


def test_missing_session_token_cannot_use_host_credentials(monkeypatch):
    calls = _model_probe(monkeypatch)
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "synthetic-host-token")
    monkeypatch.setattr("app.fastapi_routes.market_account.session_market_token", lambda _: "")
    assert asyncio.run(health._session_model_health(_request("A"))) == {"status": "login_required"}
    assert calls == []


@pytest.mark.parametrize(
    "result, expected",
    [
        ({"__proxy_error__": True, "status_code": 401}, "auth_error"),
        ({"__proxy_error__": True, "status_code": 409}, "configuration_error"),
        ({"__proxy_error__": True, "status_code": 503}, "connection_error"),
        ({"ok": True, "provider": "p"}, "configuration_error"),
    ],
)
def test_failed_session_route_remains_unavailable(monkeypatch, result, expected):
    _model_probe(monkeypatch, proxy_result=result)
    assert asyncio.run(health._session_model_health(_request("A"))) == {"status": expected}


def test_session_probe_timeout_is_bounded(monkeypatch):
    async def stalled():
        await asyncio.sleep(10)

    _model_probe(monkeypatch, proxy=stalled)
    original = asyncio.wait_for
    monkeypatch.setattr(
        health.asyncio, "wait_for", lambda task, timeout: original(task, timeout=0.01)
    )
    assert asyncio.run(health._session_model_health(_request("A"))) == {
        "status": "connection_error"
    }


def test_scoped_route_configuration_replaces_only_unscoped_llm_failure(monkeypatch):
    from app.neuro_bus.integrations import fastapi_integration, intent_integration

    route = {"provider": "p", "model": "m"}
    _model_probe(monkeypatch, proxy_result=route)
    monkeypatch.setattr(intent_integration, "is_neuro_stack_enabled", lambda: True)
    shared_snapshot = {
        "status": "healthy",
        "running": True,
        "cognition": {"cognition": {"llm_port_available": False}},
    }
    monkeypatch.setattr(
        fastapi_integration,
        "get_neurobus_health",
        lambda: shared_snapshot,
    )
    app = FastAPI(version="1")
    register_health_routes(app)
    client = TestClient(app)
    response = client.get("/api/health", headers={"X-Session-ID": "A"})
    assert response.json()["status"] == "healthy"
    assert response.json()["sessionModel"]["completion"] == "not_tested"
    assert response.headers["cache-control"] == "private, no-store"
    assert "synthetic-A" not in response.text
    assert shared_snapshot["cognition"]["cognition"]["llm_port_available"] is False
    route["ok"] = False
    other = client.get("/api/health", headers={"X-Session-ID": "B"}).json()
    assert other["status"] == "degraded"
    assert other["neuro"]["cognition"]["cognition"]["llm_port_available"] is False
    anonymous = client.get("/api/health").json()
    assert anonymous["status"] == "healthy"
    assert "LLM_RUNTIME_UNAVAILABLE" not in anonymous["degradedReasons"]
    assert anonymous["capabilities"]["cognition.llm_port_available"] == {
        "ready": False,
        "status": "not_ready",
    }
    route["ok"] = True
    record_runtime_component(app, "required-component", ok=False, required=True)
    assert client.get("/api/health", headers={"X-Session-ID": "A"}).json()["status"] == "unhealthy"
    calls = _model_probe(monkeypatch)
    assert (
        "sessionModel"
        not in client.get("/api/health?lite=true", headers={"X-Session-ID": "A"}).json()
    )
    assert calls == []
