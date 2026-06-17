"""Tests for app.fastapi_routes.mounts.compat."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.fastapi_routes.mounts.compat import register_compat_routes


class TestRegisterCompatRoutes:
    @patch("app.fastapi_routes.mounts.compat.register_essential_compat_routes")
    def test_essential_only(self, mock_essential):
        app = MagicMock()
        register_compat_routes(app, essential_only=True)
        mock_essential.assert_called_once_with(app)

    @patch("app.fastapi_routes.mounts.compat.register_legacy_compat_routes")
    @patch("app.fastapi_routes.mounts.compat.register_essential_compat_routes")
    def test_full_legacy(self, mock_essential, mock_legacy):
        app = MagicMock()
        register_compat_routes(app, essential_only=False)
        mock_legacy.assert_called_once_with(app)
        mock_essential.assert_not_called()

    @patch("app.fastapi_routes.mounts.compat.register_legacy_compat_routes")
    def test_default_is_full_legacy(self, mock_legacy):
        app = MagicMock()
        register_compat_routes(app)
        mock_legacy.assert_called_once_with(app)
