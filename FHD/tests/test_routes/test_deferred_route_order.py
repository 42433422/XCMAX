from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def _stub_deferred_mounts(monkeypatch, route_module) -> None:
    def register_business(_app, registry):
        router = APIRouter()

        @router.get("/api/auth/session/validate")
        def validate_session():
            return {"success": True, "valid": True}

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


def test_fast_start_appends_spa_fallback_after_live_deferred_routes(monkeypatch, tmp_path):
    import app.fastapi_routes as route_module
    from app.fastapi_routes import spa_fallback

    vue = tmp_path / "vue-dist"
    vue.mkdir()
    (vue / "index.html").write_text("<html>ready</html>")
    monkeypatch.setattr(spa_fallback, "_vue_dist_dir", lambda: str(vue))
    app = FastAPI()
    spa_fallback.register_spa_root(app)
    _stub_deferred_mounts(monkeypatch, route_module)

    assert not any(getattr(route, "path", "") == "/{fallback:path}" for route in app.router.routes)

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/some-vue-route").status_code == 404

        route_module.register_deferred_routes(app)

        assert getattr(app.router.routes[-1], "path", "") == "/{fallback:path}"
        response = client.get("/api/auth/session/validate")
        assert response.status_code == 200
        assert response.json() == {"success": True, "valid": True}
        assert client.get("/some-vue-route").status_code == 200


def test_deferred_routes_keep_existing_spa_fallback_last(monkeypatch):
    import app.fastapi_routes as route_module
    from app.fastapi_routes.spa_fallback import register_spa_history_fallback

    app = FastAPI()
    register_spa_history_fallback(app)
    _stub_deferred_mounts(monkeypatch, route_module)
    route_module.register_deferred_routes(app)

    fallback_routes = [
        route for route in app.router.routes if getattr(route, "path", "") == "/{fallback:path}"
    ]
    assert len(fallback_routes) == 1
    assert getattr(app.router.routes[-1], "path", "") == "/{fallback:path}"
    response = TestClient(app).get("/api/auth/session/validate")
    assert response.status_code == 200
    assert response.json() == {"success": True, "valid": True}


def test_register_all_routes_leaves_spa_fallback_to_factory(monkeypatch):
    import app.fastapi_routes as route_module

    app = FastAPI()
    _stub_deferred_mounts(monkeypatch, route_module)
    monkeypatch.setattr(route_module, "register_bootstrap_routes", lambda _app: None)

    route_module.register_all_routes(app)

    route_paths = [getattr(route, "path", "") for route in app.router.routes]
    assert "/{fallback:path}" not in route_paths
    response = TestClient(app).get("/api/auth/session/validate")
    assert response.status_code == 200
    assert response.json() == {"success": True, "valid": True}
