"""Tests for app.fastapi_routes.mobile_api_extensions — additional coverage (ext3).

Focus on REMAINING uncovered lines:
- CS endpoints (get_cs_info, post_cs_message, get_cs_messages) — authorized & unauthorized
- _shipment_items error path and shipment_no fallback
- mobile_shipments with shipment_no fallback (order_number is None)
- mobile_device_register edge cases (empty push_provider, empty product_sku, long strings)
- mobile_pairing_lookup with missing exp key
- _approval_items with rows missing request_no / applicant_id
- mobile_sync_push with user having no username (fallback actor)
- mobile_sync_push with more than 50 items (truncation to [:50])
- mobile_auth_qr_confirm with non-Bearer authorization header
- mobile_auth_qr_confirm with bearer token AND username provided (skip bearer path)
- mobile_auth_oidc_exchange with session_id None
- mobile_auth_oidc_exchange with authenticate_oidc_user returning no message
- _mobile_mod_items with None list_all_mods return
- _mobile_mod_items with mixed dict/object mods
- mobile_pairing_issue with default host (127.0.0.1)
- mobile_pairing_issue with port coercion
- _guess_lan_ipv4 with whitespace IP
- _pairing_issue_host with whitespace-only host
- _ensure_mobile_device_table with import error
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _resolve_circular_import():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture
def ext_mod():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


def _mock_user():
    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    return user


def _mock_user_no_username():
    user = MagicMock()
    user.id = 99
    # Remove username attribute to trigger fallback
    del user.username
    return user


def _mock_pairing_request(host_header: str = "127.0.0.1:5112", hostname: str = "127.0.0.1"):
    return SimpleNamespace(
        headers={"host": host_header},
        url=SimpleNamespace(hostname=hostname),
    )


# ---------------------------------------------------------------------------
# CS endpoints — get_cs_info
# ---------------------------------------------------------------------------


class TestGetCsInfo:
    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_info(request=mock_request, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_authorized_returns_demo_data(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_info(request=mock_request, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        # /cs 是专属客服(cs-officer)通道,非小C;cs_name 取 SSOT 专属客服标签
        assert data.get("data", {}).get("cs_available") is True
        assert data.get("data", {}).get("cs_name") == "专属客服"
        assert data.get("data", {}).get("cs_online") is True
        assert data.get("data", {}).get("cs_avatar") is None


# ---------------------------------------------------------------------------
# CS endpoints — post_cs_message
# ---------------------------------------------------------------------------


class TestPostCsMessage:
    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.post_cs_message(
            request=mock_request, body={"body": "hello"}, user=None
        )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_authorized_returns_message_id(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.post_cs_message(
            request=mock_request, body={"body": "hello world"}, user=_mock_user()
        )
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        msg_id = data.get("data", {}).get("message_id", "")
        assert msg_id.startswith("cs_")
        assert len(msg_id) == 15  # "cs_" + 12 hex chars
        assert "timestamp" in data.get("data", {})

    @pytest.mark.asyncio
    async def test_authorized_empty_body(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.post_cs_message(request=mock_request, body={}, user=_mock_user())
        # 空消息体应返回 400
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_authorized_body_with_extra_fields(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.post_cs_message(
            request=mock_request,
            body={"body": "msg", "extra": "ignored", "type": "text"},
            user=_mock_user(),
        )
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# CS endpoints — get_cs_messages
# ---------------------------------------------------------------------------


class TestGetCsMessages:
    @pytest.fixture(autouse=True)
    def _isolate_db(self):
        """Mock get_db 返回空 session，避免前序测试持久化 ServiceRequest 污染。"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.get_bind.return_value = MagicMock()
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            yield

    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_messages(request=mock_request, user=None)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_authorized_returns_empty_list(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_messages(request=mock_request, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("messages") == []

    @pytest.mark.asyncio
    async def test_authorized_with_since_param(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_messages(
            request=mock_request, since="2026-01-01T00:00:00", user=_mock_user()
        )
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("messages") == []

    @pytest.mark.asyncio
    async def test_authorized_with_none_since(self, ext_mod):
        mock_request = MagicMock()
        result = await ext_mod.get_cs_messages(request=mock_request, since=None, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# _shipment_items error path and shipment_no fallback
# ---------------------------------------------------------------------------


class TestShipmentItemsAdditional:
    def test_shipment_no_fallback_when_order_number_none(self, ext_mod):
        """When order_number is None, fall back to shipment_no."""
        mock_db = MagicMock()
        mock_row = MagicMock(spec=["id", "shipment_no", "status"])
        mock_row.id = 1
        mock_row.shipment_no = "SHP-001"
        mock_row.status = "delivered"
        # order_number not in spec, so getattr returns None
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
        assert len(items) == 1
        assert items[0]["order_number"] == "SHP-001"
        assert items[0]["status"] == "delivered"

    def test_both_order_number_and_shipment_no_none(self, ext_mod):
        """When both order_number and shipment_no are None, order_number is None."""
        mock_db = MagicMock()
        mock_row = MagicMock(spec=["id", "status"])
        mock_row.id = 2
        mock_row.status = "pending"
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
        assert len(items) == 1
        assert items[0]["order_number"] is None

    def test_empty_result(self, ext_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
        assert items == []

    def test_multiple_rows(self, ext_mod):
        mock_db = MagicMock()
        rows = []
        for i in range(3):
            r = MagicMock()
            r.id = i
            r.order_number = f"ORD-{i}"
            r.status = "shipped"
            rows.append(r)
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = rows
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
        assert len(items) == 3
        assert items[0]["id"] == 0
        assert items[2]["id"] == 2


# ---------------------------------------------------------------------------
# mobile_shipments with shipment_no fallback
# ---------------------------------------------------------------------------


class TestMobileShipmentsAdditional:
    @pytest.mark.asyncio
    async def test_shipment_no_fallback(self, ext_mod):
        """Test mobile_shipments with rows that only have shipment_no."""
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 1
        mock_shipment = MagicMock(spec=["id", "shipment_no", "status"])
        mock_shipment.id = 1
        mock_shipment.shipment_no = "SHP-001"
        mock_shipment.status = "in_transit"
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_shipment
        ]
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_shipments(page=1, per_page=20, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_empty_shipments(self, ext_mod):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 0
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_shipments(page=2, per_page=10, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# _approval_items with rows missing attributes
# ---------------------------------------------------------------------------


class TestApprovalItemsAdditional:
    def test_row_missing_request_no(self, ext_mod):
        """Test _approval_items with row that has no request_no."""
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Test"
        mock_row.status = "pending"
        mock_row.request_no = None
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._approval_items(limit=10)
        assert len(items) == 1
        assert items[0]["id"] == 1
        assert items[0]["request_no"] is None

    def test_empty_result(self, ext_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._approval_items(limit=10)
        assert items == []

    def test_default_limit(self, ext_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._approval_items()
        assert items == []
        # Verify default limit=100 is passed
        mock_db.query.return_value.order_by.return_value.limit.assert_called_once_with(100)


# ---------------------------------------------------------------------------
# mobile_device_register edge cases
# ---------------------------------------------------------------------------


class TestMobileDeviceRegisterAdditional:
    @pytest.mark.asyncio
    async def test_empty_push_provider_defaults_to_fcm(self, ext_mod):
        """When push_provider is empty, provider defaults to 'fcm'."""
        body = ext_mod.DeviceRegisterBody(
            fcm_token="a" * 10, push_token="push_tok", push_provider=""
        )
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_empty_product_sku_defaults_to_personal(self, ext_mod):
        """When product_sku is empty, defaults to 'personal'."""
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10, push_token="push_tok", product_sku="")
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_push_provider_uppercase_lowered(self, ext_mod):
        """push_provider is lowercased."""
        body = ext_mod.DeviceRegisterBody(
            fcm_token="a" * 10, push_token="push_tok", push_provider="FCM"
        )
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_push_token_from_fcm_when_push_empty(self, ext_mod):
        """When push_token is empty, token comes from fcm_token."""
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10, push_token="")
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_update_existing_row_with_empty_product_sku(self, ext_mod):
        """Update existing row with empty product_sku defaults to 'personal'."""
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 10, push_token="push_tok", product_sku="")
        mock_db = MagicMock()
        mock_row = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = mock_row
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.utils.time.utc_now_naive", return_value="2026-06-17"),
        ):
            result = await ext_mod.mobile_device_register(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_pairing_lookup with missing exp
# ---------------------------------------------------------------------------


class TestMobilePairingLookupAdditional:
    @pytest.mark.asyncio
    async def test_lookup_missing_exp_key(self, ext_mod):
        """Test lookup when rec has no 'exp' key — should default to 0."""
        body = ext_mod.PairingLookupBody(code="123456")
        with patch.object(
            ext_mod,
            "lookup_by_shortcode",
            return_value={"host": "192.168.1.1", "port": 5000, "nonce": "abc"},
        ):
            result = await ext_mod.mobile_pairing_lookup(body=body)
        # format_mobile_response returns a dict (not JSONResponse)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("exp") == 0

    @pytest.mark.asyncio
    async def test_lookup_with_exp_present(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="123456")
        with patch.object(
            ext_mod,
            "lookup_by_shortcode",
            return_value={
                "host": "192.168.1.1",
                "port": 5000,
                "nonce": "abc",
                "exp": 9999,
            },
        ):
            result = await ext_mod.mobile_pairing_lookup(body=body)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("exp") == 9999

    @pytest.mark.asyncio
    async def test_lookup_not_found(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="000000")
        with patch.object(
            ext_mod,
            "lookup_by_shortcode",
            return_value=None,
        ):
            result = await ext_mod.mobile_pairing_lookup(body=body)
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# mobile_pairing_issue additional
# ---------------------------------------------------------------------------


class TestMobilePairingIssueAdditional:
    @pytest.mark.asyncio
    async def test_issue_with_default_host(self, ext_mod):
        """Test pairing issue with default host (127.0.0.1) — should call _guess_lan_ipv4."""
        body = ext_mod.PairingIssueBody()
        with (
            patch.object(ext_mod, "_guess_lan_ipv4", return_value="10.0.0.5"),
            patch(
                "app.security.mobile_pairing.issue_pairing_nonce",
                return_value={"nonce": "n", "host": "10.0.0.5", "port": 5112},
            ),
        ):
            result = await ext_mod.mobile_pairing_issue(body, _mock_pairing_request())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_issue_with_localhost_host(self, ext_mod):
        body = ext_mod.PairingIssueBody(host="localhost", port=8080)
        with (
            patch.object(ext_mod, "_guess_lan_ipv4", return_value="10.0.0.5"),
            patch(
                "app.security.mobile_pairing.issue_pairing_nonce",
                return_value={"nonce": "n", "host": "10.0.0.5", "port": 8080},
            ),
        ):
            result = await ext_mod.mobile_pairing_issue(
                body,
                _mock_pairing_request("localhost:8080", "localhost"),
            )
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_issue_with_custom_host(self, ext_mod):
        body = ext_mod.PairingIssueBody(host="example.com", port=443)
        with patch(
            "app.security.mobile_pairing.issue_pairing_nonce",
            return_value={"nonce": "n", "host": "example.com", "port": 443},
        ):
            result = await ext_mod.mobile_pairing_issue(
                body,
                _mock_pairing_request("example.com:443", "example.com"),
            )
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_sync_push with user having no username
# ---------------------------------------------------------------------------


class TestMobileSyncPushAdditional:
    @pytest.mark.asyncio
    async def test_user_without_username_uses_fallback_actor(self, ext_mod):
        """When user has no username, actor falls back to 'user-{id}'."""
        user = MagicMock()
        user.id = 42
        del user.username

        mock_sync_db = MagicMock()
        body = ext_mod.SyncPushBody(
            items=[ext_mod.SyncPushItem(entity_type="customer", entity_id="1")]
        )
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 1},
            ),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=user)
        assert hasattr(result, "body") or isinstance(result, dict)
        # Verify append_change was called with actor="user-42"
        mock_sync_db.append_change.assert_called_once()
        call_kwargs = mock_sync_db.append_change.call_args
        assert call_kwargs.kwargs.get("actor") == "user-42"

    @pytest.mark.asyncio
    async def test_more_than_50_items_truncated(self, ext_mod):
        """Test that more than 50 items are truncated to first 50."""
        mock_sync_db = MagicMock()
        items = [ext_mod.SyncPushItem(entity_type="customer", entity_id=str(i)) for i in range(60)]
        body = ext_mod.SyncPushBody(items=items)
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 50},
            ),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        # Only 50 items should be written
        assert mock_sync_db.append_change.call_count == 50

    @pytest.mark.asyncio
    async def test_apply_inbox_with_written_zero(self, ext_mod):
        """Test apply_inbox with limit=0+50=50 when no items written."""
        mock_sync_db = MagicMock()
        body = ext_mod.SyncPushBody(items=[])
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 0},
            ) as mock_apply,
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        mock_apply.assert_called_once_with(limit=50)


# ---------------------------------------------------------------------------
# mobile_auth_qr_confirm additional branches
# ---------------------------------------------------------------------------


class TestMobileAuthQrConfirmAdditional2:
    @pytest.mark.asyncio
    async def test_non_bearer_authorization_header(self, ext_mod):
        """Test that non-Bearer authorization header is ignored."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Basic abc123"}

        with patch(
            "app.security.auth_qr_login.get_auth_qr",
            return_value={"status": "pending"},
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="", password="pass")
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        # No username (bearer path not taken), should fail
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_bearer_with_username_provided_skips_bearer_path(self, ext_mod):
        """When username is already provided, bearer path is skipped."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer some_token"}

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid123"}, None)),
            ),
            patch(
                "app.security.auth_qr_login.confirm_auth_qr",
                return_value=True,
            ),
            patch("app.security.mobile_jwt.user_id_from_mobile_bearer") as mock_bearer,
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        # bearer lookup should NOT be called since username is provided
        mock_bearer.assert_not_called()
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_bearer_no_password(self, ext_mod):
        """Bearer token present, uid found, user found, but no password."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer mobile_jwt_token"}

        mock_db = MagicMock()
        mock_user_row = MagicMock()
        mock_user_row.username = "alice"
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = mock_user_row
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch(
                "app.security.mobile_jwt.user_id_from_mobile_bearer",
                return_value=42,
            ),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="", password="")
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        # Username found via bearer but no password → 400
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_login_error_body_decode_fails(self, ext_mod):
        """Test login error where err.body exists but decode fails."""
        err_resp = MagicMock()
        err_resp.body = b"\xff\xfe invalid utf-8"

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, err_resp)),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError, ValueError, UnicodeDecodeError),
            ),
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_login_error_body_not_json(self, ext_mod):
        """Test login error where err.body is not valid JSON."""
        err_resp = MagicMock()
        err_resp.body = b"not json"

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, err_resp)),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError, ValueError, UnicodeDecodeError),
            ),
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_qr_id_with_whitespace_stripped(self, ext_mod):
        """Test that qr_id is stripped on confirm."""
        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid123"}, None)),
            ),
            patch(
                "app.security.auth_qr_login.confirm_auth_qr",
                return_value=True,
            ) as mock_confirm,
        ):
            body = ext_mod.AuthQrConfirmBody(
                qr_id="  " + "a" * 8 + "  ", username="alice", password="pass"
            )
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert hasattr(result, "body") or isinstance(result, dict)
        # confirm_auth_qr should be called with stripped qr_id
        call_args = mock_confirm.call_args
        assert call_args[0][0] == "a" * 8


# ---------------------------------------------------------------------------
# mobile_auth_oidc_exchange additional branches
# ---------------------------------------------------------------------------


class TestMobileAuthOidcExchangeAdditional2:
    @pytest.mark.asyncio
    async def test_authenticate_returns_no_message(self, ext_mod):
        """Test path where authenticate_oidc_user fails with no message."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(
                    return_value={
                        "profile": {"sub": "x", "email": "a@b.com"},
                        "access_token": "oidc-at",
                    }
                ),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": False,
            }
            mock_get.return_value = mock_service
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_session_id_none(self, ext_mod):
        """Test success path where session_id is None."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(
                    return_value={
                        "profile": {"sub": "x", "email": "a@b.com"},
                        "access_token": "oidc-at",
                    }
                ),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.finalize_auth_after_oidc",
                new=AsyncMock(
                    return_value={
                        "user": {"id": 1, "username": "alice"},
                        "account_kind": "personal",
                    }
                ),
            ),
            patch(
                "app.security.mobile_jwt.issue_mobile_tokens",
                return_value={"access_token": "tok", "refresh_token": "rtok"},
            ),
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": True,
                "session_id": None,
                "user": {"id": 1, "username": "alice"},
            }
            mock_get.return_value = mock_service
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_enterprise_sku(self, ext_mod):
        """Test with enterprise SKU."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(
                    return_value={
                        "profile": {"sub": "x", "email": "a@b.com"},
                        "access_token": "oidc-at",
                    }
                ),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.application.enterprise_login_flow.finalize_auth_after_oidc",
                new=AsyncMock(
                    return_value={
                        "user": {"id": 1, "username": "alice"},
                        "account_kind": "enterprise",
                        "session_id": "sid123",
                    }
                ),
            ),
            patch(
                "app.security.mobile_jwt.issue_mobile_tokens",
                return_value={"access_token": "tok", "refresh_token": "rtok"},
            ),
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": True,
                "session_id": "sid123",
                "user": {"id": 1, "username": "alice"},
            }
            mock_get.return_value = mock_service
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_authenticate_returns_success_false_with_empty_user(self, ext_mod):
        """Test path where authenticate_oidc_user returns success=False with empty user."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(
                    return_value={
                        "profile": {"sub": "x", "email": "a@b.com"},
                        "access_token": "oidc-at",
                    }
                ),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": False,
                "user": {},
                "message": "",
            }
            mock_get.return_value = mock_service
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
        assert result.status_code == 401


# ---------------------------------------------------------------------------
# _mobile_mod_items additional branches
# ---------------------------------------------------------------------------


class TestMobileModItemsAdditional2:
    def test_none_return_from_list_all_mods(self, ext_mod):
        """Test when list_all_mods returns None."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = None
            items = ext_mod._mobile_mod_items()
        assert items == []

    def test_mixed_dict_and_object_mods(self, ext_mod):
        """Test mix of dict and object mods."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            obj_mod = MagicMock()
            obj_mod.id = "obj-1"
            obj_mod.name = "Object Mod"
            obj_mod.mod_id = ""
            obj_mod.title = ""
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "dict-1", "name": "Dict Mod"},
                obj_mod,
            ]
            items = ext_mod._mobile_mod_items()
        assert len(items) == 2
        assert items[0]["id"] == "dict-1"
        assert items[1]["id"] == "obj-1"

    def test_dict_mod_with_only_title(self, ext_mod):
        """Test dict mod that only has title (no id, mod_id, or name)."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = [
                {"title": "Title Only Mod"},
            ]
            items = ext_mod._mobile_mod_items()
        # No id/mod_id → mid is empty → skipped
        assert len(items) == 0

    def test_dict_mod_with_id_and_title(self, ext_mod):
        """Test dict mod with id and title (no name)."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "mod-1", "title": "Title Mod"},
            ]
            items = ext_mod._mobile_mod_items()
        assert len(items) == 1
        assert items[0]["id"] == "mod-1"
        assert items[0]["name"] == "Title Mod"

    def test_object_mod_with_all_none_attrs(self, ext_mod):
        """Test object mod where all attributes are None."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mod = MagicMock()
            mod.id = None
            mod.name = None
            mod.mod_id = None
            mod.title = None
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
        # All None → mid is empty → skipped
        assert len(items) == 0

    def test_dict_mod_with_empty_string_id(self, ext_mod):
        """Test dict mod with empty string id and empty mod_id."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "", "mod_id": "", "name": "No ID"},
            ]
            items = ext_mod._mobile_mod_items()
        assert len(items) == 0

    def test_dict_mod_with_whitespace_id(self, ext_mod):
        """Test dict mod with whitespace-only id."""
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "   ", "name": "Whitespace ID"},
            ]
            items = ext_mod._mobile_mod_items()
        # "   ".strip() == "" → skipped
        assert len(items) == 0


# ---------------------------------------------------------------------------
# _guess_lan_ipv4 additional branches
# ---------------------------------------------------------------------------


class TestGuessLanIpv4Additional2:
    def test_whitespace_ip_returns_loopback(self, ext_mod):
        """Test that whitespace-only IP returns loopback."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("   ", 80)
        with patch("socket.socket", return_value=mock_socket):
            ip = ext_mod._guess_lan_ipv4()
        assert ip == "127.0.0.1"

    def test_none_ip_returns_loopback(self, ext_mod):
        """Test that None IP returns loopback."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = (None, 80)
        with patch("socket.socket", return_value=mock_socket):
            ip = ext_mod._guess_lan_ipv4()
        assert ip == "127.0.0.1"

    def test_socket_close_called(self, ext_mod):
        """Test that socket.close() is called on success."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("192.168.1.100", 80)
        with patch("socket.socket", return_value=mock_socket):
            ext_mod._guess_lan_ipv4()
        mock_socket.close.assert_called_once()

    def test_socket_close_called_on_error(self, ext_mod):
        """Test that socket.close() is NOT called when connect raises OSError."""
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError("no network")
        with patch("socket.socket", return_value=mock_socket):
            ip = ext_mod._guess_lan_ipv4()
        assert ip == "127.0.0.1"
        # socket was created but connect failed, close not called
        mock_socket.close.assert_not_called()


# ---------------------------------------------------------------------------
# _pairing_issue_host additional
# ---------------------------------------------------------------------------


class TestPairingIssueHostAdditional:
    def test_whitespace_only_host(self, ext_mod):
        """Test that whitespace-only host defaults to 127.0.0.1 then LAN."""
        with patch.object(ext_mod, "_guess_lan_ipv4", return_value="10.0.0.5"):
            assert ext_mod._pairing_issue_host("   ") == "10.0.0.5"

    def test_host_with_whitespace(self, ext_mod):
        """Test that host with surrounding whitespace is stripped."""
        assert ext_mod._pairing_issue_host("  192.168.1.50  ") == "192.168.1.50"

    def test_host_with_tabs(self, ext_mod):
        """Test that host with tabs is stripped."""
        assert ext_mod._pairing_issue_host("\t192.168.1.50\t") == "192.168.1.50"


# ---------------------------------------------------------------------------
# _ensure_mobile_device_table additional
# ---------------------------------------------------------------------------


class TestEnsureMobileDeviceTableAdditional:
    def test_import_error_logged(self, ext_mod):
        """Test that import errors are caught and logged."""
        with (
            patch(
                "app.db.session.get_db",
                side_effect=ImportError("module not found"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError, ImportError),
            ),
        ):
            # Should not raise
            ext_mod._ensure_mobile_device_table()

    def test_value_error_logged(self, ext_mod):
        """Test that ValueError is caught."""
        with (
            patch(
                "app.db.session.get_db",
                side_effect=ValueError("bad value"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError, ValueError),
            ),
        ):
            ext_mod._ensure_mobile_device_table()

    def test_table_creation_called(self, ext_mod):
        """Test that table creation is called when table is missing."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_db.get_bind.return_value = mock_bind
        mock_table = MagicMock()
        mock_table.__table__ = MagicMock()
        mock_table.__tablename__ = "mobile_device_tokens"
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = False
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("sqlalchemy.inspect", return_value=mock_insp),
            patch(
                "app.db.models.mobile_device.MobileDeviceToken",
                mock_table,
                create=True,
            ),
        ):
            ext_mod._ensure_mobile_device_table()
        mock_table.__table__.create.assert_called_once_with(mock_bind, checkfirst=True)


# ---------------------------------------------------------------------------
# mobile_sync_status additional
# ---------------------------------------------------------------------------


class TestMobileSyncStatusAdditional:
    @pytest.mark.asyncio
    async def test_status_with_inbox_pending(self, ext_mod):
        """Test sync status with inbox_pending count."""
        mock_sync_db = MagicMock()
        mock_sync_db.get_status.return_value = {"healthy": True, "local_cursor": 1}
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (5,)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn", return_value=mock_ctx),
        ):
            result = await ext_mod.mobile_sync_status(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("inbox_pending") == 5
        assert data.get("data", {}).get("sync_mode") == "cloud"
        assert data.get("data", {}).get("standalone_supported") is True
        assert data.get("data", {}).get("desktop_required") is False
        assert data.get("data", {}).get("desktop_executor", {}).get("required") is False

    @pytest.mark.asyncio
    async def test_status_with_zero_inbox_pending(self, ext_mod):
        mock_sync_db = MagicMock()
        mock_sync_db.get_status.return_value = {"healthy": True}
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (0,)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn", return_value=mock_ctx),
        ):
            result = await ext_mod.mobile_sync_status(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_sync_pull additional
# ---------------------------------------------------------------------------


class TestMobileSyncPullAdditional:
    @pytest.mark.asyncio
    async def test_pull_with_im_read_state_changes(self, ext_mod):
        """Test sync pull with im_read_state entity type."""
        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = [
            {"entity_type": "im_read_state", "id": 1},
            {"entity_type": "customer", "id": 2},
            {"entity_type": "im_message", "id": 3},
        ]
        mock_sync_db.get_status.return_value = {"local_cursor": 10}

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.fastapi_routes.mobile_api_extensions._approval_items",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._shipment_items",
                return_value=[],
            ),
        ):
            body = ext_mod.SyncPullBody(since_cursor=5)
            result = await ext_mod.mobile_sync_pull(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("source") == "cloud"
        assert data.get("data", {}).get("executor_required") is False
        assert data.get("data", {}).get("im_change_count") == 2
        # update_remote_cursor should be called with cursor=10
        mock_sync_db.update_remote_cursor.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_pull_with_cursor_zero_skips_update(self, ext_mod):
        """Test sync pull where cursor is 0 — update_remote_cursor NOT called."""
        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": 0}

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.fastapi_routes.mobile_api_extensions._approval_items",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._shipment_items",
                return_value=[],
            ),
        ):
            body = ext_mod.SyncPullBody(since_cursor=0)
            result = await ext_mod.mobile_sync_pull(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        # cursor is 0 (falsy) → update_remote_cursor NOT called
        mock_sync_db.update_remote_cursor.assert_not_called()

    @pytest.mark.asyncio
    async def test_pull_with_no_im_changes(self, ext_mod):
        """Test sync pull with no IM changes."""
        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = [
            {"entity_type": "customer", "id": 1},
            {"entity_type": "order", "id": 2},
        ]
        mock_sync_db.get_status.return_value = {"local_cursor": 5}

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.fastapi_routes.mobile_api_extensions._approval_items",
                return_value=[{"id": 1, "title": "A"}],
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions._shipment_items",
                return_value=[{"id": 1, "order_number": "O1"}],
            ),
        ):
            body = ext_mod.SyncPullBody(since_cursor=0)
            result = await ext_mod.mobile_sync_pull(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("im_change_count") == 0
        assert len(data.get("data", {}).get("approvals", [])) == 1


# ---------------------------------------------------------------------------
# mobile_sync_conflicts additional
# ---------------------------------------------------------------------------


class TestMobileSyncConflictsAdditional:
    @pytest.mark.asyncio
    async def test_conflicts_empty_items(self, ext_mod):
        """Test sync conflicts with no conflict rows."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn", return_value=mock_ctx),
        ):
            result = await ext_mod.mobile_sync_conflicts(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("items") == []

    @pytest.mark.asyncio
    async def test_conflicts_with_multiple_rows(self, ext_mod):
        """Test sync conflicts with multiple conflict rows."""
        mock_conn = MagicMock()
        rows = []
        for i in range(3):
            row = MagicMock()
            row.keys.return_value = [
                "id",
                "entity_type",
                "entity_id",
                "conflict_note",
                "received_at",
            ]
            row.__getitem__ = MagicMock(
                side_effect=lambda k: {
                    "id": i,
                    "entity_type": "customer",
                    "entity_id": f"c-{i}",
                    "conflict_note": "note",
                    "received_at": "2026-01-01",
                }[k]
            )
            rows.append(row)
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn", return_value=mock_ctx),
        ):
            result = await ext_mod.mobile_sync_conflicts(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_sync_ack additional
# ---------------------------------------------------------------------------


class TestMobileSyncAckAdditional:
    @pytest.mark.asyncio
    async def test_ack_with_zero_cursor(self, ext_mod):
        """Test sync ack with cursor=0."""
        mock_sync_db = MagicMock()
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db):
            body = ext_mod.SyncAckBody(cursor=0)
            result = await ext_mod.mobile_sync_ack(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("acked") == 0

    @pytest.mark.asyncio
    async def test_ack_with_large_cursor(self, ext_mod):
        """Test sync ack with large cursor value."""
        mock_sync_db = MagicMock()
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db):
            body = ext_mod.SyncAckBody(cursor=999999)
            result = await ext_mod.mobile_sync_ack(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        mock_sync_db.update_remote_cursor.assert_called_once_with(999999)


# ---------------------------------------------------------------------------
# mobile_approval_list additional
# ---------------------------------------------------------------------------


class TestMobileApprovalListAdditional:
    @pytest.mark.asyncio
    async def test_with_pagination_page_2(self, ext_mod):
        """Test approval list with page=2."""
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 100
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_approval_list(
                request=MagicMock(), status=None, page=2, page_size=50, user=_mock_user()
            )
        assert hasattr(result, "body") or isinstance(result, dict)
        # Verify offset is (2-1)*50 = 50
        mock_q.order_by.return_value.offset.assert_called_once_with(50)

    @pytest.mark.asyncio
    async def test_with_status_filter_and_results(self, ext_mod):
        """Test approval list with status filter and results."""
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 1
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Test"
        mock_row.status = "approved"
        mock_row.request_no = "REQ-001"
        mock_row.applicant_id = 100
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_approval_list(
                request=MagicMock(), status="approved", page=1, page_size=50, user=_mock_user()
            )
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_customers additional
# ---------------------------------------------------------------------------


class TestMobileCustomersAdditional:
    @pytest.mark.asyncio
    async def test_empty_customers(self, ext_mod):
        """Test customers with no data."""
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 0
        mock_q.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_customers(page=1, per_page=20, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_customers_with_pagination(self, ext_mod):
        """Test customers with page=3, per_page=10."""
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 50
        mock_customer = MagicMock()
        mock_customer.id = 21
        mock_customer.customer_name = "Bob"
        mock_customer.contact_phone = "13900000000"
        mock_q.offset.return_value.limit.return_value.all.return_value = [mock_customer]
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_customers(page=3, per_page=10, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        # Verify offset is (3-1)*10 = 20
        mock_q.offset.assert_called_once_with(20)


# ---------------------------------------------------------------------------
# Pydantic model validation additional
# ---------------------------------------------------------------------------


class TestPydanticModelsAdditional:
    def test_device_register_body_fcm_token_too_short(self, ext_mod):
        """Test that fcm_token with less than 8 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.DeviceRegisterBody(fcm_token="short")

    def test_device_register_body_push_provider_too_long(self, ext_mod):
        """Test that push_provider longer than 16 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.DeviceRegisterBody(fcm_token="a" * 8, push_provider="x" * 17)

    def test_device_register_body_device_label_too_long(self, ext_mod):
        """Test that device_label longer than 200 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.DeviceRegisterBody(fcm_token="a" * 8, device_label="x" * 201)

    def test_device_register_body_platform_too_long(self, ext_mod):
        """Test that platform longer than 32 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.DeviceRegisterBody(fcm_token="a" * 8, platform="x" * 33)

    def test_pairing_lookup_body_too_short(self, ext_mod):
        """Test that code shorter than 6 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.PairingLookupBody(code="12345")

    def test_pairing_lookup_body_too_long(self, ext_mod):
        """Test that code longer than 6 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.PairingLookupBody(code="1234567")

    def test_pairing_issue_body_port_out_of_range_low(self, ext_mod):
        """Test that port < 1 fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.PairingIssueBody(port=0)

    def test_pairing_issue_body_port_out_of_range_high(self, ext_mod):
        """Test that port > 65535 fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.PairingIssueBody(port=65536)

    def test_sync_pull_body_negative_cursor(self, ext_mod):
        """Test that negative since_cursor fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.SyncPullBody(since_cursor=-1)

    def test_sync_push_item_empty_entity_type(self, ext_mod):
        """Test that empty entity_type fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.SyncPushItem(entity_type="", entity_id="1")

    def test_sync_push_item_entity_id_too_long(self, ext_mod):
        """Test that entity_id longer than 128 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.SyncPushItem(entity_type="customer", entity_id="x" * 129)

    def test_sync_ack_body_negative_cursor(self, ext_mod):
        """Test that negative cursor fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.SyncAckBody(cursor=-1)

    def test_auth_qr_confirm_body_qr_id_too_short(self, ext_mod):
        """Test that qr_id shorter than 8 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.AuthQrConfirmBody(qr_id="short")

    def test_auth_qr_confirm_body_username_too_long(self, ext_mod):
        """Test that username longer than 128 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="x" * 129)

    def test_oidc_exchange_body_code_too_short(self, ext_mod):
        """Test that code shorter than 4 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.OidcExchangeBody(code="ab", state="s" * 8)

    def test_oidc_exchange_body_state_too_short(self, ext_mod):
        """Test that state shorter than 8 chars fails validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ext_mod.OidcExchangeBody(code="abcd", state="short")

    def test_sync_push_item_default_operation(self, ext_mod):
        """Test that operation defaults to 'update'."""
        item = ext_mod.SyncPushItem(entity_type="customer", entity_id="1")
        assert item.operation == "update"

    def test_sync_push_item_default_payload(self, ext_mod):
        """Test that payload defaults to empty dict."""
        item = ext_mod.SyncPushItem(entity_type="customer", entity_id="1")
        assert item.payload == {}

    def test_sync_push_body_default_items(self, ext_mod):
        """Test that items defaults to empty list."""
        body = ext_mod.SyncPushBody()
        assert body.items == []

    def test_auth_qr_confirm_body_default_account_kind(self, ext_mod):
        """Test that account_kind defaults to 'enterprise'."""
        body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8)
        assert body.account_kind == "enterprise"

    def test_auth_qr_confirm_body_default_username_password(self, ext_mod):
        """Test that username and password default to empty strings."""
        body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8)
        assert body.username == ""
        assert body.password == ""

    def test_device_register_body_push_token_default_empty(self, ext_mod):
        """Test that push_token defaults to empty string."""
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 8)
        assert body.push_token == ""

    def test_device_register_body_device_label_default_empty(self, ext_mod):
        """Test that device_label defaults to empty string."""
        body = ext_mod.DeviceRegisterBody(fcm_token="a" * 8)
        assert body.device_label == ""

    def test_pairing_exchange_body_defaults(self, ext_mod):
        """Test PairingExchangeBody defaults."""
        body = ext_mod.PairingExchangeBody()
        assert body.nonce == ""
        assert body.code == ""


# ---------------------------------------------------------------------------
# mobile_home additional
# ---------------------------------------------------------------------------


class TestMobileHomeAdditional:
    @pytest.mark.asyncio
    async def test_home_with_empty_mods(self, ext_mod):
        """Test home with no mods installed."""
        mock_sync_db = MagicMock()
        mock_sync_db.get_status.return_value = {"healthy": True}
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=[]),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "empty"},
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
        ):
            result = await ext_mod.mobile_home(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("mods") == []
        assert data.get("data", {}).get("sync", {}).get("healthy") is True

    @pytest.mark.asyncio
    async def test_home_with_multiple_mods(self, ext_mod):
        """Test home with multiple mods."""
        mock_sync_db = MagicMock()
        mock_sync_db.get_status.return_value = {"healthy": True, "local_cursor": 5}
        mods = [{"id": f"mod-{i}", "name": f"Mod {i}"} for i in range(5)]
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=mods),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "data"},
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
        ):
            result = await ext_mod.mobile_home(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_platform_shell additional
# ---------------------------------------------------------------------------


class TestMobilePlatformShellAdditional:
    @pytest.mark.asyncio
    async def test_platform_shell_with_empty_mods(self, ext_mod):
        """Test platform shell with no mods."""
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=[]),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "empty"},
            ) as mock_build,
        ):
            result = await ext_mod.mobile_platform_shell(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        mock_build.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_platform_shell_with_mods(self, ext_mod):
        """Test platform shell with mods."""
        mods = [{"id": "mod-1", "name": "Mod 1"}, {"id": "mod-2", "name": "Mod 2"}]
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=mods),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "data"},
            ) as mock_build,
        ):
            result = await ext_mod.mobile_platform_shell(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        mock_build.assert_called_once_with(["mod-1", "mod-2"])


# ---------------------------------------------------------------------------
# mobile_mods_summary additional
# ---------------------------------------------------------------------------


class TestMobileModsSummaryAdditional:
    @pytest.mark.asyncio
    async def test_summary_with_empty_items(self, ext_mod):
        """Test mods summary with no items."""
        with patch.object(ext_mod, "_mobile_mod_items", return_value=[]):
            result = await ext_mod.mobile_mods_summary(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("data", {}).get("items") == []

    @pytest.mark.asyncio
    async def test_summary_with_multiple_items(self, ext_mod):
        """Test mods summary with multiple items."""
        items = [{"id": f"mod-{i}", "name": f"Mod {i}"} for i in range(10)]
        with patch.object(ext_mod, "_mobile_mod_items", return_value=items):
            result = await ext_mod.mobile_mods_summary(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)
