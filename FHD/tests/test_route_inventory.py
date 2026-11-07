"""Inventory must expand lazy routes and refuse unfinished registration."""

from __future__ import annotations

import os

import pytest
from fastapi import APIRouter, FastAPI

from scripts import route_inventory_diff as inventory


def test_inventory_expands_lazy_include_and_asgi_mount():
    leaf = APIRouter()
    leaf.add_api_route("/items/{item_id:int}/", lambda: None, methods=["GET", "POST"])
    nested = APIRouter()
    nested.include_router(leaf, prefix="/nested")
    child = FastAPI()
    child.include_router(nested, prefix="/api")
    app = FastAPI()
    app.mount("/service", child)
    pairs = inventory._fastapi_route_pairs(app)
    assert ("GET", "/service/api/nested/items/{item_id}") in pairs
    assert ("POST", "/service/api/nested/items/{item_id}") in pairs
    assert not any(method in {"HEAD", "OPTIONS", "TRACE"} for method, _ in pairs)


@pytest.mark.parametrize("previous", [None, "1"])
def test_inventory_waits_for_complete_configured_registration(monkeypatch, previous):
    from app import fastapi_app
    from app.fastapi_app import mod_startup

    if previous is None:
        monkeypatch.delenv("XCAGI_DESKTOP_FAST_START", raising=False)
    else:
        monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", previous)
    app = FastAPI()
    events = []

    def create(**kwargs):
        assert os.environ["XCAGI_DESKTOP_FAST_START"] == "0"
        events.append("create")
        app.add_api_route("/api/host", lambda: None)
        return app

    def wait(candidate, *, timeout):
        assert candidate is app and timeout == 7.0
        events.append("wait")
        app.add_api_route("/api/mod/example", lambda: None)
        app.state.mods_full_load_done = True
        return True

    monkeypatch.setattr(fastapi_app, "create_fastapi_app", create)
    monkeypatch.setattr(mod_startup, "wait_for_background_mod_load", wait)
    monkeypatch.setattr(inventory, "_mod_registration_failures", lambda: {})
    result = inventory._build_app(timeout=7.0)
    assert events == ["create", "wait"]
    assert ("GET", "/api/mod/example") in inventory._fastapi_route_pairs(result)
    assert os.environ.get("XCAGI_DESKTOP_FAST_START") == previous


@pytest.mark.parametrize("failure", ["timeout", "error", "pending", "incomplete"])
def test_inventory_never_accepts_partial_registration(monkeypatch, failure):
    from app import fastapi_app
    from app.fastapi_app import mod_startup

    app = FastAPI()
    app.state.mods_full_load_done = failure != "incomplete"
    app.state.deferred_routes_pending = failure == "pending"
    app.state.mods_background_load_error = "failed" if failure == "error" else None
    monkeypatch.setattr(fastapi_app, "create_fastapi_app", lambda **kwargs: app)
    monkeypatch.setattr(
        mod_startup, "wait_for_background_mod_load", lambda *a, **k: failure != "timeout"
    )
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    with pytest.raises(RuntimeError, match="incomplete"):
        inventory._build_app()
    assert os.environ["XCAGI_DESKTOP_FAST_START"] == "1"


def test_inventory_reports_failed_mounts_and_final_conflicts(monkeypatch):
    app = FastAPI()
    app.add_api_route("/api/items/{item_id}", lambda: None)
    app.add_api_route("/api/items/export", lambda: None)
    app.state.runtime_components = {"optional_router": {"ok": False, "required": False}}
    monkeypatch.setenv("SECRET_KEY", "must-not-be-in-report")
    report = inventory._inventory_report(app)
    assert report["complete"] is False
    assert report["failed_components"] == ["optional_router"]
    assert report["conflicts"][0]["kind"] == "shadow"
    assert "SECRET_KEY" not in report["configuration"]


@pytest.mark.parametrize("phase", ["blueprint", "load", "manifest"])
def test_swallowed_mod_failures_make_completed_worker_inventory_incomplete(monkeypatch, phase):
    from app import fastapi_app
    from app.fastapi_app import mod_startup
    from app.infrastructure.mods import mod_manager

    # Use the manager's real failure accessors without initializing a Mod runtime.
    manager = object.__new__(mod_manager.ModManager)
    manager._blueprint_failures = []
    manager._recent_load_failures = []
    manager._scan_manifest_errors = []
    if phase == "blueprint":
        manager.record_blueprint_failure("broken-mod", "backend import failed")
    elif phase == "load":
        manager._recent_load_failures.append({"mod_id": "broken-mod"})
    else:
        manager._scan_manifest_errors.append({"mod_id": "broken-mod"})
    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: manager)
    monkeypatch.setattr(mod_manager, "is_mods_disabled", lambda: False)
    app = FastAPI()
    app.state.mods_full_load_done = True
    app.state.mods_background_load_error = None
    monkeypatch.setattr(fastapi_app, "create_fastapi_app", lambda **kwargs: app)
    monkeypatch.setattr(mod_startup, "wait_for_background_mod_load", lambda *a, **k: True)
    report = inventory._inventory_report(inventory._build_app())
    assert report["complete"] is False
    assert report["mod_registration_failures"] == {phase: ["broken-mod"]}
    monkeypatch.setattr(inventory, "_build_app", lambda: app)
    monkeypatch.setattr("sys.argv", ["route_inventory_diff.py"])
    assert inventory.main() == 1


def test_disabled_mod_profile_does_not_initialize_manager(monkeypatch):
    from app.infrastructure.mods import mod_manager

    monkeypatch.setattr(mod_manager, "is_mods_disabled", lambda: True)

    def unexpected_initialization():
        pytest.fail("A disabled Mod profile must not create a runtime manager")

    monkeypatch.setattr(mod_manager, "get_mod_manager", unexpected_initialization)
    assert inventory._mod_registration_failures() == {}
