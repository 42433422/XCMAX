"""Admin/write endpoints require real credentials; a forged bearer no longer skips CSRF."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.application.auth import AuthApplicationService, AuthenticationError

ADMIN = {"Authorization": "Bearer admin-token"}
MEMBER = {"Authorization": "Bearer member-token"}


@pytest.fixture(autouse=True)
def _fake_tokens(monkeypatch):
    users = {
        "Bearer admin-token": SimpleNamespace(id=7, is_admin=True),
        "Bearer member-token": SimpleNamespace(id=8, is_admin=False),
    }

    def _resolve(_self, authorization):
        if authorization not in users:
            raise AuthenticationError("凭证无效或已过期")
        return users[authorization]

    monkeypatch.setattr(AuthApplicationService, "current_user_from_authorization", _resolve)


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_production_line_mutations_require_admin_and_ignore_body_identity() -> None:
    from modstore_server.production_line_api import router

    client = _client(router)
    for path in ("/run", "/stop", "/steps/P1/approve", "/steps/P1/reject"):
        url = f"/api/admin/production-line{path}"
        assert client.post(url, json={}).status_code == 401
        assert client.post(url, json={}, headers={"Authorization": "Bearer x"}).status_code == 401
        assert client.post(url, json={}, headers=MEMBER).status_code == 403

    step = SimpleNamespace(step_id="P1", status=SimpleNamespace(value="approved"))
    approve = AsyncMock(return_value=step)
    with patch(
        "modstore_server.production_line_orchestrator.approve_production_line_step", approve
    ):
        r = client.post(
            "/api/admin/production-line/steps/P1/approve",
            json={"admin_user_id": 999},
            headers=ADMIN,
        )
    assert r.status_code == 200
    approve.assert_awaited_once_with("P1", admin_user_id=7)

    orch = MagicMock()
    with patch(
        "modstore_server.production_line_orchestrator.get_production_line_orchestrator",
        return_value=orch,
    ):
        assert client.post("/api/admin/production-line/stop", headers=ADMIN).status_code == 200
    orch.stop_pipeline.assert_called_once()


def test_put_config_requires_admin(monkeypatch) -> None:
    from modstore_server.api import config

    saved = []
    monkeypatch.setattr(config.library_paths, "save_config", saved.append)
    monkeypatch.setattr(config, "get_config", lambda: {"ok": True})
    client = _client(config.router)
    body = {"xcagi_backend_url": "http://attacker.invalid"}

    assert client.put("/api/config", json=body).status_code == 401
    assert client.put("/api/config", json=body, headers=MEMBER).status_code == 403
    assert saved == []
    assert client.put("/api/config", json=body, headers=ADMIN).status_code == 200
    assert saved[0].xcagi_backend_url == "http://attacker.invalid"


def test_sync_receive_requires_shared_secret(monkeypatch, tmp_path) -> None:
    from modstore_server.xcmax_admin_api import router

    monkeypatch.setenv("XCMAX_SYNC_DB_PATH", str(tmp_path / "sync.db"))
    client = _client(router)
    item = {"entity_type": "personnel", "entity_id": "1", "operation": "insert"}
    url = "/api/xcmax/sync/receive"

    monkeypatch.delenv("XCMAX_SYNC_SHARED_SECRET", raising=False)
    assert client.post(url, json=item, headers={"X-XCMAX-Sync-Token": ""}).status_code == 503

    monkeypatch.setenv("XCMAX_SYNC_SHARED_SECRET", "node-secret")
    assert client.post(url, json=item).status_code == 401
    assert client.post(url, json=item, headers={"X-XCMAX-Sync-Token": "nope"}).status_code == 401
    ok = client.post(url, json=item, headers={"X-XCMAX-Sync-Token": "node-secret"})
    assert ok.status_code == 200
    assert ok.json()["received"] == 1


def test_csrf_bearer_bypass_requires_valid_token(monkeypatch) -> None:
    from modstore_server.api.csrf import CSRFMiddleware

    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    app = FastAPI()

    @app.post("/api/write")
    def write() -> dict:
        return {"ok": True}

    app.add_middleware(CSRFMiddleware)
    client = TestClient(app)
    client.cookies.set("csrf_token", "cookie-token")

    assert client.post("/api/write", headers={"Authorization": "Bearer bogus"}).status_code == 403
    assert client.post("/api/write", headers=ADMIN).status_code == 200
    forged = {"Authorization": "Bearer bogus", "X-CSRF-Token": "cookie-token"}
    assert client.post("/api/write", headers=forged).status_code == 200

    client.cookies.clear()
    assert client.post("/api/write", headers={"Authorization": "Bearer svc"}).status_code == 200
    assert client.post("/api/write").status_code == 403
