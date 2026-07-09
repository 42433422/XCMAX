"""桌面 fast-start 延后加载开关与调度（隔离导入，避免拉全量 factory）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

_MODULE_PATH = Path(__file__).resolve().parents[2] / "app" / "fastapi_app" / "deferred_startup.py"


def _load_deferred_startup():
    name = "xcagi_deferred_startup_isolated"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (None, True),
        ("1", True),
        ("true", True),
        ("0", False),
        ("false", False),
        ("off", False),
        ("no", False),
    ],
)
def test_desktop_fast_start_enabled(monkeypatch, env, expected):
    mod = _load_deferred_startup()
    if env is None:
        monkeypatch.delenv("XCAGI_DESKTOP_FAST_START", raising=False)
    else:
        monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", env)
    assert mod._desktop_fast_start_enabled() is expected


@pytest.mark.asyncio
async def test_schedule_deferred_startup_is_idempotent(monkeypatch):
    mod = _load_deferred_startup()
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    app = FastAPI()
    await mod.schedule_deferred_heavy_startup(app)
    first = app.state.deferred_startup_task
    await mod.schedule_deferred_heavy_startup(app)
    assert app.state.deferred_startup_task is first
    await mod.cancel_deferred_heavy_startup(app)


@pytest.mark.asyncio
async def test_schedule_skipped_when_fast_start_disabled(monkeypatch):
    mod = _load_deferred_startup()
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "0")
    app = FastAPI()
    await mod.schedule_deferred_heavy_startup(app)
    assert not hasattr(app.state, "deferred_startup_task")


@pytest.mark.asyncio
async def test_cancel_noop_when_no_task():
    mod = _load_deferred_startup()
    app = FastAPI()
    await mod.cancel_deferred_heavy_startup(app)


@pytest.mark.asyncio
async def test_deferred_route_registration_skips_when_not_pending():
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.deferred_routes_pending = False
    await mod._deferred_route_registration(app)
    assert app.state.deferred_routes_pending is False


@pytest.mark.asyncio
async def test_deferred_mod_bootstrap_skips_when_already_loaded():
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.mods_deferred_bootstrap = True
    app.state.mods_routes_loaded = True
    await mod._deferred_mod_bootstrap(app)
    assert app.state.mods_deferred_bootstrap is False


@pytest.mark.asyncio
async def test_deferred_mod_bootstrap_noop_when_flag_off():
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.mods_deferred_bootstrap = False
    await mod._deferred_mod_bootstrap(app)
