"""Tests for app.fastapi_routes.xcagi_compat — coverage ramp C3.3-a.

Covers the aggregated compat router and ``_register_router_events`` log path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.openapi_route_compat import iter_effective_routes
from app.fastapi_routes.xcagi_compat import router


def _collect_paths(app: FastAPI) -> list[str]:
    paths: set[str] = set()

    def _walk(routes):
        for route in routes:
            # FastAPI 0.138+ 用 _IncludedRouter 包装 include_router 的路由，
            # 实际路径在 original_router.routes 中；旧版直接展开为 Route。
            orig = getattr(route, "original_router", None)
            if orig is not None:
                _walk(getattr(orig, "routes", []))
            else:
                path = getattr(route, "path", None)
                if path:
                    paths.add(path)

    _walk(app.routes)
    return sorted(paths)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRouterEvents:
    def test_register_logs_subscribers(self) -> None:
        with patch("app.fastapi_routes.xcagi_compat.get_neuro_bus") as g:
            bus = MagicMock()
            bus.subscribers = {"a": 1, "b": 2}
            g.return_value = bus
            # Re-invoke the function under test
            from app.fastapi_routes.xcagi_compat import _register_router_events

            _register_router_events()
        g.assert_called_once()

    def test_register_handles_exception(self) -> None:
        with patch(
            "app.fastapi_routes.xcagi_compat.get_neuro_bus", side_effect=Exception("no bus")
        ):
            from app.fastapi_routes.xcagi_compat import _register_router_events

            # Should not raise
            _register_router_events()


class TestRouterAggregation:
    def test_includes_subrouters(self, client: TestClient) -> None:
        # The aggregated router should have at least the legacy endpoints
        routes = _collect_paths(client.app)
        # Loose assertion: at least one route under /api/...
        assert any(p.startswith("/api/") for p in routes) or any(
            "compat" in p or "v1" in p or "v2" in p for p in routes
        )
