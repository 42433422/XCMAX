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
    # FastAPI 0.138+ 用 _IncludedRouter 包装 include_router 的路由，
    # 实际路径在 original_router.routes 中；旧版直接展开为 Route。
    paths: list[str] = []
    for r in app.routes:
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                p = getattr(sub, "path", None)
                if p:
                    paths.append(p)
        else:
            p = getattr(r, "path", None)
            if p:
                paths.append(p)
    assert paths.index("/high") < paths.index("/low")
