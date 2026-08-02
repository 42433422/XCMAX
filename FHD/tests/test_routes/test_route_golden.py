"""Golden snapshot of critical route paths (edition=essential)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.fastapi_routes import register_all_routes
from app.fastapi_routes.openapi_route_compat import iter_effective_routes

GOLDEN_PATH = Path(__file__).parent / "route_golden_essential.json"

REQUIRED_PATHS = (
    "/api/health",
    "/api/ping",
    "/api/auth/session/validate",
)


@pytest.fixture
def essential_app() -> FastAPI:
    os.environ["XCAGI_SKIP_LEGACY_COMPAT_ROUTES"] = "1"
    app = FastAPI()
    register_all_routes(app)
    return app


def _collect_paths(app: FastAPI) -> list[str]:
    paths: set[str] = set()
    for route in app.routes:
        # FastAPI 0.138+ uses _IncludedRouter for include_router; the direct
        # paths live on original_router.routes.  This shallow snapshot is kept
        # for stable compatibility coverage, while nested product routers are
        # checked below through iter_effective_routes with their full prefixes.
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            for child in getattr(original_router, "routes", []):
                path = getattr(child, "path", None)
                if path:
                    paths.add(path)
        else:
            path = getattr(route, "path", None)
            if path:
                paths.add(path)
    return sorted(paths)


def test_required_paths_present(essential_app: FastAPI):
    paths = _collect_paths(essential_app)
    for required in REQUIRED_PATHS:
        assert required in paths or any(required in p for p in paths), (
            f"missing {required} in {paths[:20]}..."
        )


def test_golden_route_snapshot_essential(essential_app: FastAPI):
    paths = _collect_paths(essential_app)
    assert len(paths) >= len(REQUIRED_PATHS)
    if GOLDEN_PATH.exists():
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        assert paths == expected


def test_private_delivery_routes_are_exposed(essential_app: FastAPI):
    paths = {route.path for route in iter_effective_routes(essential_app.routes) if route.path}
    assert {
        "/api/mod-store/private-delivery",
        "/api/mod-store/private-delivery/requests",
        "/api/mod-store/private-delivery/requests/{ticket_id}/decision",
        "/api/mod-store/private-delivery/requests/{ticket_id}/install",
        "/api/mod-store/private-delivery/status",
        "/api/mod-store/private-mod/update",
    } <= paths
