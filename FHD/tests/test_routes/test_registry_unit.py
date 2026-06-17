"""Tests for RouteRegistry."""

from fastapi import APIRouter

from app.fastapi_routes.registry import RouteRegistry


def test_register_deduplicates_by_name():
    registry = RouteRegistry()
    router = APIRouter()

    @router.get("/a")
    def _a():
        return {}

    registry.register_router("x", router)
    registry.register_router("x", router)
    assert len(registry.names()) == 1


def test_apply_sorts_by_priority():
    registry = RouteRegistry()
    r1, r2 = APIRouter(), APIRouter()

    @r1.get("/low")
    def _low():
        return {}

    @r2.get("/high")
    def _high():
        return {}

    registry.register_router("low", r1, priority=100)
    registry.register_router("high", r2, priority=1)
    from fastapi import FastAPI

    app = FastAPI()
    included_paths: list[list[str]] = []
    original_include_router = app.include_router

    def record_include_router(router: APIRouter, **kwargs):
        included_paths.append([getattr(route, "path", "") for route in router.routes])
        return original_include_router(router, **kwargs)

    app.include_router = record_include_router
    registry.apply(app)
    assert included_paths == [["/high"], ["/low"]]
