"""Tests for app.fastapi_routes.xcmax_admin — additional coverage (ext2).

Focus: _market_admin_proxy additional branches (no authorization, proxy error payload,
JSONResponse passthrough), _digest_local_or_proxy local paths (daily-digests list,
daily-digests single, daily-digests artifacts, action-items stats, action-items list,
local read failure), _remote_duty_health (dict passthrough, JSONResponse body parsing,
fallback), admin routes (admin_list_market_users, admin_bind_user_mod, admin_unbind_user_mod,
admin_set_user_admin, admin_set_user_enterprise, admin_list_user_mods,
admin_list_assignable_mods, admin_list_user_wechat_customers, admin_save_user_wechat_customers,
admin_start_impersonate success, admin_end_impersonate, get_digest_identity 404 fallback,
get_digest_identity dict passthrough, ops_duty_health, ops_dispatch, ops_jobs, ops_duty_runs,
ops_duty_run_detail, ops_closure_status, ops_staffing_onboard, ops_staffing_install_local,
ops_staffing_close_gap), _xcmax_market_proxy_impl, _sync_sse_generator.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_routes.router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    return TestClient(app_with_router, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _market_admin_proxy additional branches
# ---------------------------------------------------------------------------


class TestMarketAdminProxyAdditional:
    @pytest.mark.asyncio
    async def test_no_authorization_returns_401(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value=None,
            ),
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_proxy_error_payload(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(
                    return_value={
                        "__proxy_error__": True,
                        "status_code": 502,
                        "payload": {"error": "upstream fail"},
                    }
                ),
            ),
            patch(
                "app.fastapi_routes.market_account._error_message",
                return_value="upstream error",
            ),
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_proxy_returns_jsonresponse(self):
        req = MagicMock(spec=Request)
        json_resp = JSONResponse({"success": False}, status_code=400)
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value=json_resp),
            ),
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
        assert result is json_resp

    @pytest.mark.asyncio
    async def test_proxy_returns_dict_payload(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"success": True, "data": {"id": 1}}),
            ),
        ):
            result = await admin_routes._market_admin_proxy(req, "GET", "/api/test")
        assert isinstance(result, dict)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_require_admin_session_true_gate(self):
        """When require_admin_session=True and gate fails, returns gate."""
        req = MagicMock(spec=Request)
        gate_resp = JSONResponse({"success": False}, status_code=401)
        with patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=gate_resp,
        ):
            result = await admin_routes._market_admin_proxy(
                req, "GET", "/api/test", require_admin_session=True
            )
        assert result is gate_resp

    @pytest.mark.asyncio
    async def test_require_admin_session_false_skips_gate(self):
        """When require_admin_session=False, gate is not checked."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._require_market_admin_session",
                return_value=JSONResponse({"success": False}, status_code=401),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"success": True}),
            ),
        ):
            result = await admin_routes._market_admin_proxy(
                req, "GET", "/api/test", require_admin_session=False
            )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _digest_local_or_proxy local paths
# ---------------------------------------------------------------------------


class TestDigestLocalOrProxyLocalPaths:
    @pytest.mark.asyncio
    async def test_local_daily_digests_list(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_daily_digests_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests?limit=10&offset=5"
            )
        assert isinstance(result, dict)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_local_daily_digests_single(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.get_daily_digest_local",
                new=AsyncMock(return_value={"success": True, "data": {"id": 1}}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests/123"
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_local_daily_digests_artifacts(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.get_daily_digest_artifacts_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests/123/artifacts"
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_local_action_items_stats(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.action_items_stats_local",
                new=AsyncMock(return_value={"success": True, "data": {}}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/admin/action-items/stats?kind=patch&day=2026-06-17"
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_local_action_items_list(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_action_items_local",
                new=AsyncMock(return_value={"success": True, "data": []}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/admin/action-items?kind=patch&day=2026-06-17"
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_local_read_failure(self):
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_daily_digests_local",
                new=AsyncMock(side_effect=RuntimeError("local fail")),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "GET", "/api/agent/butler/daily-digests?limit=10"
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_non_get_method_skips_local(self):
        """Non-GET methods should skip local path and go to proxy."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True, "proxied": True}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req, "POST", "/api/agent/butler/daily-digests"
            )
        assert isinstance(result, dict)
        assert result.get("proxied") is True

    @pytest.mark.asyncio
    async def test_unknown_path_falls_through_to_proxy(self):
        """Unknown path in local mode falls through to proxy."""
        req = MagicMock(spec=Request)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True, "proxied": True}),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(req, "GET", "/api/unknown/path")
        assert isinstance(result, dict)
        assert result.get("proxied") is True


# ---------------------------------------------------------------------------
# _remote_duty_health
# ---------------------------------------------------------------------------


class TestRemoteDutyHealth:
    @pytest.mark.asyncio
    async def test_dict_passthrough(self):
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"healthy": True, "staffing": {}}),
        ):
            result = await admin_routes._remote_duty_health(req)
        assert isinstance(result, dict)
        assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_jsonresponse_body_parsing(self):
        req = MagicMock(spec=Request)
        mock_resp = MagicMock()
        mock_resp.body = json.dumps({"healthy": True}).encode("utf-8")
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await admin_routes._remote_duty_health(req)
        assert isinstance(result, dict)
        assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_jsonresponse_body_invalid_json(self):
        req = MagicMock(spec=Request)
        mock_resp = MagicMock()
        mock_resp.body = b"not json"
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await admin_routes._remote_duty_health(req)
        assert result == {}

    @pytest.mark.asyncio
    async def test_non_dict_non_jsonresponse(self):
        req = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value="some string"),
        ):
            result = await admin_routes._remote_duty_health(req)
        assert result == {}


# ---------------------------------------------------------------------------
# Admin route handlers
# ---------------------------------------------------------------------------


class TestAdminRouteHandlers:
    @pytest.mark.asyncio
    async def test_admin_list_market_users(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/market/users")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_assignable_mods(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/market/assignable-mods")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_user_mods(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/market/users/1/mods")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_bind_user_mod(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch("app.application.session_account_meta.audit_admin_action"),
        ):
            response = client.post("/api/xcmax/admin/market/users/1/mods/test_mod")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_unbind_user_mod(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch("app.application.session_account_meta.audit_admin_action"),
        ):
            response = client.delete("/api/xcmax/admin/market/users/1/mods/test_mod")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_set_user_admin(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.put("/api/xcmax/admin/market/users/1/admin?is_admin=true")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_set_user_enterprise(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.put("/api/xcmax/admin/market/users/1/enterprise?is_enterprise=false")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_user_wechat_customers_no_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/admin/market/users/1/wechat-customers")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_list_user_wechat_customers_with_session(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.get_bindings_for_user",
                return_value=[{"id": 1}],
            ),
        ):
            response = client.get("/api/xcmax/admin/market/users/1/wechat-customers")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_user_wechat_customers_error(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.get_bindings_for_user",
                side_effect=RuntimeError("fail"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            response = client.get("/api/xcmax/admin/market/users/1/wechat-customers")
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_admin_save_user_wechat_customers(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ),
        ):
            response = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": [1, 2]},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_save_user_wechat_customers_invalid_ids(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ) as mock_save,
        ):
            response = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": "not a list"},
            )
        assert response.status_code == 200
        # Verify empty list passed
        mock_save.assert_called_once()
        args, _ = mock_save.call_args
        assert args[1] == []

    @pytest.mark.asyncio
    async def test_admin_save_user_wechat_customers_error(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                side_effect=RuntimeError("fail"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            response = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": [1]},
            )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Impersonate routes — additional
# ---------------------------------------------------------------------------


class TestImpersonateRoutesAdditional:
    @pytest.mark.asyncio
    async def test_impersonate_success(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch("app.application.session_account_meta.persist_session_account_meta"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value="Bearer tok"),
            ),
            patch(
                "app.enterprise.mod_entitlements.refresh_session_entitlements_from_market",
                new=AsyncMock(return_value=["mod1"]),
            ),
            patch("app.enterprise.mod_entitlements.persist_entitlements_to_session_row"),
            patch(
                "app.enterprise.mod_entitlements.reload_enterprise_mods_after_login",
                new=AsyncMock(),
            ),
            patch("app.application.session_account_meta.audit_admin_action"),
        ):
            response = client.post(
                "/api/xcmax/admin/impersonate",
                json={"market_user_id": 42, "username": "alice"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_impersonate_no_token(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch("app.application.session_account_meta.persist_session_account_meta"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value=None),
            ),
            patch("app.application.session_account_meta.audit_admin_action"),
        ):
            response = client.post(
                "/api/xcmax/admin/impersonate",
                json={"market_user_id": 42, "username": "alice"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_end_impersonate_success(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch("app.application.session_account_meta.clear_impersonation"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value="Bearer tok"),
            ),
            patch(
                "app.enterprise.mod_entitlements.refresh_session_entitlements_from_market",
                new=AsyncMock(return_value=["mod1"]),
            ),
            patch("app.enterprise.mod_entitlements.persist_entitlements_to_session_row"),
            patch(
                "app.enterprise.mod_entitlements.reload_enterprise_mods_after_login",
                new=AsyncMock(),
            ),
            patch("app.application.session_account_meta.audit_admin_action"),
        ):
            response = client.post("/api/xcmax/admin/impersonate/end")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_end_impersonate_no_token(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch("app.application.session_account_meta.clear_impersonation"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value=None),
            ),
            patch("app.application.session_account_meta.audit_admin_action"),
        ):
            response = client.post("/api/xcmax/admin/impersonate/end")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_end_impersonate_no_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.post("/api/xcmax/admin/impersonate/end")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# get_digest_identity
# ---------------------------------------------------------------------------


class TestGetDigestIdentity:
    @pytest.mark.asyncio
    async def test_404_fallback(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://api.example.com",
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=JSONResponse({"detail": "not found"}, status_code=404)),
            ),
        ):
            response = client.get("/api/xcmax/admin/digest-identity")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["code"] == ""
        assert data["data"]["digest_api_base"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_dict_passthrough(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://api.example.com",
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(
                    return_value={"success": True, "data": {"code": "abc", "valid": True}}
                ),
            ),
        ):
            response = client.get("/api/xcmax/admin/digest-identity")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["code"] == "abc"
        assert data["data"]["digest_api_base"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_other_response_passthrough(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://api.example.com",
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(
                    return_value=JSONResponse({"detail": "server error"}, status_code=500)
                ),
            ),
        ):
            response = client.get("/api/xcmax/admin/digest-identity")
        # Non-404 JSONResponse should be returned as-is
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Ops routes — additional
# ---------------------------------------------------------------------------


class TestOpsRoutesAdditional:
    @pytest.mark.asyncio
    async def test_ops_duty_health_dict(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True, "staffing": {}}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "remote_health": {"healthy": True},
                    "staffing": {"filled": 5},
                    "planned_employee_ids": ["e1"],
                    "registered_employee_ids": ["e1"],
                    "planned_local_installed_count": 1,
                    "extra_local_employee_pack_ids": [],
                },
            ),
        ):
            response = client.get("/api/xcmax/ops/duty-health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_duty_health_non_dict(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value="not a dict"),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "remote_health": {"healthy": False},
                    "staffing": {"filled": 0},
                },
            ),
        ):
            response = client.get("/api/xcmax/ops/duty-health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_dispatch(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post("/api/xcmax/ops/dispatch", json={"action": "test"})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_jobs_list(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/ops/jobs?limit=10")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_job_detail_valid(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True, "data": {"id": "job1"}}),
        ):
            response = client.get("/api/xcmax/ops/jobs/job-123")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_job_detail_invalid(self, client: TestClient):
        # Use a job_id that sanitizes to empty (only alnum/-/_ are kept) to
        # exercise the 400 "job_id 无效" branch. A trailing slash would be
        # redirected to the list endpoint and return 401 (no auth).
        response = client.get("/api/xcmax/ops/jobs/%21%21%21")
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_ops_duty_runs(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post("/api/xcmax/ops/duty-runs", json={"run_id": 1})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_duty_run_detail_valid(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True, "data": {"id": 1}}),
        ):
            response = client.get("/api/xcmax/ops/duty-runs/1")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_closure_status_no_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.get("/api/xcmax/ops/closure-status")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_ops_closure_status_with_session(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={"staffing": {"filled": 5}},
            ),
        ):
            response = client.get("/api/xcmax/ops/closure-status")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_onboard_list_ids(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"employee_ids": ["e1", "e2"], "dry_run": True},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_onboard_string_ids(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/onboard",
                json={"pkg_ids": "e1,e2", "force": True},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_install_local_no_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": "e1"},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_ops_staffing_install_local_missing_id(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": ""},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_ops_staffing_install_local_success(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value={"success": True, "message": "ok"}),
            ),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": "e1"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_install_local_pydantic_model(self, client: TestClient):
        mock_model = MagicMock()
        mock_model.model_dump.return_value = {"success": True, "data": {"id": "e1"}}
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value=mock_model),
            ),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": "e1"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_install_local_error(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(side_effect=RuntimeError("install fail")),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": "e1"},
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_ops_staffing_close_gap_no_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            response = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_ops_staffing_close_gap_no_missing(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": [],
                    "missing_local_employee_packs": [],
                },
            ),
        ):
            response = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_close_gap_with_onboard(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": ["e1"],
                    "missing_local_employee_packs": [],
                },
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True}),
            ),
        ):
            response = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_close_gap_with_install(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": [],
                    "missing_local_employee_packs": ["e1"],
                },
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value={"success": True, "message": "ok"}),
            ),
        ):
            response = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_close_gap_install_error(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": [],
                    "missing_local_employee_packs": ["e1"],
                },
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(side_effect=RuntimeError("install fail")),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            response = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_staffing_close_gap_skip_onboard(self, client: TestClient):
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": ["e1"],
                    "missing_local_employee_packs": [],
                },
            ),
        ):
            response = client.post(
                "/api/xcmax/ops/staffing/close-gap",
                json={"skip_onboard": True, "skip_install": True},
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Daily digest routes
# ---------------------------------------------------------------------------


class TestDailyDigestRoutes:
    @pytest.mark.asyncio
    async def test_list_daily_digests(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/daily-digests?limit=10&offset=0")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_daily_digest(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": {"id": 1}}),
        ):
            response = client.get("/api/xcmax/admin/daily-digests/1")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_daily_digest_artifacts(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/daily-digests/1/artifacts")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_action_items(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/action-items?kind=patch&day=2026-06-17")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_action_items_no_params(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": []}),
        ):
            response = client.get("/api/xcmax/admin/action-items")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_action_items_stats(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": {}}),
        ):
            response = client.get("/api/xcmax/admin/action-items/stats?kind=patch&day=2026-06-17")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_action_items_stats_no_params(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._digest_local_or_proxy",
            new=AsyncMock(return_value={"success": True, "data": {}}),
        ):
            response = client.get("/api/xcmax/admin/action-items/stats")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_start_digest_vibe_prep_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post(
                "/api/xcmax/admin/daily-digests/1/vibe-prep/sessions",
                json={"option": "value"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_start_digest_line_execute(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post(
                "/api/xcmax/admin/daily-digests/1/line-execute",
                json={"option": "value"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_digest_vibe_prep_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/abc123")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_digest_vibe_prep_session_empty_id(self, client: TestClient):
        response = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/")
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_start_all_hands_report_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.post(
                "/api/xcmax/admin/all-hands-report/sessions",
                json={"option": "value"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_all_hands_report_session(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.get("/api/xcmax/admin/all-hands-report/sessions/abc123")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# _xcmax_market_proxy_impl
# ---------------------------------------------------------------------------


class TestXcmaxMarketProxyImpl:
    @pytest.mark.asyncio
    async def test_get_request(self):
        req = MagicMock(spec=Request)
        req.method = "GET"
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_post_request_with_body(self):
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.json = AsyncMock(return_value={"key": "value"})
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_post_request_with_non_dict_body(self):
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.json = AsyncMock(return_value=[1, 2, 3])  # list, not dict
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_post_request_invalid_json(self):
        req = MagicMock(spec=Request)
        req.method = "POST"
        req.json = AsyncMock(side_effect=ValueError("invalid json"))
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (ValueError,),
            ),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_put_request(self):
        req = MagicMock(spec=Request)
        req.method = "PUT"
        req.json = AsyncMock(return_value={"key": "value"})
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "test/path")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_market_proxy_routes_registered(self, client: TestClient):
        """Test that market-proxy routes are accessible."""
        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            new=AsyncMock(return_value={"success": True}),
        ):
            response = client.get("/api/xcmax/market-proxy/test/path")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# _sync_sse_generator
# ---------------------------------------------------------------------------


class TestSyncSseGenerator:
    @pytest.mark.asyncio
    async def test_generator_with_changes(self):
        req = MagicMock(spec=Request)
        req.is_disconnected = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.get_changes.return_value = [{"id": 1, "entity_type": "product"}]
        mock_db.get_status.return_value = {"healthy": True}

        # Generator yields connected event, then changes, then we break by disconnecting
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            gen = admin_routes._sync_sse_generator(req, since_cursor=0)
            # Consume first event (connected)
            first = await gen.__anext__()
            assert "connected" in first
            # Consume second event (changes)
            second = await gen.__anext__()
            assert "cursor" in second
            # Now disconnect
            req.is_disconnected = AsyncMock(return_value=True)
            # Should stop on next iteration
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

    @pytest.mark.asyncio
    async def test_generator_with_heartbeat(self):
        req = MagicMock(spec=Request)
        req.is_disconnected = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.get_changes.return_value = []  # No changes
        mock_db.get_status.return_value = {"healthy": True}

        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            gen = admin_routes._sync_sse_generator(req, since_cursor=0)
            first = await gen.__anext__()
            assert "connected" in first
            second = await gen.__anext__()
            assert "heartbeat" in second
            req.is_disconnected = AsyncMock(return_value=True)
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

    @pytest.mark.asyncio
    async def test_generator_with_error(self):
        req = MagicMock(spec=Request)
        req.is_disconnected = AsyncMock(return_value=False)

        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db error"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            gen = admin_routes._sync_sse_generator(req, since_cursor=0)
            first = await gen.__anext__()
            assert "connected" in first
            second = await gen.__anext__()
            assert "error" in second
            req.is_disconnected = AsyncMock(return_value=True)
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()


# ---------------------------------------------------------------------------
# sync_receive additional
# ---------------------------------------------------------------------------


class TestSyncReceiveAdditional:
    @pytest.mark.asyncio
    async def test_sync_receive_apply_error(self):
        mock_db = MagicMock()
        mock_db.enqueue_inbox.return_value = 1
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                side_effect=RuntimeError("apply fail"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
            patch("app.mod_sdk.audit.write_audit_event"),
        ):
            result = await admin_routes.sync_receive({"entity_type": "product"})
        assert result["success"] is True
        assert result["received"] == 1
        assert "error" in result["apply_result"]

    @pytest.mark.asyncio
    async def test_sync_receive_audit_error(self):
        mock_db = MagicMock()
        mock_db.enqueue_inbox.return_value = 1
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.application.xcmax_sync_app.apply_inbox",
                return_value={"applied": 1},
            ),
            patch(
                "app.mod_sdk.audit.write_audit_event",
                side_effect=RuntimeError("audit fail"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await admin_routes.sync_receive({"entity_type": "product"})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_sync_receive_db_error(self):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db init fail"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            result = await admin_routes.sync_receive({"entity_type": "product"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# resolve_conflict additional
# ---------------------------------------------------------------------------


class TestResolveConflictAdditional:
    @pytest.mark.asyncio
    async def test_resolve_conflict_apply_with_applier(self, client: TestClient):
        mock_db = MagicMock()
        mock_applier = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.fetch_inbox_row",
                return_value={"entity_type": "product", "payload": "{}"},
            ),
            patch(
                "app.application.xcmax_sync_app.entity_appliers",
                return_value={"product": mock_applier},
            ),
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "apply"},
            )
        assert response.status_code == 200
        mock_applier.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_conflict_apply_no_row(self, client: TestClient):
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.fetch_inbox_row",
                return_value=None,
            ),
            patch(
                "app.application.xcmax_sync_app.entity_appliers",
                return_value={},
            ),
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "apply"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_resolve_conflict_apply_no_applier(self, client: TestClient):
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.fetch_inbox_row",
                return_value={"entity_type": "unknown", "payload": "{}"},
            ),
            patch(
                "app.application.xcmax_sync_app.entity_appliers",
                return_value={},  # No applier for "unknown"
            ),
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "apply"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_resolve_conflict_error(self, client: TestClient):
        with (
            patch(
                "app.db.xcmax_sync.SyncDb",
                side_effect=RuntimeError("db fail"),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin.RECOVERABLE_ERRORS",
                (RuntimeError,),
            ),
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={"action": "skip"},
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_resolve_conflict_default_action(self, client: TestClient):
        """Default action should be 'skip'."""
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
            patch(
                "app.services.admin_sync_service.mark_inbox_skipped",
            ) as mock_skip,
        ):
            response = client.post(
                "/api/xcmax/sync/conflicts/1/resolve",
                json={},  # No action specified
            )
        assert response.status_code == 200
        mock_skip.assert_called_once_with(1)
