"""Global database mode changes require a live administrator session."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models.user import User
from app.fastapi_routes.domains.misc.misc_routes import router
from app.infrastructure.db import sync_engine
from app.middleware.csrf import CSRFMiddleware
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture(params=["enable", "enable/", "disable", "disable/"])
def test_db_http(request, trusted_actor, tmp_path, monkeypatch):
    actors = {
        "admin": trusted_actor(role="admin", tier="admin", tenant_id=None),
        "viewer": trusted_actor(role="viewer"),
        "disabled": trusted_actor(role="admin", tier="admin", tenant_id=None),
    }
    with actors["disabled"].factory.begin() as db:
        db.get(User, actors["disabled"].user_id).is_active = False
    target_mode = "test" if request.param.startswith("enable") else "production"
    initial_mode = "production" if target_mode == "test" else "test"
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    monkeypatch.setattr(sync_engine, "_mode", initial_mode)
    monkeypatch.setattr(sync_engine, "_engine", object())
    monkeypatch.setattr(sync_engine, "_bound_engine_url", "test-only-cached-engine")
    monkeypatch.setattr(
        sync_engine.mod_database_gate, "mod_db_gate_state", lambda: {"gate_open": True}
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        client.get("/api/system/test-db/status")
        client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
        yield client, f"/api/system/test-db/{request.param}", actors, target_mode


@pytest.mark.parametrize(
    ("actor", "expected_status"),
    [("anonymous", 401), ("forged", 401), ("viewer", 403), ("disabled", 403)],
)
def test_denied_caller_cannot_change_database_mode(test_db_http, actor, expected_status):
    client, path, actors, _ = test_db_http
    before = (sync_engine.resolve_mode(), sync_engine._engine, sync_engine._bound_engine_url)
    database_url = sync_engine.get_database_url()
    headers = actors[actor].headers if actor in actors else {}
    if actor == "forged":
        headers = {"X-User-ID": str(actors["admin"].user_id), "X-Session-ID": "invalid-session"}

    response = client.post(path, json={"enabled": True}, headers=headers)

    assert response.status_code == expected_status, response.text
    assert (
        sync_engine.resolve_mode(),
        sync_engine._engine,
        sync_engine._bound_engine_url,
    ) == before
    assert sync_engine.get_database_url() == database_url


def test_live_admin_can_change_database_mode(test_db_http):
    client, path, actors, target_mode = test_db_http

    response = client.post(path, json={"enabled": True}, headers=actors["admin"].headers)

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert response.json()["data"]["test_mode"] is (target_mode == "test")
    assert sync_engine.resolve_mode() == target_mode
    assert sync_engine._engine is None
    assert sync_engine._bound_engine_url is None
    expected_file = "products_test.db" if target_mode == "test" else "products.db"
    assert sync_engine.get_database_url().endswith("/" + expected_file)
