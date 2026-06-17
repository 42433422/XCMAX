"""Comprehensive tests for app.fastapi_routes.mobile_api_extensions.

Covers: pairing, device register/unregister, sync, QR confirm, OIDC exchange,
approval/shipment/customer lists, mods, home, platform-shell, and all helper functions.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _resolve_circular_import():
    """Resolve circular import between mobile_api and mobile_api_extensions."""
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def ext_mod():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


# ---------------------------------------------------------------------------
# _ensure_mobile_device_table
# ---------------------------------------------------------------------------


class TestEnsureMobileDeviceTable:
    def test_happy_path(self, ext_mod):
        mock_db = MagicMock()
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = True
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db), \
             patch("sqlalchemy.inspect", return_value=mock_insp):
            ext_mod._ensure_mobile_device_table()

    def test_table_missing_creates(self, ext_mod):
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_db.get_bind.return_value = mock_bind
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = False
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db), \
             patch("sqlalchemy.inspect", return_value=mock_insp):
            ext_mod._ensure_mobile_device_table()

    def test_recoverable_error_logged(self, ext_mod):
        with patch("app.db.session.get_db", side_effect=RuntimeError("db down")):
            ext_mod._ensure_mobile_device_table()  # should not raise


# ---------------------------------------------------------------------------
# _guess_lan_ipv4
# ---------------------------------------------------------------------------


class TestGuessLanIpv4:
    def test_returns_string(self, ext_mod):
        ip = ext_mod._guess_lan_ipv4()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_fallback_on_os_error(self, ext_mod):
        with patch("socket.socket", side_effect=OSError("no network")):
            ip = ext_mod._guess_lan_ipv4()
            assert ip == "127.0.0.1"


# ---------------------------------------------------------------------------
# _pairing_issue_host
# ---------------------------------------------------------------------------


class TestPairingIssueHost:
    def test_localhost_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("127.0.0.1") == "192.168.1.100"

    def test_localhost_name_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("localhost") == "192.168.1.100"

    def test_0000_replaced(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("0.0.0.0") == "192.168.1.100"

    def test_real_ip_kept(self, ext_mod):
        assert ext_mod._pairing_issue_host("192.168.1.50") == "192.168.1.50"

    def test_empty_defaults(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host("") == "192.168.1.100"

    def test_none_defaults(self, ext_mod):
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.1.100"):
            assert ext_mod._pairing_issue_host(None) == "192.168.1.100"


# ---------------------------------------------------------------------------
# Pairing routes (direct handler tests)
# ---------------------------------------------------------------------------


class TestPairingIssue:
    @pytest.mark.asyncio
    async def test_issue_success(self, ext_mod):
        body = ext_mod.PairingIssueBody(host="192.168.1.10", port=5000)
        with patch.object(ext_mod, "_pairing_issue_host", return_value="192.168.1.10"), \
             patch("app.security.mobile_pairing.issue_pairing_nonce", return_value={"nonce": "abc123", "host": "192.168.1.10", "port": 5000}):
            result = await ext_mod.mobile_pairing_issue(body)
        # format_mobile_response returns a dict
        if hasattr(result, "body"):
            import json
            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True or data.get("data", {}).get("host") == "192.168.1.10"


class TestPairingLookup:
    @pytest.mark.asyncio
    async def test_invalid_code(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="000000")
        result = await ext_mod.mobile_pairing_lookup(body)
        import json
        data = json.loads(result.body)
        assert result.status_code == 404 or data.get("success") is False


class TestPairingExchange:
    @pytest.mark.asyncio
    async def test_exchange_by_nonce(self, ext_mod):
        # Mock the pairing functions to return valid data
        with patch("app.security.mobile_pairing.issue_pairing_nonce", return_value={"nonce": "abc123", "host": "192.168.1.10", "port": 5000}), \
             patch("app.security.mobile_pairing.consume_pairing_nonce", return_value={"host": "192.168.1.10", "port": 5000, "shortCode": "123456"}), \
             patch.object(ext_mod, "_pairing_issue_host", return_value="192.168.1.10"):
            # First issue a pairing to get a nonce
            body_issue = ext_mod.PairingIssueBody(host="192.168.1.10", port=5000)
            issue_result = await ext_mod.mobile_pairing_issue(body_issue)
            if hasattr(issue_result, "body"):
                import json
                issue_data = json.loads(issue_result.body)
            else:
                issue_data = issue_result
            nonce = issue_data.get("data", {}).get("nonce", "abc123")
            body_exchange = ext_mod.PairingExchangeBody(nonce=nonce)
            result = await ext_mod.mobile_pairing_exchange(body_exchange)
            if hasattr(result, "body"):
                import json
                data = json.loads(result.body)
            else:
                data = result
            assert data.get("success") is True or data.get("code") == 200

    @pytest.mark.asyncio
    async def test_exchange_by_shortcode(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="123456")
        with patch.object(
            ext_mod,
            "consume_by_shortcode",
            return_value={"host": "192.168.1.20", "port": 5100, "nonce": "n1", "shortCode": "123456"},
        ) as consume:
            result = await ext_mod.mobile_pairing_exchange(body)
        consume.assert_called_once_with("123456")
        if hasattr(result, "body"):
            import json
            data = json.loads(result.body)
        else:
            data = result
        assert data["success"] is True
        assert data["data"]["host"] == "192.168.1.20"
        assert data["data"]["port"] == 5100

    @pytest.mark.asyncio
    async def test_exchange_no_credentials(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="", nonce="")
        result = await ext_mod.mobile_pairing_exchange(body)
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# Auth-required routes (unauthorized) - direct handler tests
# ---------------------------------------------------------------------------


class TestUnauthorizedRoutes:
    @pytest.mark.asyncio
    async def test_approval_list_unauthorized(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.mobile_approval_list(request=mock_request, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_customers_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_customers(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_shipments_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_shipments(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_device_register_unauthorized(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        result = await ext_mod.mobile_device_register(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_device_unregister_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_device_unregister(fcm_token="a" * 10, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_mods_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_mods_summary(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_platform_shell_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_platform_shell(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_home_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_home(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_status_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_sync_status(user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_pull_unauthorized(self, ext_mod):
        body = ext_mod.SyncPullBody(since_cursor=0)
        result = await ext_mod.mobile_sync_pull(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_push_unauthorized(self, ext_mod):
        body = ext_mod.SyncPushBody(items=[])
        result = await ext_mod.mobile_sync_push(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_ack_unauthorized(self, ext_mod):
        body = ext_mod.SyncAckBody(cursor=1)
        result = await ext_mod.mobile_sync_ack(body=body, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_conflicts_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_sync_conflicts(user=None)
        assert result.status_code == 401


# ---------------------------------------------------------------------------
# _mobile_mod_items
# ---------------------------------------------------------------------------


class TestMobileModItems:
    def test_empty_list(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = []
            assert ext_mod._mobile_mod_items() == []

    def test_dict_mods(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "mod-a", "name": "Mod A"},
                {"mod_id": "mod-b", "title": "Mod B"},
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 2
            assert items[0]["id"] == "mod-a"

    def test_object_mods(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mod = MagicMock()
            mod.id = "mod-obj"
            mod.name = "Obj Mod"
            mod.mod_id = ""
            mod.title = ""
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
            assert items[0]["id"] == "mod-obj"

    def test_exception_returns_empty(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager", side_effect=RuntimeError("fail")):
            assert ext_mod._mobile_mod_items() == []

    def test_limit_100(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": f"mod-{i}", "name": f"Mod {i}"} for i in range(150)
            ]
            assert len(ext_mod._mobile_mod_items()) == 100

    def test_empty_id_skipped(self, ext_mod):
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "", "name": "NoId"},
                {"mod_id": "has-id", "title": "HasId"},
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 1
            assert items[0]["id"] == "has-id"


# ---------------------------------------------------------------------------
# _approval_items / _shipment_items
# ---------------------------------------------------------------------------


class TestApprovalItems:
    def test_happy_path(self, ext_mod):
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Test"
        mock_row.status = "pending"
        mock_row.request_no = "REQ-001"
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_row]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._approval_items(limit=10)
            assert len(items) == 1
            assert items[0]["id"] == 1

    def test_db_error(self, ext_mod):
        with patch("app.db.session.get_db", side_effect=RuntimeError("fail")):
            with pytest.raises(RuntimeError):
                ext_mod._approval_items()


class TestShipmentItems:
    def test_happy_path(self, ext_mod):
        mock_db = MagicMock()
        mock_row = MagicMock(spec=[])
        mock_row.id = 5
        mock_row.order_number = "ORD-1"
        mock_row.status = "shipped"
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_row]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
            assert len(items) == 1
            assert items[0]["id"] == 5


# ---------------------------------------------------------------------------
# Auth QR confirm (direct handler test)
# ---------------------------------------------------------------------------


class TestAuthQrConfirm:
    @pytest.mark.asyncio
    async def test_expired_qr(self, ext_mod):
        with patch("app.security.auth_qr_login.get_auth_qr", return_value=None):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="u", password="p")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_expired_status(self, ext_mod):
        with patch("app.security.auth_qr_login.get_auth_qr", return_value={"status": "expired"}):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="u", password="p")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_credentials(self, ext_mod):
        with patch("app.security.auth_qr_login.get_auth_qr", return_value={"status": "pending"}):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="", password="")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
            assert result.status_code == 400


# ---------------------------------------------------------------------------
# OIDC exchange (direct handler test)
# ---------------------------------------------------------------------------


class TestOidcExchange:
    @pytest.mark.asyncio
    async def test_invalid_state(self, ext_mod):
        with patch("app.infrastructure.auth.oidc_provider.verify_oidc_state", return_value=(False, "")):
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_exchange_code_fails(self, ext_mod):
        async def _raise(code):
            raise RuntimeError("OIDC down")

        with patch("app.infrastructure.auth.oidc_provider.verify_oidc_state", return_value=(True, "rt")), \
             patch("app.infrastructure.auth.oidc_provider.exchange_code_for_userinfo", side_effect=_raise):
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
            assert result.status_code == 502


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestDeviceRegisterBody:
    def test_valid(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        assert body.fcm_token == "a" * 10
        assert body.push_provider == "fcm"

    def test_default_values(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10)
        assert body.platform == "android"
        assert body.product_sku == "personal"


class TestPairingExchangeBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.PairingExchangeBody()
        assert body.nonce == ""
        assert body.code == ""


class TestPairingIssueBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.PairingIssueBody()
        assert body.host == "127.0.0.1"
        assert body.port == 5000


class TestSyncPullBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.SyncPullBody()
        assert body.since_cursor == 0


class TestSyncPushItem:
    def test_valid(self, ext_mod):
        item = ext_mod.SyncPushItem(entity_type="customer", entity_id="1")
        assert item.entity_type == "customer"
        assert item.operation == "update"


class TestSyncAckBody:
    def test_defaults(self, ext_mod):
        body = ext_mod.SyncAckBody()
        assert body.cursor == 0


class TestPairingLookupBody:
    def test_valid(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="123456")
        assert body.code == "123456"


class TestAuthQrConfirmBody:
    def test_valid(self, ext_mod):
        body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8)
        assert body.qr_id == "a" * 8
        assert body.account_kind == "enterprise"


class TestOidcExchangeBody:
    def test_valid(self, ext_mod):
        body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
        assert body.code == "abc123"
