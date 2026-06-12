"""mounts/business — _mount 成功/失败与 CI strict 分支。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
