from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def test_deferred_routes_are_moved_before_spa_fallback(monkeypatch):
    import app.fastapi_routes as route_module
    from app.fastapi_routes.spa_fallback import register_spa_history_fallback

    app = FastAPI()
    register_spa_history_fallback(app)

    def register_business(_app, registry):
        router = APIRouter()

        @router.get("/api/deferred-probe")
        def probe():
            return {"ok": True}

        registry.register_router("probe", router, priority=1)

    monkeypatch.setattr(route_module, "register_business_routes", register_business)
    for name in (
        "register_neuro_routes",
        "register_neuro_migration_routes",
        "register_lan_routes",
        "register_essential_compat_routes",
        "register_legacy_compat_routes",
    ):
        monkeypatch.setattr(route_module, name, lambda _app: None)
    monkeypatch.setenv("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

    route_module.register_deferred_routes(app)
    assert getattr(app.router.routes[-1], "path", "") == "/{fallback:path}"
    response = TestClient(app).get("/api/deferred-probe")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
