"""Exercise the imported lifespan with scoped database and worker boundaries."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.engine import Engine


@pytest.fixture
def runtime(monkeypatch):
    def forbid_runtime_resource(*args, **kwargs):
        raise AssertionError("lifespan wiring test opened a real database or worker")

    monkeypatch.setattr(Engine, "connect", forbid_runtime_resource)
    monkeypatch.setattr(sqlite3, "connect", forbid_runtime_resource)
    monkeypatch.setattr(threading.Thread, "start", forbid_runtime_resource)
    lifecycle = importlib.import_module("app.fastapi_app.lifespan")
    mocks = {}

    def isolate(name, sync=(), asynchronous=()):
        module = sys.modules.get(name)
        loaded = module is not None
        if not loaded:
            module = ModuleType(name)
            monkeypatch.setitem(sys.modules, name, module)
        attrs = {key: Mock(name=key) for key in sync}
        attrs.update({key: AsyncMock(name=key) for key in asynchronous})
        mocks.update(attrs)
        for key, value in attrs.items():
            monkeypatch.setattr(module, key, value, raising=loaded)

    isolate("app.fastapi_app.startup_timing", ["mark_startup"])
    isolate("app.neuro_async_bridge", ["set_neuro_main_loop"])
    isolate("app.application.elt.service", ["mark_interrupted_runs_on_startup"])
    isolate("app.application.elt.stale_watchdog", ["start_stale_watchdog", "stop_stale_watchdog"])
    isolate("app.db", ["get_engine"])
    isolate(
        "app.application.dataset_rag.auto_sync_scheduler",
        ["start_auto_sync_scheduler", "stop_auto_sync_scheduler"],
    )
    isolate("app.application.desktop_admin_gate", ["purge_admin_sessions_on_desktop"])
    isolate(
        "app.fastapi_app.deferred_startup",
        asynchronous=["schedule_deferred_heavy_startup", "cancel_deferred_heavy_startup"],
    )
    isolate("app.mod_sdk.desktop_deliverable", asynchronous=["ensure_deliverable_runtime"])
    isolate("app.utils.performance.performance_initializer", ["init_performance_optimization"])
    isolate(
        "app.desktop_runtime.backup_scheduler", ["start_backup_scheduler", "stop_backup_scheduler"]
    )
    isolate(
        "app.desktop_runtime.sync_outbox_scheduler",
        ["start_sync_outbox_scheduler", "stop_sync_outbox_scheduler"],
    )
    isolate(
        "app.desktop_runtime.process_memory",
        ["start_process_memory_guard", "stop_process_memory_guard"],
    )
    isolate("app.fastapi_app.mod_startup", ["wait_for_background_mod_load"])
    isolate("app.fastapi_app.resource_cleanup", asynchronous=["close_llm_http_clients"])
    isolate("app.application.employee_runtime.scheduler", ["stop_employee_scheduler"])
    isolate("app.domain.shared_services.mobile_relay_desktop_client", ["stop_desktop_relay_poller"])
    isolate("app.neuro_bus.bus_setup", asynchronous=["teardown_neuro_bus"])
    isolate("app.neuro_bus.health_monitor", ["get_health_monitor"])

    async def inline_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(
        lifecycle,
        "asyncio",
        SimpleNamespace(
            gather=asyncio.gather,
            get_running_loop=asyncio.get_running_loop,
            to_thread=inline_thread,
        ),
    )
    for name in (
        "install_proactor_reset_filter",
        "_log_ai_capability_status",
        "_start_agent_tasks",
        "_stop_agent_tasks",
        "start_paid_asset_installs",
        "_start_parent_watchdog",
        "passive_node_enabled",
        "_desktop_fast_start_enabled",
    ):
        mocks[name] = Mock(name=name)
        monkeypatch.setattr(lifecycle, name, mocks[name])
    for name in (
        "_init_mods_async",
        "_initialize_databases_async",
        "_init_neuro_ddd_async",
        "_init_employee_runtime_async",
        "_init_mobile_relay_desktop_async",
        "stop_paid_asset_installs",
    ):
        mocks[name] = AsyncMock(name=name)
        monkeypatch.setattr(lifecycle, name, mocks[name])
    mocks["_start_parent_watchdog"].return_value = None
    return lifecycle.lifespan, mocks


@pytest.mark.parametrize("passive", [False, True])
@pytest.mark.parametrize("fast_start", [False, True])
@pytest.mark.parametrize("shutdown", [None, RuntimeError, asyncio.CancelledError])
def test_scheduler_and_elt_survive_lifespan(runtime, passive, fast_start, shutdown):
    lifespan, calls = runtime
    calls["passive_node_enabled"].return_value = passive
    calls["_desktop_fast_start_enabled"].return_value = fast_start
    app = SimpleNamespace(state=SimpleNamespace())

    async def run():
        async with lifespan(app):
            if passive:
                calls["mark_interrupted_runs_on_startup"].assert_not_called()
                calls["start_stale_watchdog"].assert_not_called()
            else:
                calls["mark_interrupted_runs_on_startup"].assert_called_once_with(
                    calls["get_engine"].return_value
                )
                calls["start_stale_watchdog"].assert_called_once_with()
            calls["stop_stale_watchdog"].assert_not_called()
            assert calls["start_auto_sync_scheduler"].call_count == int(not passive)
            calls["stop_auto_sync_scheduler"].assert_not_called()
            if shutdown:
                raise shutdown("shutdown")

    if shutdown:
        with pytest.raises(shutdown, match="shutdown"):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert calls["start_auto_sync_scheduler"].call_count == int(not passive)
    calls["stop_auto_sync_scheduler"].assert_called_once_with()
    if passive:
        calls["stop_stale_watchdog"].assert_not_called()
    else:
        calls["stop_stale_watchdog"].assert_called_once_with()
    calls["start_paid_asset_installs"].assert_called_once_with()
    calls["stop_paid_asset_installs"].assert_awaited_once_with()
    calls["close_llm_http_clients"].assert_awaited_once_with()
    calls["teardown_neuro_bus"].assert_awaited_once_with()
    assert calls["schedule_deferred_heavy_startup"].await_count == int(fast_start)
    assert calls["cancel_deferred_heavy_startup"].await_count == int(fast_start)


@pytest.mark.parametrize(
    "failure", ["start_auto_sync_scheduler", "stop_auto_sync_scheduler", "stop_stale_watchdog"]
)
def test_scheduler_failure_does_not_block_other_lifecycle_cleanup(runtime, failure):
    lifespan, calls = runtime
    calls["passive_node_enabled"].return_value = False
    calls["_desktop_fast_start_enabled"].return_value = True
    calls[failure].side_effect = RuntimeError("scheduler unavailable")

    async def run():
        async with lifespan(SimpleNamespace(state=SimpleNamespace())):
            calls["start_stale_watchdog"].assert_called_once_with()

    asyncio.run(run())
    calls["start_auto_sync_scheduler"].assert_called_once_with()
    calls["stop_auto_sync_scheduler"].assert_called_once_with()
    calls["stop_paid_asset_installs"].assert_awaited_once_with()
    calls["teardown_neuro_bus"].assert_awaited_once_with()
