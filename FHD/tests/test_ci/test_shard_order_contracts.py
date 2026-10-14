"""Explicit contracts formerly reached only through incidental suite state."""

import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "app.legacy.lan.lan_compat",
        "app.mod_sdk.approval_compat",
        "app.mod_sdk.customer_service_pages_compat",
        "app.mod_sdk.model_payment_compat",
    ],
)
def test_registered_facade_resolves_its_manifest(module, tmp_path, monkeypatch):
    facade = importlib.import_module(module)
    (tmp_path / "manifest.json").write_text('{"config": {"lan_facade": true}}')
    manager = SimpleNamespace(get_mod=lambda _id: SimpleNamespace(mod_path=str(tmp_path)))
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: manager)
    assert facade._resolve_mod_dir() == tmp_path
    if module.endswith("lan_compat"):
        monkeypatch.delenv("XCAGI_DISABLE_LAN_MOD", raising=False)
        monkeypatch.delenv("XCAGI_LAN_VIA_MOD", raising=False)
        monkeypatch.setattr(facade, "is_lan_mod_installed", lambda: True)
        assert facade.is_lan_via_mod_enabled() is True


def test_runtime_issue_expiry_and_healthy_cognition(monkeypatch):
    from app import runtime_integrity as runtime

    monkeypatch.setattr(runtime, "_PROCESS_ISSUES", {})
    clock = SimpleNamespace(monotonic=lambda: 100.0)
    monkeypatch.setattr(runtime, "time", clock)
    runtime.record_runtime_issue("fixture", "temporary", ttl_seconds=1)
    assert runtime.runtime_integrity_snapshot()["status"] == "degraded"
    clock.monotonic = lambda: 101.0
    assert runtime.runtime_integrity_snapshot()["status"] == "healthy"
    assert runtime._PROCESS_ISSUES == {}
    assert (
        runtime.neuro_degraded_reasons({"cognition": {"cognition": {"llm_port_available": True}}})
        == []
    )
