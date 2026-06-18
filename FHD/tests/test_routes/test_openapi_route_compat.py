"""Tests for app.fastapi_routes.openapi_route_compat."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.openapi_route_compat import (
    hide_trailing_slash_openapi_duplicates,
    include_router_with_slash_compat,
)


class TestHideTrailingSlashOpenapiDuplicates:
    def test_no_routes_returns_zero(self):
        app = MagicMock()
        app.routes = []
        result = hide_trailing_slash_openapi_duplicates(app)
        assert result == 0

    def test_non_api_routes_skipped(self):
        app = MagicMock()
        app.routes = [MagicMock()]
        # Not an APIRoute instance, should be skipped
        with patch(
            "app.utils.openapi_path.normalize_path_template",
            side_effect=lambda x: x.rstrip("/"),
        ):
            result = hide_trailing_slash_openapi_duplicates(app)
            assert result == 0


class TestIncludeRouterWithSlashCompat:
    def test_includes_router(self):
        app = MagicMock()
        router = MagicMock()
        include_router_with_slash_compat(app, router, hide_slash_in_schema=False)
        app.include_router.assert_called_once_with(router)

    def test_hides_slash_duplicates_by_default(self):
        app = MagicMock()
        router = MagicMock()
        with patch(
            "app.fastapi_routes.openapi_route_compat.hide_trailing_slash_openapi_duplicates",
            return_value=0,
        ) as mock_hide:
            include_router_with_slash_compat(app, router)
            mock_hide.assert_called_once_with(app)

    def test_extra_kwargs_passed(self):
        app = MagicMock()
        router = MagicMock()
        include_router_with_slash_compat(app, router, prefix="/api", hide_slash_in_schema=False)
        app.include_router.assert_called_once_with(router, prefix="/api")
