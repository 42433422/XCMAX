"""Production LAN mount preserves the formerly first-match settings contract."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import lan_admin_routes
from app.fastapi_routes.mounts.lan import register_lan_routes
from app.legacy.routes.openapi_route_compat import iter_effective_routes
from app.security import lan_settings_store


@pytest.fixture
def mounted_lan(monkeypatch):
    cfg = SimpleNamespace(
        enabled=True,
        admin_host_ips=["127.0.0.1"],
        trusted_proxies=[],
        license_secret="test-license-secret-" + "x" * 32,
        admin_bootstrap_key="test-bootstrap-key-" + "y" * 32,
        allowed_cidrs=["127.0.0.0/8"],
        is_secret_ready=lambda: True,
    )
    overrides = SimpleNamespace(
        enabled=None, license_secret=None, admin_bootstrap_key=None, allowed_cidrs=None
    )
    monkeypatch.setattr(lan_admin_routes, "get_lan_config", lambda: cfg)
    monkeypatch.setattr(lan_settings_store, "load_overrides", lambda: overrides)
    saved = Mock()
    monkeypatch.setattr(lan_settings_store, "save_overrides", saved)
    monkeypatch.setattr("app.security.lan_config.reset_lan_config_cache", lambda: None)
    app = FastAPI()

    @app.middleware("http")
    async def admin_key_session(request, call_next):
        request.state.lan_is_admin = True
        return await call_next(request)

    register_lan_routes(app)
    return app, cfg, saved


def test_production_mount_has_one_handler_per_settings_method(mounted_lan):
    app, _, _ = mounted_lan
    routes = list(iter_effective_routes(app.routes))
    schema = app.openapi()
    assert set(schema["paths"]["/api/lan/admin/settings"]) == {"get", "post", "put"}
    for method in ("GET", "POST", "PUT"):
        selected = [
            r for r in routes if r.path == "/api/lan/admin/settings" and method in r.methods
        ]
        assert len(selected) == 1
        assert selected[0].endpoint.__module__ == lan_admin_routes.__name__


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
def test_remote_admin_key_cannot_change_host_only_settings(mounted_lan, enabled, method):
    app, cfg, saved = mounted_lan
    cfg.enabled = enabled
    with TestClient(app, client=("192.0.2.10", 12345)) as client:
        kwargs = {} if method == "GET" else {"json": {"enabled": True}}
        response = client.request(method, "/api/lan/admin/settings", **kwargs)
    assert response.status_code == 403
    assert response.json()["detail"] == "admin_host_required"
    saved.assert_not_called()


def test_admin_host_reads_original_fields_and_secret_mask(mounted_lan):
    app, cfg, _ = mounted_lan
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.get("/api/lan/admin/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["secret_preview"] == cfg.license_secret[:4] + "***" + cfg.license_secret[-4:]
    assert (
        body["bootstrap_preview"]
        == cfg.admin_bootstrap_key[:4] + "***" + cfg.admin_bootstrap_key[-4:]
    )
    assert body["allowed_cidrs"] == cfg.allowed_cidrs
    assert set(body["source"]) == {
        "enabled",
        "license_secret",
        "admin_bootstrap_key",
        "allowed_cidrs",
    }


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_admin_host_empty_secret_still_rejected_and_valid_update_saved(mounted_lan, method):
    app, _, saved = mounted_lan
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        bad = client.request(method, "/api/lan/admin/settings", json={"license_secret": ""})
        assert bad.status_code == 400
        assert bad.json()["detail"] == "license_secret_too_short"
        saved.assert_not_called()
        good = client.request(
            method, "/api/lan/admin/settings", json={"allowed_cidrs": ["10.0.0.2/8"]}
        )
    assert good.status_code == 200
    saved.assert_called_once()
    assert saved.call_args.args[0].allowed_cidrs == ["10.0.0.0/8"]
    assert saved.call_args.kwargs == {"merge": True}
