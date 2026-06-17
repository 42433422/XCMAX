"""Tests for app.fastapi_routes.lan_routes."""
from __future__ import annotations

import time
from ipaddress import ip_network
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.fastapi_routes.lan_routes import (
    _ip_in_admin_hosts,
    _ip_in_cidrs,
    _clear_token_cookie,
    _set_token_cookie,
    router,
)


# ---------------------------------------------------------------------------
# _ip_in_admin_hosts
# ---------------------------------------------------------------------------
class TestIpInAdminHosts:
    def test_matching_ip(self):
        assert _ip_in_admin_hosts("192.168.1.1", ("192.168.1.1",)) is True

    def test_non_matching_ip(self):
        assert _ip_in_admin_hosts("192.168.1.2", ("192.168.1.1",)) is False

    def test_none_ip(self):
        assert _ip_in_admin_hosts(None, ("192.168.1.1",)) is False

    def test_empty_ip(self):
        assert _ip_in_admin_hosts("", ("192.168.1.1",)) is False

    def test_invalid_ip(self):
        assert _ip_in_admin_hosts("not-an-ip", ("192.168.1.1",)) is False

    def test_empty_admin_hosts(self):
        assert _ip_in_admin_hosts("192.168.1.1", ()) is False

    def test_invalid_admin_host_entry(self):
        assert _ip_in_admin_hosts("192.168.1.1", ("not-an-ip",)) is False

    def test_blank_admin_host_entry_skipped(self):
        assert _ip_in_admin_hosts("192.168.1.1", ("", "  ")) is False


# ---------------------------------------------------------------------------
# _ip_in_cidrs
# ---------------------------------------------------------------------------
class TestIpInCidrs:
    def test_ip_in_cidr(self):
        net = ip_network("192.168.1.0/24")
        assert _ip_in_cidrs("192.168.1.100", [net]) is True

    def test_ip_not_in_cidr(self):
        net = ip_network("10.0.0.0/24")
        assert _ip_in_cidrs("192.168.1.100", [net]) is False

    def test_none_ip(self):
        assert _ip_in_cidrs(None, []) is False

    def test_empty_ip(self):
        assert _ip_in_cidrs("", []) is False

    def test_invalid_ip(self):
        net = ip_network("192.168.1.0/24")
        assert _ip_in_cidrs("not-an-ip", [net]) is False

    def test_empty_cidrs(self):
        assert _ip_in_cidrs("192.168.1.1", []) is False

    def test_invalid_cidr_handled(self):
        result = _ip_in_cidrs("192.168.1.1", ["not-a-cidr"])
        assert result is False


# ---------------------------------------------------------------------------
# _set_token_cookie / _clear_token_cookie
# ---------------------------------------------------------------------------
class TestTokenCookie:
    def test_set_token_cookie(self):
        mock_cfg = MagicMock()
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.cookie_secure = False
        mock_cfg.cookie_samesite = "lax"
        mock_cfg.cookie_domain = None

        mock_response = MagicMock()

        with patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg):
            _set_token_cookie(mock_response, "token123", 3600)

        mock_response.set_cookie.assert_called_once()

    def test_clear_token_cookie(self):
        mock_cfg = MagicMock()
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.cookie_domain = None

        mock_response = MagicMock()

        with patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg):
            _clear_token_cookie(mock_response)

        mock_response.delete_cookie.assert_called_once()


# ---------------------------------------------------------------------------
# Route integration tests (using TestClient on the router)
# ---------------------------------------------------------------------------
def _make_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app


class TestHostInfoRoute:
    def test_host_info_returns_200(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.admin_bootstrap_key = None
        mock_cfg.has_any_active_key = False
        mock_cfg.has_admin_key = False
        mock_cfg.allowed_cidrs = ["192.168.0.0/16"]
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.token_ttl_seconds = 3600
        mock_cfg.admin_host_ips = ()
        mock_cfg.trusted_proxies = ()

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.has_any_active_key", return_value=False),
            patch("app.fastapi_routes.lan_routes.has_any_admin_key", return_value=False),
        ):
            resp = client.get("/api/lan/host-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True


class TestStatusRoute:
    def test_status_returns_200(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = []
        mock_cfg.admin_host_ips = ()
        mock_cfg.is_secret_ready.return_value = False

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="10.0.0.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=False),
        ):
            resp = client.get("/api/lan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestActivateRoute:
    def test_activate_disabled_lan(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = False

        with patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg):
            resp = client.post("/api/lan/activate", json={"key": "test-key"})
        assert resp.status_code == 400

    def test_activate_misconfigured_secret(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = False

        with patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg):
            resp = client.post("/api/lan/activate", json={"key": "test-key"})
        assert resp.status_code == 503

    def test_activate_blocked_ip(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = []
        mock_cfg.admin_host_ips = ()

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="1.2.3.4"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=False),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "test-key"})
        assert resp.status_code == 403

    def test_activate_bad_key(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = [ip_network("192.168.0.0/16")]
        mock_cfg.admin_host_ips = ()
        mock_cfg.admin_bootstrap_key = None

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=True),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.find_key_by_plaintext", return_value=None),
            patch("app.fastapi_routes.lan_routes.has_any_active_key", return_value=True),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "bad-key"})
        assert resp.status_code == 401

    def test_activate_revoked_key(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = [ip_network("192.168.0.0/16")]
        mock_cfg.admin_host_ips = ()

        record = MagicMock()
        record.id = 1
        record.revoked_at = time.time()
        record.expires_at = None
        record.is_admin = False

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=True),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.find_key_by_plaintext", return_value=record),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "revoked-key"})
        assert resp.status_code == 401

    def test_activate_expired_key(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = [ip_network("192.168.0.0/16")]
        mock_cfg.admin_host_ips = ()

        record = MagicMock()
        record.id = 1
        record.revoked_at = None
        record.expires_at = int(time.time()) - 100  # expired
        record.is_admin = False

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=True),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.find_key_by_plaintext", return_value=record),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "expired-key"})
        assert resp.status_code == 401

    def test_activate_non_admin_without_allowlist(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = [ip_network("192.168.0.0/16")]
        mock_cfg.admin_host_ips = ()

        record = MagicMock()
        record.id = 1
        record.revoked_at = None
        record.expires_at = None
        record.is_admin = False

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=False),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.find_key_by_plaintext", return_value=record),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "user-key"})
        assert resp.status_code == 403

    def test_activate_success_with_admin_key(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = [ip_network("192.168.0.0/16")]
        mock_cfg.admin_host_ips = ()
        mock_cfg.license_secret = "test-secret"
        mock_cfg.token_ttl_seconds = 3600
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.cookie_secure = False
        mock_cfg.cookie_samesite = "lax"
        mock_cfg.cookie_domain = None

        record = MagicMock()
        record.id = 1
        record.revoked_at = None
        record.expires_at = None
        record.is_admin = True

        mock_payload = MagicMock()
        mock_payload.jti = "jti-123"
        mock_payload.iat = int(time.time())
        mock_payload.exp = int(time.time()) + 3600
        mock_payload.kid = "1"

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=True),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.find_key_by_plaintext", return_value=record),
            patch("app.fastapi_routes.lan_routes.mark_key_used"),
            patch("app.fastapi_routes.lan_routes.issue_token", return_value=("token123", mock_payload)),
            patch("app.fastapi_routes.lan_routes.record_session"),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "admin-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_admin"] is True

    def test_activate_bootstrap_key(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.is_secret_ready.return_value = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = [ip_network("192.168.0.0/16")]
        mock_cfg.admin_host_ips = ()
        mock_cfg.license_secret = "test-secret"
        mock_cfg.token_ttl_seconds = 3600
        mock_cfg.admin_bootstrap_key = "bootstrap-secret"
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.cookie_secure = False
        mock_cfg.cookie_samesite = "lax"
        mock_cfg.cookie_domain = None

        new_key = MagicMock()
        new_key.id = 99

        mock_payload = MagicMock()
        mock_payload.jti = "jti-bootstrap"
        mock_payload.iat = int(time.time())
        mock_payload.exp = int(time.time()) + 3600
        mock_payload.kid = "99"

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=True),
            patch("app.fastapi_routes.lan_routes.ensure_schema"),
            patch("app.fastapi_routes.lan_routes.find_key_by_plaintext", return_value=None),
            patch("app.fastapi_routes.lan_routes.has_any_active_key", return_value=False),
            patch("app.fastapi_routes.lan_routes.issue_key", return_value=("raw", new_key)),
            patch("app.fastapi_routes.lan_routes.issue_token", return_value=("token123", mock_payload)),
            patch("app.fastapi_routes.lan_routes.record_session"),
            patch("app.fastapi_routes.lan_routes.write_audit"),
        ):
            resp = client.post("/api/lan/activate", json={"key": "bootstrap-secret"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is True


class TestLogoutRoute:
    def test_logout_returns_success(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.cookie_name = "lan_token"
        mock_cfg.is_secret_ready.return_value = False
        mock_cfg.trusted_proxies = ()

        with patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg):
            resp = client.post("/api/lan/logout")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestAccessRequestRoute:
    def test_request_access_disabled(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = False

        with patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg):
            resp = client.post("/api/lan/access-requests", json={"device_label": "test"})
        assert resp.status_code == 400

    def test_request_access_already_allowed(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.trusted_proxies = ()

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="192.168.1.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=True),
            patch("app.fastapi_routes.lan_routes.get_latest_access_request_by_ip", return_value=None),
        ):
            resp = client.post("/api/lan/access-requests", json={"device_label": "test"})
        assert resp.status_code == 200
        assert resp.json()["already_allowed"] is True


class TestMyAccessRequestRoute:
    def test_my_access_request_returns_200(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.trusted_proxies = ()
        mock_cfg.cidr_objects.return_value = []

        with (
            patch("app.fastapi_routes.lan_routes.get_lan_config", return_value=mock_cfg),
            patch("app.fastapi_routes.lan_routes.get_client_ip", return_value="10.0.0.1"),
            patch("app.fastapi_routes.lan_routes.is_ip_explicitly_allowed", return_value=False),
            patch("app.fastapi_routes.lan_routes.get_latest_access_request_by_ip", return_value=None),
        ):
            resp = client.get("/api/lan/access-requests/mine")
        assert resp.status_code == 200
