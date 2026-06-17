"""Tests for app.fastapi_routes.lan_admin_routes — coverage ramp."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.lan_admin_routes import (
    IssueKeyRequest,
    SettingsUpdate,
    _is_admin_host_ip,
    _normalize_cidrs,
    require_admin,
    require_admin_host,
    router,
)


# ---------------------------------------------------------------------------
# _is_admin_host_ip
# ---------------------------------------------------------------------------
class TestIsAdminHostIp:
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_matching_ip(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=["192.168.1.1"])
        assert _is_admin_host_ip("192.168.1.1") is True

    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_non_matching_ip(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=["192.168.1.1"])
        assert _is_admin_host_ip("10.0.0.1") is False

    def test_none_ip(self):
        assert _is_admin_host_ip(None) is False

    def test_empty_ip(self):
        assert _is_admin_host_ip("") is False

    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_invalid_ip_string(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=["192.168.1.1"])
        assert _is_admin_host_ip("not-an-ip") is False

    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_empty_admin_hosts(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=[])
        assert _is_admin_host_ip("192.168.1.1") is False

    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_invalid_admin_host_entry_skipped(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=["not-an-ip", "192.168.1.1"])
        assert _is_admin_host_ip("192.168.1.1") is True

    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_blank_admin_host_entry_skipped(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=["", "  ", "192.168.1.1"])
        assert _is_admin_host_ip("192.168.1.1") is True

    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_none_in_admin_host_list(self, mock_cfg):
        mock_cfg.return_value = MagicMock(admin_host_ips=[None, "192.168.1.1"])
        assert _is_admin_host_ip("192.168.1.1") is True


# ---------------------------------------------------------------------------
# _normalize_cidrs
# ---------------------------------------------------------------------------
class TestNormalizeCidrs:
    def test_valid_cidr(self):
        result = _normalize_cidrs(["192.168.1.0/24"])
        assert result == ["192.168.1.0/24"]

    def test_deduplication(self):
        result = _normalize_cidrs(["192.168.1.0/24", "192.168.1.0/24"])
        assert result == ["192.168.1.0/24"]

    def test_empty_items_skipped(self):
        result = _normalize_cidrs(["", "  ", "10.0.0.0/8"])
        assert result == ["10.0.0.0/8"]

    def test_none_items_skipped(self):
        result = _normalize_cidrs([None, "10.0.0.0/8"])  # type: ignore[list-item]
        assert result == ["10.0.0.0/8"]

    def test_invalid_cidr_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _normalize_cidrs(["not-a-cidr"])
        assert exc_info.value.status_code == 400
        assert "invalid_cidr" in exc_info.value.detail

    def test_empty_list_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _normalize_cidrs([])
        assert exc_info.value.status_code == 400
        assert "allowed_cidrs_empty" in exc_info.value.detail

    def test_all_empty_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _normalize_cidrs(["", "  "])
        assert exc_info.value.status_code == 400

    def test_host_address_normalized(self):
        result = _normalize_cidrs(["192.168.1.1"])
        assert result == ["192.168.1.1/32"]

    def test_multiple_valid_cidrs(self):
        result = _normalize_cidrs(["10.0.0.0/8", "172.16.0.0/12"])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# require_admin_host
# ---------------------------------------------------------------------------
class TestRequireAdminHost:
    @patch("app.fastapi_routes.lan_admin_routes.get_client_ip")
    @patch("app.fastapi_routes.lan_admin_routes._is_admin_host_ip")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_admin_host_allowed(self, mock_cfg, mock_is_admin, mock_get_ip):
        mock_cfg.return_value = MagicMock(trusted_proxies=[])
        mock_get_ip.return_value = "192.168.1.1"
        mock_is_admin.return_value = True
        request = MagicMock()
        request.scope = {}
        result = require_admin_host(request)
        assert result["is_admin_host"] is True
        assert result["ip"] == "192.168.1.1"

    @patch("app.fastapi_routes.lan_admin_routes.get_client_ip")
    @patch("app.fastapi_routes.lan_admin_routes._is_admin_host_ip")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_non_admin_host_forbidden(self, mock_cfg, mock_is_admin, mock_get_ip):
        from fastapi import HTTPException

        mock_cfg.return_value = MagicMock(trusted_proxies=[])
        mock_get_ip.return_value = "10.0.0.1"
        mock_is_admin.return_value = False
        request = MagicMock()
        request.scope = {}
        with pytest.raises(HTTPException) as exc_info:
            require_admin_host(request)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------
class TestRequireAdmin:
    @patch("app.fastapi_routes.lan_admin_routes.get_client_ip")
    @patch("app.fastapi_routes.lan_admin_routes._is_admin_host_ip")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_admin_host_passes(self, mock_cfg, mock_is_admin, mock_get_ip):
        mock_cfg.return_value = MagicMock(trusted_proxies=[])
        mock_get_ip.return_value = "192.168.1.1"
        mock_is_admin.return_value = True
        request = MagicMock()
        request.scope = {"state": {}}
        result = require_admin(request)
        assert result["is_admin_host"] is True

    @patch("app.fastapi_routes.lan_admin_routes.get_client_ip")
    @patch("app.fastapi_routes.lan_admin_routes._is_admin_host_ip")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_admin_key_passes(self, mock_cfg, mock_is_admin, mock_get_ip):
        mock_cfg.return_value = MagicMock(trusted_proxies=[])
        mock_get_ip.return_value = "10.0.0.1"
        mock_is_admin.return_value = False
        request = MagicMock()
        request.scope = {"state": {"lan_is_admin": True, "lan_jti": "abc", "lan_key_id": 1}}
        result = require_admin(request)
        assert result["is_admin_key"] is True
        assert result["jti"] == "abc"
        assert result["key_id"] == 1

    @patch("app.fastapi_routes.lan_admin_routes.get_client_ip")
    @patch("app.fastapi_routes.lan_admin_routes._is_admin_host_ip")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_neither_admin_host_nor_key_forbidden(self, mock_cfg, mock_is_admin, mock_get_ip):
        from fastapi import HTTPException

        mock_cfg.return_value = MagicMock(trusted_proxies=[])
        mock_get_ip.return_value = "10.0.0.1"
        mock_is_admin.return_value = False
        request = MagicMock()
        request.scope = {"state": {"lan_is_admin": False}}
        with pytest.raises(HTTPException) as exc_info:
            require_admin(request)
        assert exc_info.value.status_code == 403

    @patch("app.fastapi_routes.lan_admin_routes.get_client_ip")
    @patch("app.fastapi_routes.lan_admin_routes._is_admin_host_ip")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_state_lan_client_ip_used(self, mock_cfg, mock_is_admin, mock_get_ip):
        mock_cfg.return_value = MagicMock(trusted_proxies=[])
        mock_is_admin.return_value = True
        request = MagicMock()
        request.scope = {"state": {"lan_client_ip": "192.168.1.1"}}
        result = require_admin(request)
        assert result["ip"] == "192.168.1.1"
        mock_get_ip.assert_not_called()


# ---------------------------------------------------------------------------
# Route integration tests (using dependency_overrides)
# ---------------------------------------------------------------------------
def _make_app_with_overrides(dep_override=None, dep_host_override=None):
    """Create a TestClient with dependency overrides for require_admin / require_admin_host."""
    app = FastAPI()
    app.include_router(router)
    if dep_override is not None:
        app.dependency_overrides[require_admin] = dep_override
    if dep_host_override is not None:
        app.dependency_overrides[require_admin_host] = dep_host_override
    return TestClient(app)


def _admin_actor():
    return {"ip": "192.168.1.1", "jti": "test-jti", "key_id": 1, "is_admin_host": True, "is_admin_key": False}


def _admin_host_actor():
    return {"ip": "192.168.1.1", "is_admin_host": True}


class TestWhoamiEndpoint:
    def test_whoami_returns_actor_info(self):
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/whoami")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["ip"] == "192.168.1.1"


class TestListKeysEndpoint:
    @patch("app.fastapi_routes.lan_admin_routes.to_dict_key")
    @patch("app.fastapi_routes.lan_admin_routes.list_keys")
    def test_list_keys_returns_data(self, mock_list, mock_to_dict):
        mock_key = MagicMock()
        mock_list.return_value = [mock_key]
        mock_to_dict.return_value = {"id": 1, "label": "test"}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 1

    @patch("app.fastapi_routes.lan_admin_routes.list_keys")
    def test_list_keys_exclude_revoked(self, mock_list):
        mock_list.return_value = []
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/keys?include_revoked=false")
        assert resp.status_code == 200
        mock_list.assert_called_once_with(include_revoked=False)


class TestIssueKeyEndpoint:
    @patch("app.fastapi_routes.lan_admin_routes.write_audit")
    @patch("app.fastapi_routes.lan_admin_routes.to_dict_key")
    @patch("app.fastapi_routes.lan_admin_routes.issue_key")
    def test_issue_key_success(self, mock_issue, mock_to_dict, mock_audit):
        mock_record = MagicMock()
        mock_record.id = 42
        mock_issue.return_value = ("plaintext123", mock_record)
        mock_to_dict.return_value = {"id": 42, "label": "test"}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.post("/api/lan/admin/keys", json={"label": "test", "is_admin": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["plaintext"] == "plaintext123"

    def test_issue_key_expires_in_past_rejected(self):
        client = _make_app_with_overrides(dep_override=_admin_actor)
        past_ts = int(time.time()) - 100
        resp = client.post("/api/lan/admin/keys", json={"label": "test", "expires_at": past_ts})
        assert resp.status_code == 400


class TestRevokeKeyEndpoint:
    @patch("app.fastapi_routes.lan_admin_routes.revoke_key")
    def test_revoke_key_success(self, mock_revoke):
        mock_revoke.return_value = True
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.delete("/api/lan/admin/keys/1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.fastapi_routes.lan_admin_routes.revoke_key")
    def test_revoke_key_not_found(self, mock_revoke):
        mock_revoke.return_value = False
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.delete("/api/lan/admin/keys/999")
        assert resp.status_code == 404


class TestListSessionsEndpoint:
    @patch("app.fastapi_routes.lan_admin_routes.to_dict_session")
    @patch("app.fastapi_routes.lan_admin_routes.list_sessions")
    def test_list_sessions_returns_data(self, mock_list, mock_to_dict):
        mock_session = MagicMock()
        mock_list.return_value = [mock_session]
        mock_to_dict.return_value = {"jti": "abc"}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestKickSessionEndpoint:
    @patch("app.fastapi_routes.lan_admin_routes.revoke_session")
    def test_kick_session_success(self, mock_revoke):
        mock_revoke.return_value = True
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.delete("/api/lan/admin/sessions/test-jti")
        assert resp.status_code == 200

    @patch("app.fastapi_routes.lan_admin_routes.revoke_session")
    def test_kick_session_not_found(self, mock_revoke):
        mock_revoke.return_value = False
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.delete("/api/lan/admin/sessions/nonexistent")
        assert resp.status_code == 404


class TestListAuditEndpoint:
    @patch("app.fastapi_routes.lan_admin_routes.to_dict_audit")
    @patch("app.fastapi_routes.lan_admin_routes.list_audit")
    def test_list_audit_returns_data(self, mock_list, mock_to_dict):
        mock_entry = MagicMock()
        mock_list.return_value = [mock_entry]
        mock_to_dict.return_value = {"action": "key.issue"}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestAccessRequestEndpoints:
    @patch("app.fastapi_routes.lan_admin_routes.to_dict_access_request")
    @patch("app.fastapi_routes.lan_admin_routes.list_access_requests")
    def test_list_access_requests(self, mock_list, mock_to_dict):
        mock_entry = MagicMock()
        mock_list.return_value = [mock_entry]
        mock_to_dict.return_value = {"id": 1}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/access-requests")
        assert resp.status_code == 200

    @patch("app.fastapi_routes.lan_admin_routes.to_dict_access_request")
    @patch("app.fastapi_routes.lan_admin_routes.approve_access_request")
    def test_approve_access_request_success(self, mock_approve, mock_to_dict):
        mock_approve.return_value = MagicMock()
        mock_to_dict.return_value = {"id": 1, "status": "approved"}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.post("/api/lan/admin/access-requests/1/approve", json={"note": "ok"})
        assert resp.status_code == 200

    @patch("app.fastapi_routes.lan_admin_routes.approve_access_request")
    def test_approve_access_request_not_found(self, mock_approve):
        mock_approve.return_value = None
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.post("/api/lan/admin/access-requests/999/approve", json={"note": "ok"})
        assert resp.status_code == 404

    @patch("app.fastapi_routes.lan_admin_routes.to_dict_access_request")
    @patch("app.fastapi_routes.lan_admin_routes.reject_access_request")
    def test_reject_access_request_success(self, mock_reject, mock_to_dict):
        mock_reject.return_value = MagicMock()
        mock_to_dict.return_value = {"id": 1, "status": "rejected"}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.post("/api/lan/admin/access-requests/1/reject", json={"note": "bad"})
        assert resp.status_code == 200

    @patch("app.fastapi_routes.lan_admin_routes.reject_access_request")
    def test_reject_access_request_not_found(self, mock_reject):
        mock_reject.return_value = None
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.post("/api/lan/admin/access-requests/999/reject", json={"note": "bad"})
        assert resp.status_code == 404


class TestAllowlistEndpoints:
    @patch("app.fastapi_routes.lan_admin_routes.to_dict_allowed_client")
    @patch("app.fastapi_routes.lan_admin_routes.list_allowed_clients")
    def test_list_allowlist(self, mock_list, mock_to_dict):
        mock_list.return_value = [MagicMock()]
        mock_to_dict.return_value = {"id": 1}
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.get("/api/lan/admin/allowlist")
        assert resp.status_code == 200

    @patch("app.fastapi_routes.lan_admin_routes.revoke_allowed_client")
    def test_revoke_allowlist_success(self, mock_revoke):
        mock_revoke.return_value = True
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.delete("/api/lan/admin/allowlist/1")
        assert resp.status_code == 200

    @patch("app.fastapi_routes.lan_admin_routes.revoke_allowed_client")
    def test_revoke_allowlist_not_found(self, mock_revoke):
        mock_revoke.return_value = False
        client = _make_app_with_overrides(dep_override=_admin_actor)
        resp = client.delete("/api/lan/admin/allowlist/999")
        assert resp.status_code == 404


class TestSettingsEndpoints:
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_get_settings_returns_config(self, mock_cfg):
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.is_secret_ready.return_value = True
        mock_config.license_secret = "secret12345678"
        mock_config.admin_bootstrap_key = "bootstrap12345"
        mock_config.allowed_cidrs = ["10.0.0.0/8"]
        mock_cfg.return_value = mock_config
        client = _make_app_with_overrides(dep_host_override=_admin_host_actor)
        with patch("app.security.lan_settings_store.load_overrides") as mock_load:
            mock_overrides = MagicMock()
            mock_overrides.enabled = None
            mock_overrides.license_secret = None
            mock_overrides.admin_bootstrap_key = None
            mock_overrides.allowed_cidrs = None
            mock_load.return_value = mock_overrides
            resp = client.get("/api/lan/admin/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True

    @patch("app.security.lan_config.reset_lan_config_cache")
    @patch("app.security.lan_settings_store.save_overrides")
    @patch("app.fastapi_routes.lan_admin_routes.get_lan_config")
    def test_update_settings_success(self, mock_cfg, mock_save, mock_reset):
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.is_secret_ready.return_value = True
        mock_config.license_secret = "newsecret123456"
        mock_config.admin_bootstrap_key = "bootstrap12345"
        mock_config.allowed_cidrs = ["10.0.0.0/8"]
        mock_cfg.return_value = mock_config
        client = _make_app_with_overrides(dep_host_override=_admin_host_actor)
        with patch("app.security.lan_settings_store.load_overrides") as mock_load:
            mock_overrides = MagicMock()
            mock_overrides.enabled = None
            mock_overrides.license_secret = None
            mock_overrides.admin_bootstrap_key = None
            mock_overrides.allowed_cidrs = None
            mock_load.return_value = mock_overrides
            resp = client.put(
                "/api/lan/admin/settings",
                json={"enabled": True, "allowed_cidrs": ["10.0.0.0/8"]},
            )
        assert resp.status_code == 200

    def test_update_settings_secret_too_short(self):
        client = _make_app_with_overrides(dep_host_override=_admin_host_actor)
        resp = client.put(
            "/api/lan/admin/settings",
            json={"license_secret": "short"},
        )
        assert resp.status_code == 400


class TestIssueKeyRequestModel:
    def test_defaults(self):
        req = IssueKeyRequest()
        assert req.label == ""
        assert req.is_admin is False
        assert req.expires_at is None
        assert req.plaintext is None

    def test_custom_values(self):
        req = IssueKeyRequest(label="test", is_admin=True, expires_at=9999999999, plaintext="abc")
        assert req.label == "test"
        assert req.is_admin is True


class TestSettingsUpdateModel:
    def test_defaults(self):
        upd = SettingsUpdate()
        assert upd.enabled is None
        assert upd.license_secret is None
        assert upd.admin_bootstrap_key is None
        assert upd.allowed_cidrs is None
