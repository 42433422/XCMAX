"""Desktop fast-start: deliverable-status must respond before deferred routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.desktop_runtime import configure_desktop_environment
from app.fastapi_app import create_fastapi_app
from app.security.lan_config import reset_lan_config_cache
from app.security.lan_settings_store import LanSettingsOverride


@pytest.fixture
def fast_start_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    configure_desktop_environment(str(tmp_path))

    import app.security.lan_settings_store as lan_store

    monkeypatch.setattr(
        lan_store,
        "load_overrides",
        lambda: LanSettingsOverride(enabled=False),
    )
    reset_lan_config_cache()

    app = create_fastapi_app()
    assert getattr(app.state, "deferred_routes_pending", False) is True
    with TestClient(app) as client:
        yield client, app


def test_deliverable_status_available_in_bootstrap(fast_start_client):
    client, app = fast_start_client
    resp = client.get("/api/platform-shell/deliverable-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert "deliverable" in (body.get("data") or {})
