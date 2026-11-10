"""Read-only route views match actual FastAPI includes without schema construction."""

from unittest.mock import patch

from fastapi import APIRouter, FastAPI, WebSocket

from app.legacy.routes.openapi_route_compat import (
    iter_effective_routes,
    remove_superseded_host_aliases,
)
from tests.route_metadata import iter_route_metadata


def signature(routes):
    return [(r.path, r.methods, r.endpoint, r.include_in_schema, r.name, r.tags) for r in routes]


def metadata_without_validation(app):
    with (
        patch(
            "fastapi.routing._populate_api_route_state",
            side_effect=AssertionError("metadata must not rebuild HTTP validation"),
        ),
        patch(
            "fastapi._compat.v2.ModelField.__post_init__",
            side_effect=AssertionError("metadata must not construct any parameter validator"),
        ),
    ):
        return list(iter_route_metadata(app.routes))


def test_nested_include_mount_tags_schema_and_dynamic_version():
    child = APIRouter()

    @child.post("/item", tags=["leaf"])
    def item(body: dict):
        return body

    parent = APIRouter()
    parent.include_router(child, prefix="/child", tags=["parent"], include_in_schema=False)
    sub = FastAPI()
    sub.include_router(parent, prefix="/v1", tags=["outer"])
    app = FastAPI()
    app.mount("/mounted", sub)
    before = metadata_without_validation(app)
    assert signature(before) == signature(iter_effective_routes(app.routes))
    route = next(r for r in before if r.path.endswith("/item"))
    assert route.path == "/mounted/v1/child/item"
    assert route.tags == ["outer", "parent", "leaf"]
    assert route.include_in_schema is False
    assert signature(metadata_without_validation(app)) == signature(before)

    @child.get("/later")
    def later():
        return {}

    updated = metadata_without_validation(app)
    assert any(r.path == "/mounted/v1/child/later" for r in updated)
    assert signature(updated) == signature(iter_effective_routes(app.routes))


def test_app_local_alias_removal_does_not_reappear_in_metadata_or_affect_another_app():
    host = APIRouter()

    @host.get("/resource")
    def inventory_host_alias():
        return {"source": "host"}

    parent = APIRouter()
    parent.include_router(host, prefix="/module")
    app = FastAPI()
    app.include_router(parent, prefix="/api")
    before = list(iter_effective_routes(app.routes))
    replacement = APIRouter()

    @replacement.get("/resource")
    def mod_route():
        return {"source": "mod"}

    app.include_router(replacement, prefix="/api/module")
    assert remove_superseded_host_aliases(app, before) == ["/api/module/resource"]
    result = metadata_without_validation(app)
    assert signature(result) == signature(iter_effective_routes(app.routes))
    assert [r.endpoint for r in result if r.path == "/api/module/resource"] == [mod_route]
    other = FastAPI()
    other.include_router(parent, prefix="/api")
    other_result = metadata_without_validation(other)
    assert [r.endpoint for r in other_result if r.path == "/api/module/resource"] == [
        inventory_host_alias
    ]
    assert signature(other_result) == signature(iter_effective_routes(other.routes))


def test_included_mount_and_websocket_preserve_materializer_context_semantics():
    sub = FastAPI()

    @sub.get("/leaf")
    def leaf():
        return {}

    router = APIRouter()
    router.mount("/inner", sub)

    @router.websocket("/ws/{room}")
    async def websocket(socket: WebSocket, room: int, query: str = ""):
        pass

    app = FastAPI()
    app.include_router(router, prefix="/api", tags=["included"], include_in_schema=False)
    cold = metadata_without_validation(app)
    actual = list(iter_effective_routes(app.routes))
    assert signature(cold) == signature(actual)
    assert signature(metadata_without_validation(app)) == signature(actual)
    assert [r.path for r in cold[-2:]] == ["", ""]


def test_full_legacy_stack_cold_and_warm_match_materializer(monkeypatch):
    from app.legacy.routes.legacy_compat import register_legacy_compat_routes

    monkeypatch.delenv("XCAGI_REGISTER_LEGACY_ROUTES", raising=False)
    with patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"):
        app = FastAPI()
        register_legacy_compat_routes(app)
    cold = metadata_without_validation(app)
    actual = list(iter_effective_routes(app.routes))
    assert len(actual) >= 50
    assert signature(cold) == signature(actual)
    assert signature(metadata_without_validation(app)) == signature(actual)
