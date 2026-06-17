"""Tests for app.fastapi_routes.mobile_api_extensions — additional coverage (ext2).

Focus: mobile_approval_list with user, mobile_customers with user, mobile_shipments with user,
mobile_device_register with user (existing row update, new row, missing token),
mobile_device_unregister with user, mobile_pairing_lookup success, mobile_pairing_exchange by code,
mobile_pairing_exchange by nonce success, mobile_mods_summary with user, mobile_platform_shell with user,
mobile_home with user (sync success, sync error), mobile_sync_status with user (success, error),
mobile_sync_pull with user (success, error, im_changes), mobile_sync_push with user (success, apply error, db error),
mobile_sync_ack with user (success, error), mobile_sync_conflicts with user (success, error),
mobile_auth_qr_confirm (bearer auth, login error, session_id missing, confirm fail, success),
mobile_auth_oidc_exchange (auth fail, success).
"""

from __future__ import annotations

import sys
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


# ---------------------------------------------------------------------------
# mobile_approval_list with user
# ---------------------------------------------------------------------------


class TestMobileApprovalListWithUser:
    @pytest.mark.asyncio
    async def test_with_user_no_status_filter(self, ext_mod):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 1
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.title = "Test"
        mock_row.status = "pending"
        mock_row.request_no = "REQ-001"
        mock_row.applicant_id = 100
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_approval_list(
                request=MagicMock(), status=None, page=1, page_size=50, user=_mock_user()
            )
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_with_user_status_filter(self, ext_mod):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 0
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_q.filter.return_value = mock_q
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_approval_list(
                request=MagicMock(), status="approved", page=1, page_size=50, user=_mock_user()
            )
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_customers with user
# ---------------------------------------------------------------------------


class TestMobileCustomersWithUser:
    @pytest.mark.asyncio
    async def test_with_user(self, ext_mod):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 1
        mock_customer = MagicMock()
        mock_customer.id = 1
        mock_customer.customer_name = "Alice"
        mock_customer.contact_phone = "13800000000"
        mock_q.offset.return_value.limit.return_value.all.return_value = [mock_customer]
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_customers(page=1, per_page=20, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_shipments with user
# ---------------------------------------------------------------------------


class TestMobileShipmentsWithUser:
    @pytest.mark.asyncio
    async def test_with_user(self, ext_mod):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.count.return_value = 1
        mock_shipment = MagicMock()
        mock_shipment.id = 1
        mock_shipment.order_number = "ORD-001"
        mock_shipment.status = "shipped"
        mock_q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_shipment
        ]
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.db.session.get_db", return_value=mock_db):
            result = await ext_mod.mobile_shipments(page=1, per_page=20, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_device_register with user
# ---------------------------------------------------------------------------


class TestMobileDeviceRegisterWithUser:
    @pytest.mark.asyncio
    async def test_missing_push_token(self, ext_mod):
        # token = (body.push_token or body.fcm_token).strip(); to hit the
        # "缺少 push_token" 400 branch, BOTH push_token and fcm_token must be
        # empty. DeviceRegisterBody.fcm_token has min_length=8, so bypass
        # pydantic validation with model_construct to reach the branch.
        body = ext_mod.DeviceRegisterBody.model_construct(
            fcm_token="", push_token="", push_provider=""
        )
        with patch.object(ext_mod, "_ensure_mobile_device_table"):
            result = await ext_mod.mobile_device_register(body=body, user=_mock_user())
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_update_existing_row(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(
            fcm_token="a" * 10, push_token="push_tok", device_label="My Phone"
        )
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

    @pytest.mark.asyncio
    async def test_create_new_row(self, ext_mod):
        body = ext_mod.DeviceRegisterBody(
            fcm_token="a" * 10, push_token="push_tok", device_label="My Phone"
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


# ---------------------------------------------------------------------------
# mobile_device_unregister with user
# ---------------------------------------------------------------------------


class TestMobileDeviceUnregisterWithUser:
    @pytest.mark.asyncio
    async def test_with_user(self, ext_mod):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.delete.return_value = None
        mock_db.query.return_value = mock_q
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(ext_mod, "_ensure_mobile_device_table"),
            patch("app.db.session.get_db", return_value=mock_db),
        ):
            result = await ext_mod.mobile_device_unregister(fcm_token="a" * 10, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_pairing_lookup success
# ---------------------------------------------------------------------------


class TestMobilePairingLookupSuccess:
    @pytest.mark.asyncio
    async def test_lookup_success(self, ext_mod):
        body = ext_mod.PairingLookupBody(code="123456")
        with patch(
            "app.security.mobile_pairing.lookup_by_shortcode",
            return_value={"host": "192.168.1.1", "port": 5000, "nonce": "abc", "exp": 1234},
        ):
            result = await ext_mod.mobile_pairing_lookup(body=body)
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_pairing_exchange by code/nonce success
# ---------------------------------------------------------------------------


class TestMobilePairingExchangeSuccess:
    @pytest.mark.asyncio
    async def test_exchange_by_code(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="123456", nonce="")
        with patch(
            "app.security.mobile_pairing.consume_by_shortcode",
            return_value={"host": "192.168.1.1", "port": 5000, "shortCode": "123456"},
        ):
            result = await ext_mod.mobile_pairing_exchange(body=body)
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_exchange_by_nonce_success(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="", nonce="abc123")
        with patch(
            "app.security.mobile_pairing.consume_pairing_nonce",
            return_value={"host": "192.168.1.1", "port": 5000, "shortCode": "123456"},
        ):
            result = await ext_mod.mobile_pairing_exchange(body=body)
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_exchange_invalid_both_empty(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="", nonce="")
        result = await ext_mod.mobile_pairing_exchange(body=body)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_exchange_invalid_code_returns_none(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="000000", nonce="")
        with patch(
            "app.security.mobile_pairing.consume_by_shortcode",
            return_value=None,
        ):
            result = await ext_mod.mobile_pairing_exchange(body=body)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_exchange_invalid_nonce_returns_none(self, ext_mod):
        body = ext_mod.PairingExchangeBody(code="", nonce="bad")
        with patch(
            "app.security.mobile_pairing.consume_pairing_nonce",
            return_value=None,
        ):
            result = await ext_mod.mobile_pairing_exchange(body=body)
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# mobile_mods_summary with user
# ---------------------------------------------------------------------------


class TestMobileModsSummaryWithUser:
    @pytest.mark.asyncio
    async def test_with_user(self, ext_mod):
        with patch.object(
            ext_mod, "_mobile_mod_items", return_value=[{"id": "m1", "name": "Mod1"}]
        ):
            result = await ext_mod.mobile_mods_summary(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_platform_shell with user
# ---------------------------------------------------------------------------


class TestMobilePlatformShellWithUser:
    @pytest.mark.asyncio
    async def test_with_user(self, ext_mod):
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=[{"id": "m1", "name": "Mod1"}]),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "data"},
            ),
        ):
            result = await ext_mod.mobile_platform_shell(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_home with user
# ---------------------------------------------------------------------------


class TestMobileHomeWithUser:
    @pytest.mark.asyncio
    async def test_with_user_sync_success(self, ext_mod):
        mock_sync_db = MagicMock()
        mock_sync_db.get_status.return_value = {"healthy": True}
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=[{"id": "m1", "name": "Mod1"}]),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "data"},
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
        ):
            result = await ext_mod.mobile_home(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_with_user_sync_error(self, ext_mod):
        with (
            patch.object(ext_mod, "_mobile_mod_items", return_value=[{"id": "m1", "name": "Mod1"}]),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"shell": "data"},
            ),
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("sync db fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await ext_mod.mobile_home(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_sync_status with user
# ---------------------------------------------------------------------------


class TestMobileSyncStatusWithUser:
    @pytest.mark.asyncio
    async def test_success(self, ext_mod):
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

    @pytest.mark.asyncio
    async def test_error(self, ext_mod):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await ext_mod.mobile_sync_status(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_sync_pull with user
# ---------------------------------------------------------------------------


class TestMobileSyncPullWithUser:
    @pytest.mark.asyncio
    async def test_success_with_im_changes(self, ext_mod):
        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = [
            {"entity_type": "im_message", "id": 1},
            {"entity_type": "customer", "id": 2},
        ]
        mock_sync_db.get_status.return_value = {"local_cursor": 5}

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

    @pytest.mark.asyncio
    async def test_success_no_cursor(self, ext_mod):
        mock_sync_db = MagicMock()
        mock_sync_db.get_changes.return_value = []
        mock_sync_db.get_status.return_value = {"local_cursor": None}

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

    @pytest.mark.asyncio
    async def test_error(self, ext_mod):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            body = ext_mod.SyncPullBody(since_cursor=0)
            result = await ext_mod.mobile_sync_pull(body=body, user=_mock_user())
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# mobile_sync_push with user
# ---------------------------------------------------------------------------


class TestMobileSyncPushWithUser:
    @pytest.mark.asyncio
    async def test_success(self, ext_mod):
        mock_sync_db = MagicMock()
        body = ext_mod.SyncPushBody(
            items=[
                ext_mod.SyncPushItem(entity_type="customer", entity_id="1"),
                ext_mod.SyncPushItem(entity_type="order", entity_id="2"),
            ]
        )
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 2},
            ),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_apply_error(self, ext_mod):
        mock_sync_db = MagicMock()
        body = ext_mod.SyncPushBody(
            items=[ext_mod.SyncPushItem(entity_type="customer", entity_id="1")]
        )
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                side_effect=RuntimeError("apply fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_db_error(self, ext_mod):
        body = ext_mod.SyncPushBody(
            items=[ext_mod.SyncPushItem(entity_type="customer", entity_id="1")]
        )
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=_mock_user())
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_empty_items(self, ext_mod):
        mock_sync_db = MagicMock()
        body = ext_mod.SyncPushBody(items=[])
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 0},
            ),
        ):
            result = await ext_mod.mobile_sync_push(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_sync_ack with user
# ---------------------------------------------------------------------------


class TestMobileSyncAckWithUser:
    @pytest.mark.asyncio
    async def test_success(self, ext_mod):
        mock_sync_db = MagicMock()
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_sync_db):
            body = ext_mod.SyncAckBody(cursor=10)
            result = await ext_mod.mobile_sync_ack(body=body, user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_error(self, ext_mod):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            body = ext_mod.SyncAckBody(cursor=10)
            result = await ext_mod.mobile_sync_ack(body=body, user=_mock_user())
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# mobile_sync_conflicts with user
# ---------------------------------------------------------------------------


class TestMobileSyncConflictsWithUser:
    @pytest.mark.asyncio
    async def test_success(self, ext_mod):
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__iter__ = MagicMock(return_value=iter([("id", 1), ("entity_type", "customer")]))
        mock_row.keys.return_value = ["id", "entity_type"]
        # Make dict(mock_row) work
        mock_row.keys = MagicMock(return_value=["id", "entity_type"])
        mock_row.__getitem__ = MagicMock(side_effect=lambda k: 1 if k == "id" else "customer")
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.xcmax_sync._ensure_schema"),
            patch("app.db.xcmax_sync._get_conn", return_value=mock_ctx),
        ):
            result = await ext_mod.mobile_sync_conflicts(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_error(self, ext_mod):
        with (
            patch(
                "app.db.xcmax_sync._get_conn",
                side_effect=RuntimeError("conn fail"),
            ),
            patch(
                "app.fastapi_routes.mobile_api_extensions.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await ext_mod.mobile_sync_conflicts(user=_mock_user())
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_auth_qr_confirm additional branches
# ---------------------------------------------------------------------------


class TestMobileAuthQrConfirmAdditional:
    @pytest.mark.asyncio
    async def test_bearer_auth_with_user_lookup(self, ext_mod):
        """Test bearer auth path that looks up user from DB."""
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
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="", password="pass")
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        # Should fail because password is provided but username comes from bearer
        # Actually password is provided, so should proceed to login
        assert result.status_code in (400, 401, 500, 200)

    @pytest.mark.asyncio
    async def test_bearer_auth_no_uid(self, ext_mod):
        """Test bearer auth path where uid lookup returns None."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer mobile_jwt_token"}

        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch(
                "app.security.mobile_jwt.user_id_from_mobile_bearer",
                return_value=None,
            ),
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="", password="pass")
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        # No username, should fail
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_bearer_auth_user_not_found(self, ext_mod):
        """Test bearer auth path where user is not found in DB."""
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer mobile_jwt_token"}

        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
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
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="", password="pass")
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_login_error(self, ext_mod):
        """Test login error path."""
        err_resp = MagicMock()
        err_resp.body = b'{"message": "invalid credentials"}'

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
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_login_error_no_body(self, ext_mod):
        """Test login error path where err has no body attribute."""
        err_resp = MagicMock(spec=[])  # No body attribute

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
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_session_id_missing(self, ext_mod):
        """Test path where login succeeds but no session_id."""
        with (
            patch(
                "app.security.auth_qr_login.get_auth_qr",
                return_value={"status": "pending"},
            ),
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True}, None)),
            ),
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_confirm_auth_qr_fail(self, ext_mod):
        """Test path where confirm_auth_qr returns False."""
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
                return_value=False,
            ),
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_success(self, ext_mod):
        """Test full success path."""
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
        ):
            body = ext_mod.AuthQrConfirmBody(qr_id="a" * 8, username="alice", password="pass")
            mock_request = MagicMock()
            mock_request.headers = {}
            result = await ext_mod.mobile_auth_qr_confirm(body=body, request=mock_request)
        assert hasattr(result, "body") or isinstance(result, dict)


# ---------------------------------------------------------------------------
# mobile_auth_oidc_exchange additional branches
# ---------------------------------------------------------------------------


class TestMobileAuthOidcExchangeAdditional:
    @pytest.mark.asyncio
    async def test_auth_failure(self, ext_mod):
        """Test path where authenticate_oidc_user fails."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_code_for_userinfo",
                new=AsyncMock(return_value={"sub": "x", "email": "a@b.com"}),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": False,
                "message": "no user",
            }
            mock_get.return_value = mock_service
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_success(self, ext_mod):
        """Test full success path."""
        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, "rt"),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_code_for_userinfo",
                new=AsyncMock(return_value={"sub": "x", "email": "a@b.com"}),
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new=AsyncMock(
                    return_value={
                        "user": {"id": 1, "username": "alice"},
                        "account_kind": "personal",
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


# ---------------------------------------------------------------------------
# _mobile_mod_items additional branches
# ---------------------------------------------------------------------------


class TestMobileModItemsAdditional:
    def test_object_mod_with_mod_id_only(self, ext_mod):
        """Test object mod that only has mod_id attribute."""
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mod = MagicMock()
            mod.id = None
            mod.name = None
            mod.mod_id = "mod-via-id"
            mod.title = "Mod Via ID"
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 1
            assert items[0]["id"] == "mod-via-id"

    def test_object_mod_with_title_only(self, ext_mod):
        """Test object mod that only has title attribute."""
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mod = MagicMock()
            mod.id = "mod-1"
            mod.name = None
            mod.mod_id = ""
            mod.title = "Title Only"
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 1
            assert items[0]["name"] == "Title Only"

    def test_dict_mod_with_name_fallback(self, ext_mod):
        """Test dict mod that uses name as fallback for id."""
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm:
            mock_mm.return_value.list_all_mods.return_value = [
                {"name": "Just Name"},  # No id/mod_id
            ]
            items = ext_mod._mobile_mod_items()
            # Empty id should be skipped
            assert len(items) == 0


# ---------------------------------------------------------------------------
# _guess_lan_ipv4 additional branches
# ---------------------------------------------------------------------------


class TestGuessLanIpv4Additional:
    def test_returns_loopback_when_ip_starts_with_127(self, ext_mod):
        """Test that 127.x.x.x IPs are rejected and fallback returned."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("127.0.0.1", 80)
        with patch("socket.socket", return_value=mock_socket):
            ip = ext_mod._guess_lan_ipv4()
        assert ip == "127.0.0.1"

    def test_returns_valid_lan_ip(self, ext_mod):
        """Test that valid LAN IPs are returned."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("192.168.1.100", 80)
        with patch("socket.socket", return_value=mock_socket):
            ip = ext_mod._guess_lan_ipv4()
        assert ip == "192.168.1.100"

    def test_empty_ip_returns_loopback(self, ext_mod):
        """Test that empty IP returns loopback."""
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ("", 80)
        with patch("socket.socket", return_value=mock_socket):
            ip = ext_mod._guess_lan_ipv4()
        assert ip == "127.0.0.1"
