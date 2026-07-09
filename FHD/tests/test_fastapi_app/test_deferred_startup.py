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


@pytest.mark.asyncio
async def test_deferred_route_registration_runs_when_pending(monkeypatch):
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.deferred_routes_pending = True
    called = {"n": 0}

    def _register(_app):
        called["n"] += 1

    monkeypatch.setattr(
        "app.fastapi_routes.register_deferred_routes",
        _register,
        raising=False,
    )
    # 隔离导入模块内 from-import，直接 patch 目标命名空间
    import types

    fake_routes = types.ModuleType("app.fastapi_routes")
    fake_routes.register_deferred_routes = _register
    monkeypatch.setitem(sys.modules, "app.fastapi_routes", fake_routes)

    fake_timing = types.ModuleType("app.fastapi_app.startup_timing")
    fake_timing.mark_startup = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "app.fastapi_app.startup_timing", fake_timing)

    await mod._deferred_route_registration(app)
    assert called["n"] == 1
    assert app.state.deferred_routes_pending is False


@pytest.mark.asyncio
async def test_deferred_mod_bootstrap_runs(monkeypatch):
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.mods_deferred_bootstrap = True
    app.state.mods_routes_loaded = False
    called = {"n": 0}

    def _boot(_app):
        called["n"] += 1

    import types

    fake_mod = types.ModuleType("app.fastapi_app.mod_startup")
    fake_mod.bootstrap_mod_extensions_sync = _boot
    monkeypatch.setitem(sys.modules, "app.fastapi_app.mod_startup", fake_mod)

    await mod._deferred_mod_bootstrap(app)
    assert called["n"] == 1
    assert app.state.mods_deferred_bootstrap is False


@pytest.mark.asyncio
async def test_deferred_heavy_startup_happy_path(monkeypatch):
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.deferred_routes_pending = False
    app.state.mods_deferred_bootstrap = False
    marks: list[str] = []

    import types

    fake_timing = types.ModuleType("app.fastapi_app.startup_timing")
    fake_timing.mark_startup = lambda name: marks.append(name)
    monkeypatch.setitem(sys.modules, "app.fastapi_app.startup_timing", fake_timing)

    async def _ok(_app=None):
        return None

    fake_deliverable = types.ModuleType("app.mod_sdk.desktop_deliverable")

    async def _ensure(_app):
        return None

    fake_deliverable.ensure_deliverable_runtime = _ensure
    monkeypatch.setitem(sys.modules, "app.mod_sdk.desktop_deliverable", fake_deliverable)

    fake_perf = types.ModuleType("app.utils.performance_initializer")
    fake_perf.init_performance_optimization = lambda _app: None
    monkeypatch.setitem(sys.modules, "app.utils.performance_initializer", fake_perf)

    fake_life = types.ModuleType("app.fastapi_app.lifespan")
    fake_life._init_neuro_ddd_async = _ok
    fake_life._init_employee_runtime_async = _ok
    fake_life._init_mobile_relay_desktop_async = _ok
    monkeypatch.setitem(sys.modules, "app.fastapi_app.lifespan", fake_life)

    fake_backup = types.ModuleType("app.desktop_runtime.backup_scheduler")
    fake_backup.start_backup_scheduler = lambda: None
    monkeypatch.setitem(sys.modules, "app.desktop_runtime.backup_scheduler", fake_backup)

    await mod._deferred_heavy_startup(app)
    assert "deferred_heavy_ready" in marks
    assert "performance_optimizer_ready" in marks


@pytest.mark.asyncio
async def test_deferred_heavy_startup_skips_recoverable(monkeypatch):
    mod = _load_deferred_startup()
    app = FastAPI()
    app.state.deferred_routes_pending = False
    app.state.mods_deferred_bootstrap = False

    import types

    class Recoverable(Exception):
        pass

    monkeypatch.setattr(mod, "RECOVERABLE_ERRORS", (Recoverable,))

    fake_timing = types.ModuleType("app.fastapi_app.startup_timing")
    fake_timing.mark_startup = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "app.fastapi_app.startup_timing", fake_timing)

    fake_deliverable = types.ModuleType("app.mod_sdk.desktop_deliverable")

    async def _boom(_app):
        raise Recoverable("skip deliverable")

    fake_deliverable.ensure_deliverable_runtime = _boom
    monkeypatch.setitem(sys.modules, "app.mod_sdk.desktop_deliverable", fake_deliverable)

    fake_perf = types.ModuleType("app.utils.performance_initializer")

    def _boom_perf(_app):
        raise Recoverable("skip perf")

    fake_perf.init_performance_optimization = _boom_perf
    monkeypatch.setitem(sys.modules, "app.utils.performance_initializer", fake_perf)

    async def _ok(_app=None):
        return None

    fake_life = types.ModuleType("app.fastapi_app.lifespan")
    fake_life._init_neuro_ddd_async = _ok
    fake_life._init_employee_runtime_async = _ok
    fake_life._init_mobile_relay_desktop_async = _ok
    monkeypatch.setitem(sys.modules, "app.fastapi_app.lifespan", fake_life)

    fake_backup = types.ModuleType("app.desktop_runtime.backup_scheduler")

    def _boom_backup():
        raise Recoverable("skip backup")

    fake_backup.start_backup_scheduler = _boom_backup
    monkeypatch.setitem(sys.modules, "app.desktop_runtime.backup_scheduler", fake_backup)

    await mod._deferred_heavy_startup(app)
