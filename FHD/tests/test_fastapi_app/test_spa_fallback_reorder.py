"""Regression: deferred routes must not stay behind SPA GET catch-all."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_ensure_spa_fallback_last_unmasks_deferred_get():
    from app.fastapi_routes.spa_fallback import (
        ensure_spa_fallback_last,
        register_spa_history_fallback,
    )

    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "healthy"}

    register_spa_history_fallback(app)

    @app.get("/api/platform-shell/deliverable-status")
    def deliverable():
        return {"success": True, "data": {"deliverable": True}}

    # Mimic bug: deferred route registered after SPA → GET shadowed.
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        shadowed = client.get("/api/platform-shell/deliverable-status")
        assert shadowed.status_code == 404
        assert "资源不存在" in shadowed.json().get("message", "")

    ensure_spa_fallback_last(app)

    with TestClient(app) as client:
        ok = client.get("/api/platform-shell/deliverable-status")
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["deliverable"] is True


@pytest.mark.asyncio
async def test_deferred_route_registration_reorders_spa(monkeypatch):
    from app.fastapi_app import deferred_startup as mod
    from app.fastapi_routes.spa_fallback import register_spa_history_fallback

    app = FastAPI()
    app.state.deferred_routes_pending = True
    register_spa_history_fallback(app)

    def fake_register(app_):
        @app_.get("/api/mods")
        def mods():
            return {"ok": True}

    monkeypatch.setattr(mod, "register_deferred_routes", fake_register, raising=False)
    # Patch the import target used inside the coroutine.
    import app.fastapi_routes as routes_pkg

    monkeypatch.setattr(routes_pkg, "register_deferred_routes", fake_register)

    await mod._deferred_route_registration(app)
    assert app.state.deferred_routes_pending is False

    with TestClient(app) as client:
        resp = client.get("/api/mods")
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True
