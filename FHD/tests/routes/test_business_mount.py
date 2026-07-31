"""mounts/business — _mount 成功/失败与 CI strict 分支。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI

from app.fastapi_routes.mounts import business as business_mount
from app.fastapi_routes.registry import RouteRegistry


def test_mount_registers_loader_router() -> None:
    registry = RouteRegistry()
    router = APIRouter()

    @router.get("/biz-smoke")
    def _smoke():
        return {"ok": True}

    business_mount._mount(registry, "smoke", lambda: router, priority=5)
    assert "smoke" in registry.names()


def test_mount_swallows_error_when_not_ci_strict() -> None:
    registry = RouteRegistry()

    def _boom():
        raise RuntimeError("loader failed")

    with patch.object(business_mount, "is_ci_strict", return_value=False):
        business_mount._mount(registry, "broken", _boom, required_in_ci=False)
    assert "broken" not in registry.names()


def test_mount_raises_in_ci_strict_when_required() -> None:
    registry = RouteRegistry()

    def _boom():
        raise RuntimeError("loader failed")

    with patch.object(business_mount, "is_ci_strict", return_value=True):
        with pytest.raises(RuntimeError, match="Required route mount failed"):
            business_mount._mount(registry, "broken", _boom, required_in_ci=True)


def test_register_business_routes_smoke() -> None:
    registry = RouteRegistry()
    app = FastAPI()
    business_mount.register_business_routes(app, registry)
    assert len(registry.names()) >= 5
    assert "agent" in registry.names()
    assert "system" in registry.names()
    assert "taiyangniao_attendance_compat" in registry.names()


def test_mod_taiyangniao_pro_exposes_attendance_api_when_routes_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Mgr:
        _http_routes_registered = {"taiyangniao-pro"}

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: _Mgr(),
    )
    assert business_mount._mod_taiyangniao_pro_exposes_attendance_api() is True


def test_mod_taiyangniao_pro_exposes_attendance_api_false_when_not_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Mgr:
        _http_routes_registered: set[str] = set()

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: _Mgr(),
    )
    assert business_mount._mod_taiyangniao_pro_exposes_attendance_api() is False


def test_bundled_taiyangniao_pro_exposes_attendance_api_detects_repo_mod() -> None:
    assert business_mount._bundled_taiyangniao_pro_exposes_attendance_api() is True


def test_load_taiyangniao_attendance_compat_router_skips_when_mod_routes_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        business_mount,
        "_mod_taiyangniao_pro_exposes_attendance_api",
        lambda: True,
    )
    router = business_mount._load_taiyangniao_attendance_compat_router()
    assert router.routes == []


def test_load_taiyangniao_attendance_compat_router_loads_routes_when_mod_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        business_mount,
        "_mod_taiyangniao_pro_exposes_attendance_api",
        lambda: False,
    )
    monkeypatch.setattr(
        business_mount,
        "_bundled_taiyangniao_pro_exposes_attendance_api",
        lambda: False,
    )
    router = business_mount._load_taiyangniao_attendance_compat_router()
    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/api/mod/taiyangniao-pro/attendance/rules" in paths
