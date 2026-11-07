"""Route registry integrity tests."""

from __future__ import annotations

import os

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import register_all_routes
from app.fastapi_routes.registry import RouteMount, RouteRegistry, detect_app_route_conflicts
from app.legacy.routes.openapi_route_compat import iter_effective_routes


@pytest.fixture
def app() -> FastAPI:
    os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")
    application = FastAPI()
    register_all_routes(application)
    return application


def test_no_duplicate_registry_mount_names():
    registry = RouteRegistry()
    from app.fastapi_routes.mounts.business import register_business_routes

    register_business_routes(FastAPI(), registry)
    names = registry.names()
    assert len(names) == len(set(names))


def test_auth_session_validate_not_fallback(app: FastAPI):
    paths = [route.path for route in iter_effective_routes(app.routes) if route.path]
    assert "/api/auth/session/validate" in paths or any("session/validate" in p for p in paths)


def test_registry_detect_conflicts_empty_for_unique_routers():
    registry = RouteRegistry()
    from fastapi import APIRouter

    r1 = APIRouter()

    @r1.get("/api/foo")
    def foo():
        return {"success": True}

    registry.register_router("a", r1, priority=1)
    assert registry.detect_conflicts() == []


def test_health_routes_registered(app: FastAPI):
    paths = {route.path for route in iter_effective_routes(app.routes)}
    assert "/api/health" in paths
    assert "/api/ping" in paths


def test_registry_uses_effective_prefixes_and_nested_includes():
    child = APIRouter()
    child.add_api_route("/probe", lambda: {"ok": True}, methods=["GET"])
    parent = APIRouter()
    parent.include_router(child, prefix="/nested")
    registry = RouteRegistry()
    registry.register_router("first", parent, prefix="/first")
    registry.register_router("second", parent, prefix="/second")
    assert registry.detect_conflicts() == []
    app = FastAPI()
    registry.apply(app)
    with TestClient(app) as client:
        assert client.get("/first/nested/probe").json() == {"ok": True}
        assert client.get("/second/nested/probe").json() == {"ok": True}
    direct = APIRouter()
    direct.add_api_route("/first/nested/probe", lambda: None, methods=["GET"])
    registry.register_router("duplicate", direct)
    (conflict,) = registry.detect_conflicts()
    assert (conflict.method, conflict.path) == ("GET", "/first/nested/probe")
    assert set(conflict.mounts) == {"first", "duplicate"}


def test_registry_include_kwargs_prefix_overrides_mount_prefix_like_apply():
    router = APIRouter()
    router.add_api_route("/probe", lambda: None, methods=["GET"])
    registry = RouteRegistry()
    registry.register(
        RouteMount("override", router, prefix="/unused", include_kwargs={"prefix": "/actual"})
    )
    registry.register_router("duplicate", router, prefix="/actual")
    (conflict,) = registry.detect_conflicts()
    assert conflict.path == "/actual/probe"


@pytest.mark.parametrize(
    "parameter, expected",
    [("{filename:path}", True), ("{item_id}", True), ("{item_id:int}", False)],
)
def test_registry_reports_static_shadow_in_dispatch_order(parameter, expected):
    dynamic = APIRouter()
    dynamic.add_api_route(f"/print/{parameter}", lambda: {"route": "dynamic"}, methods=["POST"])
    fixed = APIRouter()
    fixed.add_api_route("/print/label", lambda: {"route": "fixed"}, methods=["POST"])
    registry = RouteRegistry()
    # Deliberately register in reverse: apply sorts by priority.
    registry.register_router("fixed", fixed, priority=20, prefix="/api")
    registry.register_router("dynamic", dynamic, priority=10, prefix="/api")
    conflicts = registry.detect_conflicts()
    assert bool(conflicts) is expected
    if expected:
        assert conflicts[0].kind == "shadow"
        assert conflicts[0].path == "/api/print/label"
        assert conflicts[0].mounts == ["dynamic", "fixed"]
    app = FastAPI()
    registry.apply(app)
    with TestClient(app) as client:
        assert client.post("/api/print/label").json()["route"] == (
            "dynamic" if expected else "fixed"
        )


def test_full_app_conflicts_include_routes_added_after_registry():
    router = APIRouter()
    router.add_api_route("/api/probe", lambda: None, methods=["GET"])
    app = FastAPI()
    registry = RouteRegistry()
    registry.register_router("host", router)
    registry.apply(app)
    app.include_router(router)  # A later legacy/Mod registration.
    assert registry.detect_conflicts() == []
    assert [(c.method, c.path) for c in detect_app_route_conflicts(app)] == [("GET", "/api/probe")]


def test_shadow_check_preserves_methods_and_static_first_routes():
    router = APIRouter()
    router.add_api_route("/api/items/export", lambda: None, methods=["GET"])
    router.add_api_route("/api/items/{item_id}", lambda: None, methods=["GET"])
    router.add_api_route("/api/items/preview", lambda: None, methods=["POST"])
    registry = RouteRegistry()
    registry.register_router("items", router)
    assert registry.detect_conflicts() == []


def test_registry_preserves_root_slash_under_mount_prefix():
    slash = APIRouter()
    slash.add_api_route("/", lambda: "slash")
    plain = APIRouter()
    plain.add_api_route("/api", lambda: "plain")
    registry = RouteRegistry()
    registry.register_router("slash", slash, prefix="/api")
    registry.register_router("plain", plain)
    app = FastAPI()
    registry.apply(app)
    assert registry.detect_conflicts() == detect_app_route_conflicts(app) == []
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/api/").json() == "slash"
        assert client.get("/api").json() == "plain"


def test_deferred_diagnostics_run_after_spa_reorder(monkeypatch, caplog):
    import app.fastapi_routes as routes
    from app.fastapi_routes.spa_fallback import register_spa_history_fallback

    application = FastAPI()
    register_spa_history_fallback(application)
    child = APIRouter()
    child.add_api_route("/api/late", lambda: {"ok": True})
    monkeypatch.setattr(
        routes,
        "register_business_routes",
        lambda app, registry: registry.register_router("late", child),
    )
    for stage in (
        "_register_platform_shell_bootstrap",
        "register_neuro_routes",
        "register_neuro_migration_routes",
        "register_lan_routes",
        "register_essential_compat_routes",
        "register_legacy_compat_routes",
    ):
        monkeypatch.setattr(routes, stage, lambda app: None)
    routes.register_deferred_routes(application)
    assert "Route shadow:" not in caplog.text
    with TestClient(application) as client:
        assert client.get("/api/late").json() == {"ok": True}


def test_asgi_mount_claims_even_missing_child_paths_and_other_methods():
    child = FastAPI()
    child.add_api_route("/present", lambda: "child")
    app = FastAPI()
    app.mount("/plugins", child)
    app.add_api_route("/plugins/missing", lambda: "unreachable", methods=["GET", "POST"])
    conflicts = detect_app_route_conflicts(app)
    assert {(c.method, c.path, c.shadowed_by) for c in conflicts} == {
        ("GET", "/plugins/missing", "/plugins"),
        ("POST", "/plugins/missing", "/plugins"),
    }
    with TestClient(app) as client:
        assert client.get("/plugins/present").json() == "child"
        assert client.get("/plugins/missing").status_code == 404
        assert client.post("/plugins/missing").status_code == 404
