"""AIOPEN knowledge reads must cross the in-process LAN gate without opening it."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.application.aiopen.service import (
    AIOPEN_STATE,
    generate_api_key,
    issue_client_key,
)
from app.application.dataset_rag.access_policy import _ensure_tenant_allowed
from app.domain.aiopen.principal import ScreenPrincipal
from app.fastapi_routes.ai_open import router as ai_open_router
from app.fastapi_routes.dataset_access import dataset_access_context_from_request
from app.security.lan_cidr_guard import LanCidrGuard
from app.security.lan_config import LanConfig
from app.security.license_guard import LanLicenseGuard

_OWNER = ScreenPrincipal.from_ids("7", "42")
assert _OWNER is not None


def _cfg() -> LanConfig:
    return LanConfig(
        enabled=True,
        allowed_cidrs=("10.0.0.0/8",),
        trusted_proxies=(),
        admin_host_ips=("127.0.0.1", "::1"),
        bypass_paths=("/api/aiopen/invoke", "/api/aiopen/mcp"),
        license_secret="test-secret",
        token_ttl_seconds=3600,
        admin_bootstrap_key="",
        license_db_path=Path("/tmp/aiopen-knowledge-lan.db"),
        cookie_name="lan",
        cookie_secure=False,
        cookie_samesite="Lax",
        cookie_domain="",
        static_prefixes=(),
        public_admin_hosts=(),
    )


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LanLicenseGuard)
    app.add_middleware(LanCidrGuard)
    app.include_router(ai_open_router)

    @app.get("/api/knowledge/v1/health")
    def health(request: Request) -> dict:
        context = dataset_access_context_from_request(request)
        return {
            "success": True,
            "tenant_id": context.tenant_id,
            "is_admin": context.is_admin,
            "permissions": sorted(context.permissions),
        }

    @app.get("/api/knowledge/v1/datasets/{tenant_id}", response_model=None)
    def datasets(tenant_id: str, request: Request):
        context = dataset_access_context_from_request(request)
        denied = _ensure_tenant_allowed(context, tenant_id, dataset_id="kb", operation="read")
        if denied is not None:
            return JSONResponse(denied, status_code=403)
        return {"success": True, "tenant_id": tenant_id, "is_admin": context.is_admin}

    @app.post("/api/knowledge/v1/docs")
    def write(request: Request) -> dict:
        context = dataset_access_context_from_request(request)
        return {
            "accepted": bool(context.permissions),
            "is_admin": context.is_admin,
            "permissions": sorted(context.permissions),
        }

    return app


def _enable_lan(monkeypatch) -> None:
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    monkeypatch.delenv("AIOPEN_ENABLE_WRITES", raising=False)
    cfg = _cfg()
    monkeypatch.setattr("app.security.lan_cidr_guard.get_lan_config", lambda: cfg)
    monkeypatch.setattr("app.security.license_guard.get_lan_config", lambda: cfg)
    AIOPEN_STATE["runtime_keys"] = {}
    AIOPEN_STATE["whitelist"]["/api/knowledge"] = True


def _invoke(client: TestClient, key: str, tool: str, args: dict) -> dict:
    response = client.post(
        "/api/aiopen/invoke",
        headers={"X-AIOPEN-Key": key},
        json={"tool": tool, "args": args},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_same_tenant_runtime_key_reads_knowledge_through_lan(monkeypatch) -> None:
    _enable_lan(monkeypatch)
    key = generate_api_key("tenant-read", principal=_OWNER)["key"]
    client = TestClient(_app(), client=("8.8.8.8", 9))

    health = _invoke(client, key, "api_call", {"path": "/api/knowledge/v1/health", "method": "GET"})
    assert health["status_code"] == 200
    assert health["data"]["tenant_id"] == "42"
    assert health["data"]["is_admin"] is False
    assert health["data"]["permissions"] == ["dataset.read"]
    assert health["data"].get("error") != "lan_blocked"

    own = _invoke(
        client,
        key,
        "api_call",
        {"path": "/api/knowledge/v1/datasets/42", "method": "GET"},
    )
    assert own["status_code"] == 200
    assert own["data"]["tenant_id"] == "42"

    other = _invoke(
        client,
        key,
        "api_call",
        {"path": "/api/knowledge/v1/datasets/99", "method": "GET"},
    )
    assert other["status_code"] == 403
    assert other["data"]["success"] is False
    assert "99" in other["data"]["message"]


def test_unscoped_admin_runtime_key_can_read_overview(monkeypatch) -> None:
    _enable_lan(monkeypatch)
    key = generate_api_key("面板")["key"]
    client = TestClient(_app(), client=("8.8.8.8", 9))
    health = _invoke(client, key, "api_call", {"path": "/api/knowledge/v1/health", "method": "GET"})
    assert health["status_code"] == 200
    assert health["data"]["is_admin"] is True
    assert "dataset.read" in health["data"]["permissions"]


def test_operation_call_uses_the_same_inprocess_gate(monkeypatch) -> None:
    _enable_lan(monkeypatch)
    app = _app()
    key = generate_api_key("tenant-read", principal=_OWNER)["key"]
    client = TestClient(app, client=("8.8.8.8", 9))
    from app.application.aiopen.catalog_builder import get_catalog

    operation_id = next(
        entry["operation_id"]
        for entry in get_catalog(app)["operations"]
        if entry.get("method") == "GET" and entry.get("path") == "/api/knowledge/v1/health"
    )
    called = _invoke(client, key, "operation_call", {"operation_id": operation_id})
    assert called["status_code"] == 200
    assert called["data"]["tenant_id"] == "42"
    assert called["data"].get("error") != "lan_blocked"


def test_direct_knowledge_stays_blocked_for_forged_headers_and_null_peer(monkeypatch) -> None:
    _enable_lan(monkeypatch)
    app = _app()
    key = generate_api_key("tenant-read", principal=_OWNER)["key"]
    public = TestClient(app, client=("8.8.8.8", 9))
    forged = public.get(
        "/api/knowledge/v1/health",
        headers={
            "X-AIOPEN-Key": key,
            "X-AIOPEN-Internal": "1",
            "X-Forwarded-For": "10.0.0.1",
            "X-Real-IP": "10.0.0.1",
            "X-Tenant-ID": "42",
        },
    )
    assert forged.status_code == 403
    body = forged.json()
    assert body["error"] == "lan_blocked"
    assert body["ip"] == "8.8.8.8"

    loopback_peer = TestClient(app)
    blocked = loopback_peer.get(
        "/api/knowledge/v1/health",
        headers={"X-AIOPEN-Internal": "1", "X-Forwarded-For": "127.0.0.1"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "lan_blocked"
    assert blocked.json()["ip"] is None


def test_unauthenticated_and_client_key_cannot_read_knowledge(monkeypatch) -> None:
    _enable_lan(monkeypatch)
    app = _app()
    client = TestClient(app, client=("8.8.8.8", 9))
    missing = client.post(
        "/api/aiopen/invoke",
        json={"tool": "api_call", "args": {"path": "/api/knowledge/v1/health", "method": "GET"}},
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "AIOPEN_KEY_INVALID"

    issued = issue_client_key(_OWNER)
    denied = client.post(
        "/api/aiopen/invoke",
        headers={"X-AIOPEN-Key": issued["key"]},
        json={"tool": "api_call", "args": {"path": "/api/knowledge/v1/health", "method": "GET"}},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "AIOPEN_SCOPE_DENIED"


def test_inprocess_write_does_not_receive_read_admin_context(monkeypatch) -> None:
    _enable_lan(monkeypatch)
    key = generate_api_key("面板")["key"]
    client = TestClient(_app(), client=("8.8.8.8", 9))
    written = _invoke(
        client,
        key,
        "api_call",
        {"path": "/api/knowledge/v1/docs", "method": "POST", "body": {"text": "x"}},
    )
    if written.get("code") == "WRITE_DISABLED":
        assert written["success"] is False
        return
    assert written["data"]["accepted"] is False
    assert written["data"]["is_admin"] is False
    assert written["data"]["permissions"] == []
