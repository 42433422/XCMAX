"""Tests for app.fastapi_routes.mounts.legacy_compat — register_legacy_compat_routes."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.fastapi_routes.mounts.legacy_compat import register_legacy_compat_routes
from app.fastapi_routes.openapi_route_compat import iter_effective_routes


@pytest.fixture
def fresh_app():
    """Create a fresh FastAPI app for each test."""
    return FastAPI()


class TestRegisterLegacyCompatRoutes:
    """Test that register_legacy_compat_routes mounts all expected routers."""

    def test_registers_market_account(self, fresh_app):
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch(
                "app.fastapi_routes.mounts.legacy_compat.is_ci_strict",
                return_value=False,
            ),
        ):
            register_legacy_compat_routes(fresh_app)
        routes = [r.path for r in iter_effective_routes(fresh_app.routes)]
        assert len(routes) > 0

    def test_registers_without_legacy_gap_by_default(self, fresh_app):
        with (
            patch(
                "app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"
            ) as mock_gap,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_not_called()

    def test_registers_with_legacy_gap_when_env_set_true(self, fresh_app):
        with (
            patch(
                "app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"
            ) as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "1"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_called_once_with(fresh_app)

    def test_registers_with_legacy_gap_when_env_set_yes(self, fresh_app):
        with (
            patch(
                "app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"
            ) as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "yes"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_called_once_with(fresh_app)

    def test_registers_with_legacy_gap_when_env_set_on(self, fresh_app):
        with (
            patch(
                "app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"
            ) as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "on"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_called_once_with(fresh_app)

    def test_does_not_register_legacy_gap_when_env_set_false(self, fresh_app):
        with (
            patch(
                "app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"
            ) as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "false"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_not_called()

    def test_system_router_import_error_handled(self, fresh_app):
        """When system_routes import fails, it should log a warning, not crash."""
        with patch.dict(sys.modules, {"app.fastapi_routes.system_routes": None}):
            # Setting module to None forces ImportError on import
            register_legacy_compat_routes(fresh_app)

    def test_private_db_read_assistant_recoverable_error(self, fresh_app):
        """When private_db_read_assistant raises a recoverable error, it should be skipped."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(
                sys.modules, {"app.fastapi_routes.private_db_read_assistant_compat": None}
            ):
                register_legacy_compat_routes(fresh_app)

    def test_user_cs_wechat_passive_recoverable_error(self, fresh_app):
        """When user_cs_wechat_passive raises a recoverable error, it should be skipped."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(
                sys.modules, {"app.fastapi_routes.user_cs_wechat_passive_compat": None}
            ):
                register_legacy_compat_routes(fresh_app)

    def test_wechat_decrypt_recoverable_error(self, fresh_app):
        """When wechat_decrypt_routes import fails, it should be skipped."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(sys.modules, {"app.fastapi_routes.wechat_decrypt_routes": None}):
                register_legacy_compat_routes(fresh_app)

    def test_model_payment_recoverable_error(self, fresh_app):
        """When model_payment import fails, it should be skipped."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            # model_payment is already imported at module level in legacy_compat,
            # but the try/except in the function should catch ImportError
            # We need to remove it from sys.modules to force re-import
            saved = sys.modules.pop("app.fastapi_routes.model_payment", None)
            try:
                with patch.dict(sys.modules, {"app.fastapi_routes.model_payment": None}):
                    register_legacy_compat_routes(fresh_app)
            finally:
                if saved is not None:
                    sys.modules["app.fastapi_routes.model_payment"] = saved

    def test_contract_lifecycle_import_error(self, fresh_app):
        """When contract_lifecycle_api import fails, it should be skipped."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(sys.modules, {"app.fastapi_routes.contract_lifecycle_api": None}):
                register_legacy_compat_routes(fresh_app)

    def test_service_bridge_ci_strict_raises(self, fresh_app):
        """When CI is strict and service_bridge fails, it should raise RuntimeError."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with (
                patch(
                    "app.fastapi_routes.mounts.legacy_compat.is_ci_strict",
                    return_value=True,
                ),
                patch.dict(sys.modules, {"app.fastapi_routes.service_bridge": None}),
                pytest.raises(RuntimeError, match="service_bridge router required in CI"),
            ):
                register_legacy_compat_routes(fresh_app)

    def test_service_bridge_non_ci_logs_warning(self, fresh_app):
        """When not in CI and service_bridge fails, it should log a warning."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with (
                patch(
                    "app.fastapi_routes.mounts.legacy_compat.is_ci_strict",
                    return_value=False,
                ),
                patch.dict(sys.modules, {"app.fastapi_routes.service_bridge": None}),
            ):
                register_legacy_compat_routes(fresh_app)

    def test_tts_install_recoverable_error(self, fresh_app):
        """When tts_install import fails, it should be skipped."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(sys.modules, {"app.fastapi_routes.tts_install": None}):
                register_legacy_compat_routes(fresh_app)

    def test_all_routers_registered(self, fresh_app):
        """Verify that many routers are registered successfully."""
        with (
            patch("app.fastapi_routes.mounts.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            register_legacy_compat_routes(fresh_app)
        route_paths = [r.path for r in iter_effective_routes(fresh_app.routes)]
        non_empty = [p for p in route_paths if p]
        assert len(non_empty) > 10
