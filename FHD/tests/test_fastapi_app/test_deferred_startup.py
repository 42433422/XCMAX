"""桌面 fast-start 延后加载开关与调度（隔离导入，避免拉全量 factory）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

_MODULE_PATH = Path(__file__).resolve().parents[2] / "app" / "fastapi_app" / "deferred_startup.py"
_NODE_ROLE_PATH = Path(__file__).resolve().parents[2] / "app" / "fastapi_app" / "node_role.py"


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


def _load_node_role():
    name = "xcagi_node_role_isolated"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _NODE_ROLE_PATH)
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


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (None, False),
        ("0", False),
        ("false", False),
        ("1", True),
        ("true", True),
        ("on", True),
        ("yes", True),
    ],
)
def test_passive_node_enabled(monkeypatch, env, expected):
    mod = _load_node_role()
    if env is None:
        monkeypatch.delenv("XCAGI_PASSIVE_NODE", raising=False)
    else:
        monkeypatch.setenv("XCAGI_PASSIVE_NODE", env)
    assert mod.passive_node_enabled() is expected


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
