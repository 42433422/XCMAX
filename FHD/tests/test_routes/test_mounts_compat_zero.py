"""Tests for app.fastapi_routes.mounts.compat."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.fastapi_routes.mounts.compat import register_compat_routes


class TestRegisterCompatRoutes:
    """Tests for register_compat_routes."""

    @patch("app.fastapi_routes.mounts.compat.register_essential_compat_routes")
    def test_essential_only(self, mock_essential: MagicMock) -> None:
        app = FastAPI()
        register_compat_routes(app, essential_only=True)
        mock_essential.assert_called_once_with(app)

    @patch("app.fastapi_routes.mounts.compat.register_legacy_compat_routes")
    @patch("app.fastapi_routes.mounts.compat.register_essential_compat_routes")
    def test_full_legacy_stack(self, mock_essential: MagicMock, mock_legacy: MagicMock) -> None:
        app = FastAPI()
        register_compat_routes(app, essential_only=False)
        mock_legacy.assert_called_once_with(app)

    @patch("app.fastapi_routes.mounts.compat.register_legacy_compat_routes")
    def test_default_is_full_stack(self, mock_legacy: MagicMock) -> None:
        app = FastAPI()
        register_compat_routes(app)
        mock_legacy.assert_called_once_with(app)
