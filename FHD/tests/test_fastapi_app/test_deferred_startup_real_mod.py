"""直接导入真实 deferred_startup 模块，补齐隔离加载测不到的分支。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.fastapi_app import deferred_startup as ds


@pytest.mark.asyncio
async def test_cancel_deferred_heavy_startup_awaits_cancelled_task():
    app = FastAPI()

    async def _never():
        await asyncio.sleep(3600)

    task = asyncio.create_task(_never())
    app.state.deferred_startup_task = task
    await ds.cancel_deferred_heavy_startup(app)
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_schedule_creates_task_when_enabled(monkeypatch):
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    app = FastAPI()
    app.state.deferred_routes_pending = False
    app.state.mods_deferred_bootstrap = False

    with patch.object(ds, "_deferred_heavy_startup", new=AsyncMock()) as heavy:
        await ds.schedule_deferred_heavy_startup(app)
        task = app.state.deferred_startup_task
        assert task is not None
        await asyncio.sleep(0)
        heavy.assert_awaited()
        await ds.cancel_deferred_heavy_startup(app)


@pytest.mark.asyncio
async def test_deferred_route_registration_real(monkeypatch):
    app = FastAPI()
    app.state.deferred_routes_pending = True
    called = {}

    def _reg(a):
        called["app"] = a

    monkeypatch.setattr("app.fastapi_routes.register_deferred_routes", _reg)
    monkeypatch.setattr("app.fastapi_app.startup_timing.mark_startup", lambda *_a, **_k: None)
    await ds._deferred_route_registration(app)
    assert called["app"] is app
    assert app.state.deferred_routes_pending is False


@pytest.mark.asyncio
async def test_deferred_mod_bootstrap_real(monkeypatch):
    app = FastAPI()
    app.state.mods_deferred_bootstrap = True
    app.state.mods_routes_loaded = False
    called = {}

    def _boot(a):
        called["ok"] = True
        a.state.mods_routes_loaded = True

    monkeypatch.setattr("app.fastapi_app.mod_startup.bootstrap_mod_extensions_sync", _boot)
    await ds._deferred_mod_bootstrap(app)
    assert called.get("ok") is True
    assert app.state.mods_deferred_bootstrap is False
