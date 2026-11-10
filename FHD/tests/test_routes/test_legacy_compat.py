"""Tests for app.legacy.routes.legacy_compat — register_legacy_compat_routes."""

from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.legacy.routes import legacy_compat
from app.legacy.routes.legacy_compat import register_legacy_compat_routes
from scripts.route_inventory_diff import _inventory_report


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
def fresh_app():
    """Create a fresh FastAPI app for each test."""
    return FastAPI()


class TestRegisterLegacyCompatRoutes:
    """Test that register_legacy_compat_routes mounts all expected routers."""

    def test_registers_market_account(self, fresh_app):
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch(
                "app.legacy.routes.legacy_compat.is_ci_strict",
                return_value=False,
            ),
        ):
            register_legacy_compat_routes(fresh_app)
        routes = _collect_paths(fresh_app)
        assert len(routes) > 0

    def test_registers_without_legacy_gap_by_default(self, fresh_app):
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers") as mock_gap,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_not_called()

    def test_registers_with_legacy_gap_when_env_set_true(self, fresh_app):
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers") as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "1"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_called_once_with(fresh_app)

    def test_registers_with_legacy_gap_when_env_set_yes(self, fresh_app):
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers") as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "yes"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_called_once_with(fresh_app)

    def test_registers_with_legacy_gap_when_env_set_on(self, fresh_app):
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers") as mock_gap,
            patch.dict(os.environ, {"XCAGI_REGISTER_LEGACY_ROUTES": "on"}),
        ):
            register_legacy_compat_routes(fresh_app)
            mock_gap.assert_called_once_with(fresh_app)

    def test_does_not_register_legacy_gap_when_env_set_false(self, fresh_app):
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers") as mock_gap,
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
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
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
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
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
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(sys.modules, {"app.fastapi_routes.wechat_decrypt_routes": None}):
                register_legacy_compat_routes(fresh_app)

    def test_model_payment_recoverable_error(self, fresh_app):
        """When model_payment import fails, it should be skipped."""
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
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
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(sys.modules, {"app.fastapi_routes.contract_lifecycle_api": None}):
                register_legacy_compat_routes(fresh_app)

    def test_service_bridge_ci_strict_raises(self, fresh_app):
        """When CI is strict and service_bridge fails, it should raise RuntimeError."""
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with (
                patch(
                    "app.legacy.routes.legacy_compat.is_ci_strict",
                    return_value=True,
                ),
                patch.dict(sys.modules, {"app.fastapi_routes.service_bridge": None}),
                pytest.raises(RuntimeError, match="service_bridge router required in CI"),
            ):
                register_legacy_compat_routes(fresh_app)

    def test_service_bridge_non_ci_logs_warning(self, fresh_app):
        """When not in CI and service_bridge fails, it should log a warning."""
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with (
                patch(
                    "app.legacy.routes.legacy_compat.is_ci_strict",
                    return_value=False,
                ),
                patch.dict(sys.modules, {"app.fastapi_routes.service_bridge": None}),
            ):
                register_legacy_compat_routes(fresh_app)

    def test_tts_install_recoverable_error(self, fresh_app):
        """When tts_install import fails, it should be skipped."""
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            with patch.dict(sys.modules, {"app.fastapi_routes.tts_install": None}):
                register_legacy_compat_routes(fresh_app)

    def test_all_routers_registered(self, fresh_app):
        """Verify that many routers are registered successfully."""
        with (
            patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
            register_legacy_compat_routes(fresh_app)
        non_empty = _collect_paths(fresh_app)
        assert len(non_empty) > 10


@pytest.mark.parametrize("strategy", ["bare", "broad", "narrow"])
@pytest.mark.parametrize("failure_stage", ["import", "mount"])
def test_failed_router_mount_marks_inventory_incomplete_until_retry(
    fresh_app, strategy, failure_stage
):
    module = "test_route_registration"
    error = ImportError("route dependency unavailable")
    router = APIRouter()
    router.add_api_route("/probe", lambda: {"ok": True}, methods=["GET"])
    loader = (
        {"side_effect": error}
        if failure_stage == "import"
        else {"return_value": SimpleNamespace(public_router=router)}
    )
    with (
        patch.object(legacy_compat.importlib, "import_module", **loader),
        patch.object(fresh_app, "include_router", side_effect=error)
        if failure_stage == "mount"
        else nullcontext(),
    ):
        call = lambda: legacy_compat._mount_router(
            fresh_app, module, router_attr="public_router", prefix="/api", strategy=strategy
        )
        if strategy == "bare":
            with pytest.raises(ImportError) as raised:
                call()
            assert raised.value is error
        else:
            call()
    component = f"route:{module}:public_router:/api"
    report = _inventory_report(fresh_app)
    assert not report["complete"] and report["failed_components"] == [component]
    assert not fresh_app.state.runtime_components[component]["required"]

    with patch.object(
        legacy_compat.importlib, "import_module", return_value=SimpleNamespace(public_router=router)
    ):
        call()
    report = _inventory_report(fresh_app)
    assert report["complete"] and not report["failed_components"]
    assert ("GET", "/api/probe") in report["routes"]
    assert fresh_app.state.runtime_components[component]["detail"] == ""


@pytest.mark.parametrize(
    "strategy,error", [("narrow", RuntimeError("unexpected")), ("broad", TypeError("bug"))]
)
def test_router_registration_keeps_nonrecoverable_exceptions(fresh_app, strategy, error):
    with (
        patch.object(legacy_compat.importlib, "import_module", side_effect=error),
        pytest.raises(type(error)) as raised,
    ):
        legacy_compat._mount_router(fresh_app, "test_route_registration", strategy=strategy)
    assert raised.value is error
    assert not _inventory_report(fresh_app)["complete"]


@pytest.mark.parametrize("failure_stage", ["import", "register"])
def test_compat_registration_function_failure_and_retry(fresh_app, failure_stage):
    error = RuntimeError("registration unavailable")
    callback = MagicMock(side_effect=error if failure_stage == "register" else None)
    module = SimpleNamespace(register_routes=callback)
    with patch.object(
        legacy_compat.importlib,
        "import_module",
        side_effect=error if failure_stage == "import" else None,
        return_value=module,
    ):
        legacy_compat._register_compat_func(
            fresh_app, "test_route_registration", register_func_name="register_routes"
        )
    assert _inventory_report(fresh_app)["failed_components"] == [
        "route:test_route_registration:register_routes:"
    ]
    callback.side_effect = None
    with patch.object(legacy_compat.importlib, "import_module", return_value=module):
        legacy_compat._register_compat_func(
            fresh_app, "test_route_registration", register_func_name="register_routes"
        )
    assert _inventory_report(fresh_app)["complete"]


_OPTIONAL_MOUNTS = [
    ("essential", "app.fastapi_routes.domains.auth.auth_routes", "router", ""),
    ("essential", "app.fastapi_routes.system_routes", "router", ""),
    ("essential", "app.fastapi_routes.tools_execute", "router", ""),
    ("essential", "app.fastapi_routes.agent_tool_lifecycle", "router", ""),
    ("essential", "app.legacy.routes.product.compat_routes", "router", "/api"),
    ("lan", "app.fastapi_routes.lan_routes", "router", ""),
    ("lan", "app.fastapi_routes.lan_admin_routes", "router", ""),
    ("approval", "app.fastapi_routes.service_bridge", "router", ""),
    (
        "neuro",
        "app.neuro_bus.integrations.fastapi_integration",
        "add_neurobus_routes",
        "",
    ),
]


@pytest.fixture
def optional_mounts(monkeypatch):
    from app.fastapi_routes.mounts import lan, neuro
    from app.legacy.routes.mounts import essential_compat

    modules = {}
    for _, name, attribute, _ in [
        *_OPTIONAL_MOUNTS,
        ("approval", "app.fastapi_routes.approval", "router", ""),
    ]:
        router = APIRouter()
        router.add_api_route(f"/probe/{len(modules)}", lambda: {"ok": True}, methods=["GET"])
        callback = lambda app, router=router: app.include_router(router)
        modules[name] = SimpleNamespace(
            **{attribute: router if attribute == "router" else callback}
        )
        monkeypatch.setitem(sys.modules, name, modules[name])
    monkeypatch.setattr(legacy_compat, "is_ci_strict", lambda: False)
    monkeypatch.setattr(neuro, "is_ci_strict", lambda: False)
    return modules, {
        "essential": essential_compat.register_essential_compat_routes,
        "lan": lan.register_lan_routes,
        "approval": legacy_compat._register_approval_routes,
        "neuro": neuro.register_neuro_routes,
    }


@pytest.mark.parametrize(
    "phase,module,attribute,prefix,failure_stage",
    [(*mount, "import") for mount in _OPTIONAL_MOUNTS]
    # Settings now share the admin router; keep their fault/retry scenario
    # by exercising registration failure of that live router as well as import.
    + [("lan", "app.fastapi_routes.lan_admin_routes", "router", "", "register")],
)
def test_optional_phase_failure_is_reported_and_retry_recovers(
    fresh_app, monkeypatch, optional_mounts, phase, module, attribute, prefix, failure_stage
):
    modules, register = optional_mounts
    include_router = fresh_app.include_router
    if failure_stage == "import":
        monkeypatch.setitem(sys.modules, module, None)
    else:

        def fail_selected_router(router, **kwargs):
            if router is getattr(modules[module], attribute):
                raise RuntimeError("settings router registration unavailable")
            return include_router(router, **kwargs)

        monkeypatch.setattr(fresh_app, "include_router", fail_selected_router)
    register[phase](fresh_app)
    report = _inventory_report(fresh_app)
    assert not report["complete"]
    assert report["failed_components"] == [f"route:{module}:{attribute}:{prefix}"]
    if module == "app.fastapi_routes.domains.auth.auth_routes":
        with TestClient(fresh_app) as client:
            response = client.get("/api/auth/session/validate")
        assert response.status_code == 200 and response.json()["valid"] is False
    monkeypatch.setitem(sys.modules, module, modules[module])
    monkeypatch.setattr(fresh_app, "include_router", include_router)
    register[phase](fresh_app)
    assert _inventory_report(fresh_app)["complete"]


@pytest.mark.parametrize("phase,module,attribute,prefix", _OPTIONAL_MOUNTS[-2:])
def test_required_ci_phase_records_failure_and_still_raises(
    fresh_app, monkeypatch, optional_mounts, phase, module, attribute, prefix
):
    from app.fastapi_routes.mounts import neuro

    _, register = optional_mounts
    monkeypatch.setattr(legacy_compat, "is_ci_strict", lambda: True)
    monkeypatch.setattr(neuro, "is_ci_strict", lambda: True)
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(RuntimeError, match="required in CI"):
        register[phase](fresh_app)
    assert _inventory_report(fresh_app)["failed_components"] == [
        f"route:{module}:{attribute}:{prefix}"
    ]
