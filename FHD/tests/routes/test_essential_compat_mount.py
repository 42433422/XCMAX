"""mounts/essential_compat — tools/execute always-on mount."""

from __future__ import annotations

from fastapi import FastAPI

from app.fastapi_routes.mounts.essential_compat import register_essential_compat_routes
from app.fastapi_routes.openapi_route_compat import iter_effective_routes


def test_register_essential_compat_routes_mounts_tools_execute() -> None:
    app = FastAPI()
    register_essential_compat_routes(app)

    route_methods = {
        (getattr(route, "path", ""), method)
        for route in iter_effective_routes(app.routes)
        for method in (getattr(route, "methods", None) or set())
    }
    assert ("/api/tools/execute", "POST") in route_methods
