"""Coverage ramp for app/fastapi_routes/lan_settings_routes.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.fastapi_routes import lan_settings_routes as mod
from app.fastapi_routes.lan_settings_routes import (
    LanSettingsOverride,
    LanSettingsUpdate,
    LanSettingsView,
    _authorize,
    _describe_sources,
    _is_admin_host_ip,
    _mask,
    _normalize_cidrs,
    get_settings,
    router,
    update_settings,
)
from app.security.lan_config import LanConfig, reset_lan_config_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(
    *,
    enabled: bool = False,
    admin_host_ips: tuple[str, ...] = ("127.0.0.1", "::1"),
    license_secret: str = "",
    admin_bootstrap_key: str = "",
    allowed_cidrs: tuple[str, ...] = ("127.0.0.1/32",),
    trusted_proxies: tuple[str, ...] = (),
) -> LanConfig:
    return LanConfig(
        enabled=enabled,
        allowed_cidrs=allowed_cidrs,
        trusted_proxies=trusted_proxies,
        admin_host_ips=admin_host_ips,
        bypass_paths=("/api/lan/admin/settings",),
        license_secret=license_secret,
        token_ttl_seconds=3600,
        admin_bootstrap_key=admin_bootstrap_key,
        license_db_path=MagicMock(),
        cookie_name="fhd_lan_token",
        cookie_secure=False,
        cookie_samesite="Lax",
        cookie_domain="",
        static_prefixes=(),
    )


def _make_request(
    *,
    ip: str | None = "127.0.0.1",
    is_admin: bool = False,
    state_ip: str | None = None,
) -> Request:
    scope = {
        "type": "http",
        "headers": [],
        "method": "GET",
        "path": "/",
        "client": (ip, 0) if ip else None,
        "state": {},
    }
    state = {}
    if state_ip is not None:
        state["lan_client_ip"] = state_ip
    if is_admin:
        state["lan_is_admin"] = True
    scope["state"] = state
    # Use a dict-like for scope["state"] to allow .get
    return Request(scope)


# ---------------------------------------------------------------------------
# _mask
# ---------------------------------------------------------------------------


class TestMask:
    def test_empty(self) -> None:
        assert _mask("") == ""

    def test_short_secret_all_masked(self) -> None:
        assert _mask("abc") == "***"
        assert _mask("12345678") == "********"

    def test_long_secret_partial(self) -> None:
        # len > 8: first 2 + stars + last 2
        out = _mask("abcdefghij")  # len 10
        assert out == "ab******ij"
        assert len(out) == 10

    def test_exactly_nine(self) -> None:
        out = _mask("abcdefghi")  # len 9
        assert out == "ab*****hi"


# ---------------------------------------------------------------------------
# _is_admin_host_ip
# ---------------------------------------------------------------------------


class TestIsAdminHostIp:
    def test_none_returns_false(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg()
            assert _is_admin_host_ip(None) is False

    def test_empty_returns_false(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg()
            assert _is_admin_host_ip("") is False

    def test_invalid_ip_returns_false(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg()
            assert _is_admin_host_ip("not-an-ip") is False

    def test_match(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg(admin_host_ips=("127.0.0.1",))
            assert _is_admin_host_ip("127.0.0.1") is True

    def test_no_match(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg(admin_host_ips=("127.0.0.1",))
            assert _is_admin_host_ip("10.0.0.1") is False

    def test_invalid_entry_in_admin_hosts_skipped(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg(admin_host_ips=("not-an-ip", "127.0.0.1"))
            assert _is_admin_host_ip("127.0.0.1") is True

    def test_empty_entry_in_admin_hosts_skipped(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg(admin_host_ips=("", "  ", "127.0.0.1"))
            assert _is_admin_host_ip("127.0.0.1") is True

    def test_ipv6_match(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config") as m:
            m.return_value = _make_cfg(admin_host_ips=("::1",))
            assert _is_admin_host_ip("::1") is True


# ---------------------------------------------------------------------------
# _authorize
# ---------------------------------------------------------------------------


class TestAuthorize:
    def test_lan_disabled_admin_host_ok(self) -> None:
        cfg = _make_cfg(enabled=False, admin_host_ips=("127.0.0.1",))
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config", return_value=cfg):
            req = _make_request(ip="127.0.0.1")
            out = _authorize(req)
        assert out["is_admin_host"] is True
        assert out["is_admin_key"] is False

    def test_lan_disabled_non_admin_host_forbidden(self) -> None:
        cfg = _make_cfg(enabled=False, admin_host_ips=("127.0.0.1",))
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config", return_value=cfg):
            req = _make_request(ip="10.0.0.99")
            with pytest.raises(HTTPException) as ei:
                _authorize(req)
        assert ei.value.status_code == 403
        assert ei.value.detail == "admin_host_required"

    def test_lan_enabled_admin_host_ok(self) -> None:
        cfg = _make_cfg(enabled=True, admin_host_ips=("127.0.0.1",))
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config", return_value=cfg):
            req = _make_request(ip="127.0.0.1")
            out = _authorize(req)
        assert out["is_admin_host"] is True

    def test_lan_enabled_admin_key_ok(self) -> None:
        cfg = _make_cfg(enabled=True, admin_host_ips=("127.0.0.1",))
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config", return_value=cfg):
            req = _make_request(ip="10.0.0.99", is_admin=True)
            out = _authorize(req)
        assert out["is_admin_key"] is True
        assert out["is_admin_host"] is False

    def test_lan_enabled_neither_forbidden(self) -> None:
        cfg = _make_cfg(enabled=True, admin_host_ips=("127.0.0.1",))
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config", return_value=cfg):
            req = _make_request(ip="10.0.0.99")
            with pytest.raises(HTTPException) as ei:
                _authorize(req)
        assert ei.value.status_code == 403
        assert ei.value.detail == "admin_required"

    def test_state_ip_overrides_socket(self) -> None:
        cfg = _make_cfg(enabled=False, admin_host_ips=("127.0.0.1",))
        with patch("app.fastapi_routes.lan_settings_routes.get_lan_config", return_value=cfg):
            # socket peer is 10.0.0.99 but state says 127.0.0.1
            req = _make_request(ip="10.0.0.99", state_ip="127.0.0.1")
            out = _authorize(req)
        assert out["is_admin_host"] is True
        assert out["ip"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# _normalize_cidrs
# ---------------------------------------------------------------------------


class TestNormalizeCidrs:
    def test_single_valid(self) -> None:
        out = _normalize_cidrs(["192.168.1.0/24"])
        assert out == ["192.168.1.0/24"]

    def test_dedup(self) -> None:
        out = _normalize_cidrs(["192.168.1.0/24", "192.168.1.0/24"])
        assert out == ["192.168.1.0/24"]

    def test_strips_whitespace(self) -> None:
        out = _normalize_cidrs(["  192.168.1.0/24  "])
        assert out == ["192.168.1.0/24"]

    def test_skips_empty(self) -> None:
        out = _normalize_cidrs(["", "  ", "192.168.1.0/24"])
        assert out == ["192.168.1.0/24"]

    def test_invalid_raises_400(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _normalize_cidrs(["not-a-cidr"])
        assert ei.value.status_code == 400
        assert "invalid_cidr" in ei.value.detail

    def test_empty_after_filter_raises_400(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _normalize_cidrs(["", "  "])
        assert ei.value.status_code == 400
        assert ei.value.detail == "allowed_cidrs_empty"

    def test_normalizes_non_strict(self) -> None:
        # host bits set -> normalized to network
        out = _normalize_cidrs(["192.168.1.5/24"])
        assert out == ["192.168.1.0/24"]

    def test_ipv6(self) -> None:
        out = _normalize_cidrs(["::1/128"])
        assert out == ["::1/128"]


# ---------------------------------------------------------------------------
# _describe_sources
# ---------------------------------------------------------------------------


class TestDescribeSources:
    def test_all_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LAN_LICENSE_SECRET", raising=False)
        monkeypatch.delenv("LAN_ADMIN_BOOTSTRAP_KEY", raising=False)
        monkeypatch.delenv("LAN_ALLOWED_CIDRS", raising=False)
        with patch("app.fastapi_routes.lan_settings_routes.load_overrides") as m:
            m.return_value = LanSettingsOverride()
            out = _describe_sources()
        assert out["enabled"] == "env"
        assert out["license_secret"] == "unset"
        assert out["admin_bootstrap_key"] == "unset"
        assert out["allowed_cidrs"] == "default"

    def test_env_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LAN_LICENSE_SECRET", "supersecret")
        monkeypatch.setenv("LAN_ADMIN_BOOTSTRAP_KEY", "bootstrap123")
        monkeypatch.setenv("LAN_ALLOWED_CIDRS", "10.0.0.0/8")
        with patch("app.fastapi_routes.lan_settings_routes.load_overrides") as m:
            m.return_value = LanSettingsOverride()
            out = _describe_sources()
        assert out["license_secret"] == "env"
        assert out["admin_bootstrap_key"] == "env"
        assert out["allowed_cidrs"] == "env"

    def test_file_sources(self) -> None:
        with patch("app.fastapi_routes.lan_settings_routes.load_overrides") as m:
            m.return_value = LanSettingsOverride(
                enabled=True,
                license_secret="file-secret",
                admin_bootstrap_key="file-bootstrap",
                allowed_cidrs=["10.0.0.0/8"],
            )
            out = _describe_sources()
        assert out["enabled"] == "file"
        assert out["license_secret"] == "file"
        assert out["admin_bootstrap_key"] == "file"
        assert out["allowed_cidrs"] == "file"

    def test_empty_string_secret_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LAN_LICENSE_SECRET", raising=False)
        with patch("app.fastapi_routes.lan_settings_routes.load_overrides") as m:
            m.return_value = LanSettingsOverride(license_secret="")
            out = _describe_sources()
        assert out["license_secret"] == "unset"


# ---------------------------------------------------------------------------
# Routes via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a TestClient with LAN disabled and admin host = 127.0.0.1."""
    cfg = _make_cfg(enabled=False, admin_host_ips=("127.0.0.1",))
    monkeypatch.setattr(mod, "get_lan_config", lambda: cfg)
    # Also patch within lan_settings_routes module-level reference
    monkeypatch.setattr(
        "app.fastapi_routes.lan_settings_routes.get_lan_config", lambda: cfg
    )
    # Patch _authorize to always succeed (TestClient uses "testclient" as client IP,
    # which is not in admin_host_ips, so we bypass authorization for route tests)
    monkeypatch.setattr(
        "app.fastapi_routes.lan_settings_routes._authorize",
        lambda request: {"ip": "127.0.0.1", "is_admin_host": True, "is_admin_key": False},
    )
    # Patch load/save to no-op
    monkeypatch.setattr(
        "app.fastapi_routes.lan_settings_routes.load_overrides",
        lambda: LanSettingsOverride(),
    )
    monkeypatch.setattr(
        "app.fastapi_routes.lan_settings_routes.save_overrides",
        lambda update, merge=True: update,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.lan_settings_routes.write_audit",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.lan_settings_routes.reset_lan_config_cache",
        lambda: None,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestGetSettingsRoute:
    def test_get_settings_success(self, app_client: TestClient) -> None:
        r = app_client.get("/api/lan/admin/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["secret_ready"] is False
        assert body["secret_length"] == 0
        assert body["secret_preview"] == ""
        assert body["bootstrap_set"] is False
        assert body["allowed_cidrs"] == ["127.0.0.1/32"]

    def test_get_settings_unauthorized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _make_cfg(enabled=False, admin_host_ips=("127.0.0.1",))
        monkeypatch.setattr(mod, "get_lan_config", lambda: cfg)
        monkeypatch.setattr(
            "app.fastapi_routes.lan_settings_routes.get_lan_config", lambda: cfg
        )
        monkeypatch.setattr(
            "app.fastapi_routes.lan_settings_routes.load_overrides",
            lambda: LanSettingsOverride(),
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)
        # Override the request scope to use a non-admin IP
        # TestClient always uses 127.0.0.1 as client; we need to patch _authorize
        with patch(
            "app.fastapi_routes.lan_settings_routes._authorize",
            side_effect=HTTPException(status_code=403, detail="admin_host_required"),
        ):
            r = client.get("/api/lan/admin/settings")
        assert r.status_code == 403


class TestUpdateSettingsRoute:
    def test_update_no_changes(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False

    def test_update_put_alias(self, app_client: TestClient) -> None:
        r = app_client.put(
            "/api/lan/admin/settings",
            json={},
        )
        assert r.status_code == 200

    def test_update_secret_too_short(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"license_secret": "short"},
        )
        assert r.status_code == 400
        assert r.json()["detail"] == "license_secret_too_short"

    def test_update_secret_valid_length(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"license_secret": "longenoughsecret"},
        )
        assert r.status_code == 200

    def test_update_secret_empty_clears(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"license_secret": ""},
        )
        assert r.status_code == 200

    def test_update_invalid_cidr(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"allowed_cidrs": ["not-a-cidr"]},
        )
        assert r.status_code == 400
        assert "invalid_cidr" in r.json()["detail"]

    def test_update_empty_cidrs_list(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"allowed_cidrs": []},
        )
        assert r.status_code == 400
        assert r.json()["detail"] == "allowed_cidrs_empty"

    def test_update_valid_cidrs(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"allowed_cidrs": ["10.0.0.0/8", "192.168.0.0/16"]},
        )
        assert r.status_code == 200

    def test_update_enable_without_secret(self, app_client: TestClient) -> None:
        # Enable LAN but no secret provided and no existing/env secret
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"enabled": True},
        )
        assert r.status_code == 400
        assert r.json()["detail"] == "license_secret_required"

    def test_update_enable_with_secret(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"enabled": True, "license_secret": "longenoughsecret"},
        )
        assert r.status_code == 200

    def test_update_bootstrap_key(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"admin_bootstrap_key": "bootstrap-key"},
        )
        assert r.status_code == 200

    def test_update_bootstrap_key_empty(self, app_client: TestClient) -> None:
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"admin_bootstrap_key": ""},
        )
        assert r.status_code == 200

    def test_update_audit_failure_swallowed(self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        # write_audit raises a recoverable error -> should be swallowed
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        def _raise(**kw):
            raise ValueError("audit db locked")

        monkeypatch.setattr(
            "app.fastapi_routes.lan_settings_routes.write_audit", _raise
        )
        r = app_client.post(
            "/api/lan/admin/settings",
            json={"license_secret": "longenoughsecret"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestLanSettingsUpdateModel:
    def test_defaults_all_none(self) -> None:
        m = LanSettingsUpdate()
        assert m.enabled is None
        assert m.license_secret is None
        assert m.admin_bootstrap_key is None
        assert m.allowed_cidrs is None

    def test_set_fields(self) -> None:
        m = LanSettingsUpdate(
            enabled=True,
            license_secret="x" * 20,
            admin_bootstrap_key="key",
            allowed_cidrs=["10.0.0.0/8"],
        )
        assert m.enabled is True
        assert m.license_secret == "x" * 20
        assert m.admin_bootstrap_key == "key"
        assert m.allowed_cidrs == ["10.0.0.0/8"]

    def test_secret_too_long_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LanSettingsUpdate(license_secret="x" * 257)


class TestLanSettingsViewModel:
    def test_defaults(self) -> None:
        m = LanSettingsView(
            enabled=False,
            secret_ready=False,
            secret_length=0,
            secret_preview="",
            bootstrap_set=False,
            bootstrap_length=0,
            bootstrap_preview="",
        )
        assert m.allowed_cidrs == []
        assert m.source == {}
