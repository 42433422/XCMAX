"""Tests for app.legacy.routes.openapi_route_compat."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.legacy.routes.openapi_route_compat import (
    hide_trailing_slash_openapi_duplicates,
    include_router_with_slash_compat,
    iter_effective_routes,
    remove_superseded_host_aliases,
)


class TestHideTrailingSlashOpenapiDuplicates:
    """Tests for hide_trailing_slash_openapi_duplicates."""

    def test_no_duplicates_returns_zero(self) -> None:
        app = FastAPI()

        @app.get("/api/test")
        def test_endpoint() -> dict[str, str]:
            return {"ok": "true"}

        result = hide_trailing_slash_openapi_duplicates(app)
        assert result == 0

    def test_hides_trailing_slash_duplicates(self) -> None:
        app = FastAPI()

        @app.get("/api/test")
        @app.get("/api/test/")
        def test_endpoint() -> dict[str, str]:
            return {"ok": "true"}

        result = hide_trailing_slash_openapi_duplicates(app)
        assert result >= 1

    def test_root_path_not_hidden(self) -> None:
        app = FastAPI()

        @app.get("/")
        def root() -> dict[str, str]:
            return {"ok": "true"}

        result = hide_trailing_slash_openapi_duplicates(app)
        assert result == 0

    def test_different_handlers_not_hidden(self) -> None:
        app = FastAPI()

        @app.get("/api/test")
        def handler_a() -> dict[str, str]:
            return {"a": "1"}

        @app.get("/api/test/")
        def handler_b() -> dict[str, str]:
            return {"b": "2"}

        result = hide_trailing_slash_openapi_duplicates(app)
        # Different qualnames, so should not hide
        assert result == 0


class TestIncludeRouterWithSlashCompat:
    """Tests for include_router_with_slash_compat."""

    def test_includes_router(self) -> None:
        from fastapi import APIRouter

        app = FastAPI()
        router = APIRouter()

        @router.get("/hello")
        def hello() -> dict[str, str]:
            return {"hello": "world"}

        include_router_with_slash_compat(app, router)
        # Verify the route was included
        routes = [r.path for r in iter_effective_routes(app.routes)]
        assert "/hello" in routes

    def test_includes_router_without_hiding(self) -> None:
        from fastapi import APIRouter

        app = FastAPI()
        router = APIRouter()

        @router.get("/simple")
        def simple() -> dict[str, str]:
            return {"simple": "true"}

        include_router_with_slash_compat(app, router, hide_slash_in_schema=False)
        routes = [r.path for r in iter_effective_routes(app.routes)]
        assert "/simple" in routes


def test_remove_superseded_host_aliases_from_nested_lazy_router() -> None:
    from fastapi import APIRouter

    app = FastAPI()
    nested = APIRouter()

    @nested.get("/resource")
    @nested.get("/resource/", include_in_schema=False)
    def inventory_host_alias() -> dict[str, str]:
        return {"source": "host"}

    parent = APIRouter()
    parent.include_router(nested, prefix="/mod/example")
    app.include_router(parent, prefix="/api")
    routes_before = list(iter_effective_routes(app.routes))

    mod_router = APIRouter()

    @mod_router.get("/resource")
    @mod_router.get("/resource/", include_in_schema=False)
    def inventory_mod_route() -> dict[str, str]:
        return {"source": "mod"}

    app.include_router(mod_router, prefix="/api/mod/example")
    removed = remove_superseded_host_aliases(app, routes_before)

    matching = [
        route
        for route in iter_effective_routes(app.routes)
        if route.path.rstrip("/") == "/api/mod/example/resource"
    ]
    assert removed == ["/api/mod/example/resource", "/api/mod/example/resource/"]
    assert {route.endpoint.__name__ for route in matching} == {"inventory_mod_route"}

    second_app = FastAPI()
    second_app.include_router(parent, prefix="/api")
    second_matching = [
        route
        for route in iter_effective_routes(second_app.routes)
        if route.path.rstrip("/") == "/api/mod/example/resource"
    ]
    assert {route.endpoint.__name__ for route in second_matching} == {"inventory_host_alias"}
