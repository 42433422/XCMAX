"""Route registry integrity tests."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI

from app.fastapi_routes import register_all_routes
from app.fastapi_routes.registry import RouteRegistry


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
    paths = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.append(path)
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
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/health" in paths
    assert "/api/ping" in paths
