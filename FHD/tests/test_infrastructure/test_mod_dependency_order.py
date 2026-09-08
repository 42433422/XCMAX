"""Real manifest loading respects dependency order and never starts cyclic graphs."""

import json
import sys
from unittest.mock import Mock

import pytest

from app.infrastructure.mods import mod_manager
from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.registry import ModRegistry


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    registry = ModRegistry()
    monkeypatch.setattr(mod_manager, "get_mod_registry", lambda: registry)
    monkeypatch.setattr("app.mod_sdk.product_skus.assert_mod_allowed_for_sku", lambda *_: None)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", lambda *_: True
    )
    manager = mod_manager.ModManager(mods_root=str(tmp_path))
    monkeypatch.setattr(manager, "all_mods_roots", lambda: [str(tmp_path)])
    backend = Mock()
    monkeypatch.setattr(manager, "_load_mod_backend", backend)

    def write(mid, dependencies, primary=False):
        directory = tmp_path / mid
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "id": mid,
                    "name": mid,
                    "version": "1.0.0.1",
                    "dependencies": dependencies,
                    "primary": primary,
                }
            )
        )

    return manager, registry, backend, write


def test_reverse_alphabetical_chain_loads_before_primary_dependent(runtime):
    manager, registry, backend, write = runtime
    write("a-primary", {"b-middle": ">=1.0.0.1"}, primary=True)
    write("b-middle", {"z-base": ">=1.0.0.1"})
    write("z-base", {})
    assert manager.load_all_mods() == ["z-base", "b-middle", "a-primary"]
    assert set(registry.list_mod_ids()) == {"a-primary", "b-middle", "z-base"}
    assert backend.call_count == 3
    assert manager._recent_load_failures == []


@pytest.mark.parametrize("self_cycle", [False, True])
def test_cycles_and_downstream_nodes_block_but_independent_mod_loads(runtime, self_cycle):
    manager, registry, backend, write = runtime
    write("a", {"a" if self_cycle else "b": "*"})
    write("b", {"a": "*"})
    write("downstream", {"b": "*"})
    write("independent", {})
    assert manager.load_all_mods() == ["independent"]
    assert registry.list_mod_ids() == ["independent"]
    assert backend.call_count == 1
    assert len(manager._recent_load_failures) == 3


@pytest.mark.parametrize("reason", ["version", "missing", "entitlement"])
def test_ordering_does_not_bypass_dependency_or_entitlement_checks(runtime, monkeypatch, reason):
    manager, registry, backend, write = runtime
    write("a-dependent", {"z-base": ">=2.0" if reason == "version" else "*"})
    if reason != "missing":
        write("z-base", {})
    if reason == "entitlement":
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
            lambda mid: mid != "z-base",
        )
    assert manager.load_all_mods() == (["z-base"] if reason == "version" else [])
    assert registry.get_mod_metadata("a-dependent") is None
    assert backend.call_count == int(reason == "version")


def test_preloaded_dependency_satisfies_ordering_without_requiring_disk_candidate(runtime):
    manager, registry, backend, write = runtime
    registry.register_mod(ModMetadata(id="external", name="External", version="1.0.0.1"))
    write("dependent", {"external": ">=1.0.0.1"})
    assert manager.load_all_mods() == ["dependent"]
    assert backend.call_count == 1


def test_actual_backend_initialization_observes_registered_dependency(
    runtime, tmp_path, monkeypatch
):
    manager, registry, _, write = runtime
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(
        manager, "_load_mod_backend", type(manager)._load_mod_backend.__get__(manager)
    )
    for mid, dependencies in [("a-real", {"z-real": "*"}), ("z-real", {})]:
        write(mid, dependencies)
        manifest = tmp_path / mid / "manifest.json"
        data = json.loads(manifest.read_text())
        data["backend"] = {"entry": "entry", "init": "initialize"}
        manifest.write_text(json.dumps(data))
        backend = tmp_path / mid / "backend"
        backend.mkdir()
        check = (
            "    assert get_mod_registry().get_mod_metadata('z-real') is not None\n"
            if dependencies
            else ""
        )
        (backend / "entry.py").write_text(
            "from pathlib import Path\n"
            "from app.infrastructure.mods.mod_manager import get_mod_registry\n"
            "def initialize():\n"
            + check
            + "    Path(__file__).with_suffix('.receipt').write_text('initialized')\n"
        )
    try:
        assert manager.load_all_mods() == ["z-real", "a-real"]
        assert registry.get_mod_metadata("a-real") is not None
        assert (tmp_path / "a-real/backend/entry.receipt").read_text() == "initialized"
        assert (tmp_path / "z-real/backend/entry.receipt").read_text() == "initialized"
    finally:
        for name, module in list(sys.modules.items()):
            if str(getattr(module, "__file__", "")).startswith(str(tmp_path)):
                sys.modules.pop(name, None)
