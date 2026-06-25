"""Comprehensive tests for app.fastapi_routes.mobile_api_extensions.

Covers: pairing, device register/unregister, sync, QR confirm, OIDC exchange,
approval/shipment/customer lists, mods, home, platform-shell, and all helper functions.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
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


def _mock_pairing_request(host_header: str = "127.0.0.1:5112", hostname: str = "127.0.0.1"):
    return SimpleNamespace(
        headers={"host": host_header},
        url=SimpleNamespace(hostname=hostname),
    )


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
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ext_mod._ensure_mobile_device_table()

    def test_table_missing_creates(self, ext_mod):
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_db.get_bind.return_value = mock_bind
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = False
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
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


class TestPairingIssuePort:
    def test_requested_port_wins(self, ext_mod):
        assert ext_mod._pairing_issue_port(_mock_pairing_request(), 8788) == 8788

    def test_infers_port_from_host_header(self, ext_mod):
        assert ext_mod._pairing_issue_port(_mock_pairing_request("127.0.0.1:5112"), 0) == 5112

    def test_default_5000_yields_to_real_request_port(self, ext_mod):
        assert ext_mod._pairing_issue_port(_mock_pairing_request("127.0.0.1:17500"), 5000) == 17500


# ---------------------------------------------------------------------------
# Pairing routes (direct handler tests)
# ---------------------------------------------------------------------------


class TestPairingIssue:
    @pytest.mark.asyncio
    async def test_issue_success(self, ext_mod):
        body = ext_mod.PairingIssueBody(host="192.168.1.10", port=5000)
        request = _mock_pairing_request("192.168.1.10:5000", "192.168.1.10")
        with (
            patch.object(ext_mod, "_pairing_issue_host", return_value="192.168.1.10"),
            patch(
                "app.security.mobile_pairing.issue_pairing_nonce",
                return_value={"nonce": "abc123", "host": "192.168.1.10", "port": 5000},
            ),
        ):
            result = await ext_mod.mobile_pairing_issue(body, request)
        # format_mobile_response returns a dict
        if hasattr(result, "body"):
            import json

            data = json.loads(result.body)
        else:
            data = result
        assert data.get("success") is True or data.get("data", {}).get("host") == "192.168.1.10"

    @pytest.mark.asyncio
    async def test_issue_returns_mobile_ready_base_url(self, ext_mod):
        body = ext_mod.PairingIssueBody()
        request = _mock_pairing_request("127.0.0.1:17500", "127.0.0.1")
        with (
            patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.0.38"),
            patch.object(
                ext_mod,
                "issue_pairing_nonce",
                return_value={
                    "nonce": "abc123",
                    "host": "192.168.0.38",
                    "port": 17500,
                    "shortCode": "123456",
                    "exp": 123,
                },
            ),
            patch.object(ext_mod, "_register_desktop_relay_for_pairing", return_value=None),
        ):
            result = await ext_mod.mobile_pairing_issue(body, request)
        data = result if isinstance(result, dict) else __import__("json").loads(result.body)
        payload = data["data"]
        assert payload["api_base_url"] == "http://192.168.0.38:17500/"
        assert payload["base_url"] == "http://192.168.0.38:17500/"
        assert payload["code"] == "123456"
        assert payload["qr_json"]["api_base_url"] == "http://192.168.0.38:17500/"
        assert "xcagi://pairing?" in payload["deep_link"]

    @pytest.mark.asyncio
    async def test_issue_keeps_qr_lan_when_relay_exists(self, ext_mod):
        body = ext_mod.PairingIssueBody()
        request = _mock_pairing_request("127.0.0.1:42422", "127.0.0.1")
        with (
            patch.object(ext_mod, "_guess_lan_ipv4", return_value="192.168.0.38"),
            patch.object(
                ext_mod,
                "issue_pairing_nonce",
                return_value={
                    "nonce": "lan-nonce",
                    "host": "192.168.0.38",
                    "port": 42422,
                    "shortCode": "123456",
                    "exp": 123,
                },
            ),
            patch.object(
                ext_mod,
                "_register_desktop_relay_for_pairing",
                return_value={
                    "relay_id": "relay-account-1",
                    "pairing_code": "654321",
                    "relay_base_url": "https://relay.example.test/fhd-api/",
                    "qr_json": {"v": 3, "relay_id": "relay-account-1", "code": "654321"},
                },
            ),
        ):
            result = await ext_mod.mobile_pairing_issue(body, request)
        data = result if isinstance(result, dict) else __import__("json").loads(result.body)
        payload = data["data"]
        assert payload["code"] == "123456"
        assert payload["relay_id"] == "relay-account-1"
        assert payload["relay_binding_mode"] == "account_auth"
        assert payload["qr_json"]["kind"] == "xcagi_pairing"
        assert payload["qr_json"]["code"] == "123456"
        assert "xcagi://pairing?" in payload["deep_link"]
        assert "relay-pairing" not in payload["deep_link"]


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
        with (
            patch(
                "app.security.mobile_pairing.issue_pairing_nonce",
                return_value={"nonce": "abc123", "host": "192.168.1.10", "port": 5000},
            ),
            patch(
                "app.security.mobile_pairing.consume_pairing_nonce",
                return_value={"host": "192.168.1.10", "port": 5000, "shortCode": "123456"},
            ),
            patch.object(ext_mod, "_pairing_issue_host", return_value="192.168.1.10"),
        ):
            # First issue a pairing to get a nonce
            body_issue = ext_mod.PairingIssueBody(host="192.168.1.10", port=5000)
            issue_result = await ext_mod.mobile_pairing_issue(
                body_issue,
                _mock_pairing_request("192.168.1.10:5000", "192.168.1.10"),
            )
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
            return_value={
                "host": "192.168.1.20",
                "port": 5100,
                "nonce": "n1",
                "shortCode": "123456",
            },
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
        assert data["data"]["api_base_url"] == "http://192.168.1.20:5100/"

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


class TestServiceBridgeRoutes:
    @pytest.mark.asyncio
    async def test_codex_super_employee_messages_allows_enterprise_user(self, ext_mod):
        user = SimpleNamespace(id=901, role="enterprise")
        result_data = [{"id": 1, "text": "ok"}]
        with (
            patch.object(
                ext_mod,
                "_mobile_session_meta",
                return_value={"account_kind": "enterprise"},
            ),
            patch.object(ext_mod, "CodexSuperEmployeeService") as mock_service,
        ):
            mock_service.return_value.list_messages.return_value = result_data
            result = await ext_mod.mobile_admin_codex_super_employee_messages(
                request=_mock_pairing_request(),
                limit=80,
                user=user,
            )
        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert payload["data"]["messages"] == result_data
        mock_service.return_value.list_messages.assert_called_once_with(user_id=901, limit=80)

    @pytest.mark.asyncio
    async def test_codex_super_employee_invoke_allows_enterprise_user(self, ext_mod):
        user = SimpleNamespace(id=901, role="enterprise")
        expected = {"task_id": "t1", "request_id": "r1", "assistant_message": {"body": "done"}}
        with (
            patch.object(
                ext_mod,
                "_mobile_session_meta",
                return_value={"account_kind": "enterprise"},
            ),
            patch.object(ext_mod, "CodexSuperEmployeeService") as mock_service,
        ):
            mock_service.return_value.invoke.return_value = expected
            result = await ext_mod.mobile_admin_codex_super_employee_invoke(
                request=_mock_pairing_request(),
                body=ext_mod.CodexSuperEmployeeMobileMessageBody(message="帮我做点什么"),
                user=user,
            )
        payload = result if isinstance(result, dict) else __import__("json").loads(result.body)
        assert payload["success"] is True
        assert payload["data"] == expected
        call_kwargs = mock_service.return_value.invoke.call_args.kwargs
        assert call_kwargs["user_id"] == 901
        assert call_kwargs["message"] == "帮我做点什么"
        assert call_kwargs["context"]["source"] == "mobile_im"

    @pytest.mark.asyncio
    async def test_codex_super_employee_messages_rejects_personal_user(self, ext_mod):
        user = SimpleNamespace(id=902, role="personal")
        with patch.object(
            ext_mod,
            "_mobile_session_meta",
            return_value={"account_kind": "personal"},
        ):
            result = await ext_mod.mobile_admin_codex_super_employee_messages(
                request=_mock_pairing_request(),
                limit=80,
                user=user,
            )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_service_bridge_requests_unauthorized(self, ext_mod):
        result = await ext_mod.mobile_service_bridge_requests(
            request=_mock_pairing_request(), user=None
        )
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_service_bridge_requests_success(self, ext_mod):
        row = MagicMock()
        row.id = 1
        row.to_dict.return_value = {"id": 1, "title": "need help", "status": "pending"}
        query = MagicMock()
        query.filter.return_value = query
        query.count.return_value = 1
        query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [row]
        db = MagicMock()
        db.query.return_value = query
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        user = SimpleNamespace(id=1, username="u")
        with patch("app.db.session.get_db", return_value=db):
            result = await ext_mod.mobile_service_bridge_requests(
                request=_mock_pairing_request(), user=user, page=1, per_page=20
            )
        # result 可能是 dict（format_mobile_response 直接返回）或 JSONResponse
        if isinstance(result, dict):
            payload = result
        elif hasattr(result, "body"):
            payload = __import__("json").loads(result.body)
        else:
            payload = result
        assert payload["success"] is True
        assert payload["data"]["pagination"]["total"] == 1
        assert payload["data"]["items"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_service_bridge_respond_invalid_status(self, ext_mod):
        body = ext_mod.MobileServiceBridgeRespondBody(response="x", status="invalid")
        result = await ext_mod.mobile_service_bridge_request_respond(
            request_id=1, body=body, user=None
        )
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# _mobile_mod_items
# ---------------------------------------------------------------------------


class TestMobileModItems:
    def test_empty_list(self, ext_mod):
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = []
            assert ext_mod._mobile_mod_items() == []

    def test_dict_mods(self, ext_mod):
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": "mod-a", "name": "Mod A"},
                {"mod_id": "mod-b", "title": "Mod B"},
            ]
            items = ext_mod._mobile_mod_items()
            assert len(items) == 2
            assert items[0]["id"] == "mod-a"

    def test_object_mods(self, ext_mod):
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mod = MagicMock()
            mod.id = "mod-obj"
            mod.name = "Obj Mod"
            mod.mod_id = ""
            mod.title = ""
            mock_mm.return_value.list_all_mods.return_value = [mod]
            items = ext_mod._mobile_mod_items()
            assert items[0]["id"] == "mod-obj"

    def test_exception_returns_empty(self, ext_mod):
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("fail"),
            ),
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            assert ext_mod._mobile_mod_items() == []

    def test_limit_100(self, ext_mod):
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
            mock_mm.return_value.list_all_mods.return_value = [
                {"id": f"mod-{i}", "name": f"Mod {i}"} for i in range(150)
            ]
            assert len(ext_mod._mobile_mod_items()) == 100

    def test_empty_id_skipped(self, ext_mod):
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch("app.fastapi_routes.mobile_api_extensions._upsert_admin_duty_mod_item"),
        ):
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
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
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
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
            mock_row
        ]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            items = ext_mod._shipment_items(limit=10)
            assert len(items) == 1
            assert items[0]["id"] == 5


# ---------------------------------------------------------------------------
# AI employee market profile enrichment
# ---------------------------------------------------------------------------


class TestAiEmployeeMarketProfiles:
    def test_index_market_ai_employee_profiles_filters_non_employees(self, ext_mod):
        profiles = ext_mod._index_market_ai_employee_profiles(
            [
                {
                    "pkg_id": "deploy-release-officer",
                    "name": "发布部署主管",
                    "material_category": "ai_employee",
                    "artifact": "mod",
                },
                {"pkg_id": "theme-pack", "name": "Theme", "material_category": "theme"},
            ]
        )
        assert "deploy-release-officer" in profiles
        assert "发布部署主管" in profiles
        assert "theme-pack" not in profiles

    def test_admin_employee_items_enriches_matching_market_profile(self, ext_mod):
        with patch.object(
            ext_mod,
            "_load_admin_duty_records",
            return_value=[
                {
                    "id": "deploy-release-officer",
                    "name": "发布部署主管",
                    "description": "本地职责",
                    "stored_filename": "deploy-release-officer-1.0.0.xcemp",
                }
            ],
        ):
            items = ext_mod._admin_employee_items(
                {
                    "deploy-release-officer": {
                        "pkg_id": "deploy-release-officer",
                        "name": "发布部署主管",
                        "description": "市场资料",
                        "version": "2.0.0",
                        "author": "MODstore",
                        "industry": "企业服务",
                        "material_category": "ai_employee",
                        "license_scope": "enterprise",
                        "security_level": "enterprise",
                    }
                },
                market_connected=True,
            )

        item = next(i for i in items if i["id"] == "deploy-release-officer")
        assert item["profile_source"] == "ai_market"
        assert item["market_connected"] is True
        assert item["market_pkg_id"] == "deploy-release-officer"
        assert item["market_description"] == "市场资料"

    def test_admin_employee_items_uses_duty_roster_as_ssot(self, ext_mod):
        items = ext_mod._admin_employee_items()
        ids = {str(item.get("id") or "") for item in items}
        assert len(items) == 54
        assert len(ids) == 54
        assert "llm-ops-engineer" in ids
        assert "mobile-harmony-release-officer" in ids


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
        with patch(
            "app.infrastructure.auth.oidc_provider.verify_oidc_state", return_value=(False, "")
        ):
            body = ext_mod.OidcExchangeBody(code="abc123", state="s" * 8)
            result = await ext_mod.mobile_auth_oidc_exchange(body=body)
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_exchange_code_fails(self, ext_mod):
        async def _raise(code):
            raise RuntimeError("OIDC down")

        with (
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state", return_value=(True, "rt")
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                side_effect=_raise,
            ),
        ):
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
