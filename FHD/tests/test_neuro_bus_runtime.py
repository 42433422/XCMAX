from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods-admin-runtime" / "xcagi-neuro-bus-bridge"


def test_neuro_bus_manifest_runtime_phase():
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    cfg = data.get("config") or {}
    assert cfg.get("neuro_bus_facade") is True
    assert cfg.get("phase") == "S"
    assert (MOD_DIR / "backend" / "bus_runtime_factory.py").is_file()
    assert (MOD_DIR / "backend" / "bus_runtime_adapters.py").is_file()
    assert (MOD_DIR / "backend" / "bus_runtime_providers.py").is_file()


def test_create_bus_runtime_bundle():
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(str(MOD_DIR), "xcagi-neuro-bus-bridge", "bus_runtime_factory")
    bundle = mod.create_bus_runtime_bundle()
    assert bundle.get("phase") == "S"
    assert bundle.get("provider_id") == "mod:xcagi-neuro-bus-bridge"
    for key in ("setup", "teardown", "publish", "health"):
        assert callable(bundle[key])


def test_list_neuro_bus_facade_registry_runtime_path(monkeypatch):
    from app.mod_sdk import neuro_bus_compat as compat

    monkeypatch.setattr(compat, "is_neuro_bus_via_mod_enabled", lambda: True)
    data = compat.list_neuro_bus_facade_registry()
    assert data.get("execution_path") == "mod_bus_runtime"
    assert data.get("phase") == "S"


def test_publish_neuro_event_runtime_host_path(monkeypatch):
    from app.mod_sdk import neuro_bus_runtime as rt

    monkeypatch.setattr(rt, "is_neuro_bus_runtime_via_mod_enabled", lambda: False)

    class _Bus:
        is_running = False

    monkeypatch.setattr("app.neuro_bus.bus.get_neuro_bus", lambda: _Bus())
    assert rt.publish_neuro_event_runtime("test.evt", {"x": 1}) is False


def test_get_bundle_serializes_first_mod_load(monkeypatch):
    from app.mod_sdk import neuro_bus_runtime as rt

    rt._create_runtime_bundle.cache_clear()
    rt._load_runtime_providers.cache_clear()
    monkeypatch.setattr(rt, "_resolve_mod_path", lambda: ("neuro", "/tmp/neuro"))

    active = 0
    max_active = 0
    state_lock = threading.Lock()

    class _Provider:
        @staticmethod
        def create_bus_runtime_bundle():
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return {"publish": lambda *_args: True}

    monkeypatch.setattr(rt, "_load_runtime_providers", lambda *_args: _Provider())
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            bundles = list(pool.map(lambda _index: rt._get_bundle(), range(4)))
    finally:
        rt._create_runtime_bundle.cache_clear()

    assert max_active == 1
    assert all(bundle is bundles[0] for bundle in bundles)


def test_run_lifespan_setup_host_path(monkeypatch):
    from app.mod_sdk import neuro_bus_runtime as rt

    monkeypatch.setattr(rt, "is_neuro_bus_runtime_via_mod_enabled", lambda: False)
    calls: list[str] = []

    async def _setup():
        calls.append("setup")

    class _Registry:
        async def initialize_all(self):
            calls.append("domains")

    monkeypatch.setattr("app.neuro_bus.bus_setup.setup_neuro_bus", _setup)
    monkeypatch.setattr(
        "app.neuro_bus.domains.base.get_domain_registry",
        lambda: _Registry(),
    )

    import asyncio

    asyncio.run(rt.run_lifespan_setup())
    assert calls == ["setup", "domains"]


def test_get_neuro_bus_health_runtime_no_recursion(monkeypatch):
    from app.mod_sdk import neuro_bus_runtime as rt

    monkeypatch.setattr(rt, "is_neuro_bus_runtime_via_mod_enabled", lambda: False)

    class _Mgr:
        def get_health(self):
            return {"status": "ok", "source": "host_manager"}

    monkeypatch.setattr("app.neuro_bus.bus_setup.get_neuro_bus_manager", lambda: _Mgr())
    health = rt.get_neuro_bus_health_runtime()
    assert health.get("source") == "host_manager"
