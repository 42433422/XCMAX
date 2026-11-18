"""Execute the real lifespan body without importing database or worker runtimes."""

from __future__ import annotations

import ast
import asyncio
import builtins
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def runtime():
    source = Path(__file__).resolve().parents[2] / "app/fastapi_app/lifespan.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    )
    mocks = {}

    def module(name, sync=(), asynchronous=()):
        attrs = {key: Mock(name=key) for key in sync}
        attrs.update({key: AsyncMock(name=key) for key in asynchronous})
        mocks.update(attrs)
        return SimpleNamespace(**attrs)

    modules = {
        "app.fastapi_app.startup_timing": module("timing", ["mark_startup"]),
        "app.neuro_async_bridge": module("bridge", ["set_neuro_main_loop"]),
        "app.application.elt.service": module("elt", ["mark_interrupted_runs_on_startup"]),
        "app.application.elt.stale_watchdog": module("watchdog", ["start_stale_watchdog"]),
        "app.db": module("db", ["get_engine"]),
        "app.application.dataset_rag.auto_sync_scheduler": module(
            "sync", ["start_auto_sync_scheduler", "stop_auto_sync_scheduler"]
        ),
        "app.application.desktop_admin_gate": module(
            "desktop", ["purge_admin_sessions_on_desktop"]
        ),
        "app.fastapi_app.deferred_startup": module(
            "deferred",
            asynchronous=["schedule_deferred_heavy_startup", "cancel_deferred_heavy_startup"],
        ),
        "app.mod_sdk.desktop_deliverable": module(
            "deliverable", asynchronous=["ensure_deliverable_runtime"]
        ),
        "app.utils.performance.performance_initializer": module(
            "performance", ["init_performance_optimization"]
        ),
        "app.desktop_runtime.backup_scheduler": module(
            "backup", ["start_backup_scheduler", "stop_backup_scheduler"]
        ),
        "app.desktop_runtime.sync_outbox_scheduler": module(
            "outbox", ["start_sync_outbox_scheduler", "stop_sync_outbox_scheduler"]
        ),
        "app.desktop_runtime.process_memory": module(
            "memory", ["start_process_memory_guard", "stop_process_memory_guard"]
        ),
        "app.fastapi_app.mod_startup": module("mods", ["wait_for_background_mod_load"]),
        "app.fastapi_app.resource_cleanup": module(
            "cleanup", asynchronous=["close_llm_http_clients"]
        ),
        "app.application.employee_runtime.scheduler": module(
            "employee", ["stop_employee_scheduler"]
        ),
        "app.domain.shared_services.mobile_relay_desktop_client": module(
            "relay", ["stop_desktop_relay_poller"]
        ),
        "app.neuro_bus.bus_setup": module("bus", asynchronous=["teardown_neuro_bus"]),
        "app.neuro_bus.health_monitor": module("health", ["get_health_monitor"]),
    }

    def import_stub(name, globals=None, locals=None, fromlist=(), level=0):
        # Unknown imports fail rather than accidentally starting a real service.
        return modules[name]

    async def inline_thread(func, *args):
        return func(*args)

    namespace = {
        "__builtins__": dict(vars(builtins), __import__=import_stub),
        "asynccontextmanager": asynccontextmanager,
        "FastAPI": object,
        "asyncio": SimpleNamespace(
            gather=asyncio.gather,
            get_running_loop=asyncio.get_running_loop,
            to_thread=inline_thread,
        ),
        "logger": Mock(),
        "RECOVERABLE_ERRORS": (RuntimeError,),
    }
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
        namespace[name] = mocks[name] = Mock(name=name)
    for name in (
        "_init_mods_async",
        "_initialize_databases_async",
        "_init_neuro_ddd_async",
        "_init_employee_runtime_async",
        "_init_mobile_relay_desktop_async",
        "stop_paid_asset_installs",
    ):
        namespace[name] = mocks[name] = AsyncMock(name=name)
    mocks["_start_parent_watchdog"].return_value = None
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["lifespan"], mocks


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
            calls["mark_interrupted_runs_on_startup"].assert_called_once_with(
                calls["get_engine"].return_value
            )
            calls["start_stale_watchdog"].assert_called_once_with()
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
    calls["start_paid_asset_installs"].assert_called_once_with()
    calls["stop_paid_asset_installs"].assert_awaited_once_with()
    calls["close_llm_http_clients"].assert_awaited_once_with()
    calls["teardown_neuro_bus"].assert_awaited_once_with()
    assert calls["schedule_deferred_heavy_startup"].await_count == int(fast_start)
    assert calls["cancel_deferred_heavy_startup"].await_count == int(fast_start)


@pytest.mark.parametrize("failure", ["start_auto_sync_scheduler", "stop_auto_sync_scheduler"])
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
