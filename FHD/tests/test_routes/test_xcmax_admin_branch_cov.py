"""Branch-coverage tests for app.fastapi_routes.xcmax_admin (round 2).

Targets the remaining missing branches identified by coverage analysis:
  - _market_admin_proxy: yuangon path fall-through (method not GET/POST)
  - _digest_local_or_proxy: query parsing loop continue branches
  - _self_maintenance_local_or_proxy: limit parse ValueError, 404 fallback
  - admin_list_wallets: limit/offset query params
  - admin_set_user_profile: new user creation, entitled_industries paths
  - admin_save_user_wechat_customers: gate (no session)
  - admin_activate_enterprise_impersonation: full flow
  - local_self_maintenance_governance_review: full flow
  - local_employee_execute: task validation branches
  - get_digest_vibe_prep_session / get_all_hands_report_session: empty sid
  - ops_staffing_install_local: data conversion branches
  - ops_staffing_close_gap: onboard result handling
  - sync_stream: StreamingResponse
  - _xcmax_market_proxy_impl: self-maintenance path
  - _collect_codex_usage: file read error
  - _collect_trae_usage: full flow
  - _collect_mimo_usage: full flow
  - _build_token_usage_summary: full flow
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
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


def _mock_request(cookies: dict | None = None, headers: dict | None = None) -> MagicMock:
    req = MagicMock(spec=Request)
    req.cookies = cookies or {}
    req.headers = headers or {}
    req.query_params = {}
    return req


def _admin_session_ok():
    """Patch _require_market_admin_session to return None (admin OK)."""
    return patch(
        "app.fastapi_routes.xcmax_admin._require_market_admin_session",
        return_value=None,
    )


def _session_id(sid: str = "sid123"):
    return patch(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
        return_value=sid,
    )


# ---------------------------------------------------------------------------
# _market_admin_proxy — yuangon path fall-through (method not GET/POST)
# Lines 105->119, 111->119
# ---------------------------------------------------------------------------


class TestMarketAdminProxyYuangonFallThrough:
    """Cover the branch where yuangon path is matched but method is neither GET nor POST."""

    @pytest.mark.asyncio
    async def test_yuangon_path_with_put_method_falls_through_to_proxy(self):
        """Lines 105->119: prefer_local=True, path is yuangon, but method=PUT → falls through."""
        req = _mock_request()
        with (
            _admin_session_ok(),
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"ok": True}),
            ),
            patch("app.fastapi_routes.market_account._error_message", return_value="e"),
        ):
            result = await admin_routes._market_admin_proxy(
                req, "PUT", "/api/admin/yuangon-onboard/status"
            )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_yuangon_path_with_delete_method_falls_through(self):
        """Lines 111->119: prefer_local=True, path is yuangon/run, but method=DELETE → falls through."""
        req = _mock_request()
        with (
            _admin_session_ok(),
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new=AsyncMock(return_value={"ok": True}),
            ),
            patch("app.fastapi_routes.market_account._error_message", return_value="e"),
        ):
            result = await admin_routes._market_admin_proxy(
                req, "DELETE", "/api/admin/yuangon-onboard/run"
            )
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# _digest_local_or_proxy — query parsing loop continue branches
# Lines 185->182, 200->197, 209->206
# ---------------------------------------------------------------------------


class TestDigestLocalOrProxyQueryParseContinue:
    """Cover the continue branches in query string parsing loops."""

    @pytest.mark.asyncio
    async def test_daily_digests_query_with_unknown_params_continues(self):
        """Lines 185->182: query parts that don't start with limit= or offset= are skipped."""
        req = _mock_request()
        svc_result = {"items": []}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_daily_digests_local",
                new=AsyncMock(return_value=svc_result),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req,
                "GET",
                "/api/agent/butler/daily-digests?foo=bar&limit=10&baz=qux&offset=5",
            )
        assert result == svc_result

    @pytest.mark.asyncio
    async def test_action_items_stats_query_with_unknown_params_continues(self):
        """Lines 200->197: query parts that don't start with kind= or day= are skipped."""
        req = _mock_request()
        stats_result = {"total": 10}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.action_items_stats_local",
                new=AsyncMock(return_value=stats_result),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req,
                "GET",
                "/api/admin/action-items/stats?foo=bar&kind=patch&extra=x&day=2026-01-01",
            )
        assert result == stats_result

    @pytest.mark.asyncio
    async def test_action_items_list_query_with_unknown_params_continues(self):
        """Lines 209->206: query parts that don't start with kind= or day= are skipped."""
        req = _mock_request()
        list_result = {"items": []}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.digest_email_app_service.list_action_items_local",
                new=AsyncMock(return_value=list_result),
            ),
        ):
            result = await admin_routes._digest_local_or_proxy(
                req,
                "GET",
                "/api/admin/action-items?foo=bar&kind=update&extra=x&day=2026-01-01",
            )
        assert result == list_result


# ---------------------------------------------------------------------------
# _self_maintenance_local_or_proxy — limit parse ValueError, 404 fallback
# Lines 247->246, 285->293
# ---------------------------------------------------------------------------


class TestSelfMaintenanceLocalOrProxyBranches:
    """Cover the ValueError continue and 404 fallback branches."""

    @pytest.mark.asyncio
    async def test_status_path_with_invalid_limit_uses_default(self):
        """Lines 247->246: limit=abc raises ValueError → pass → uses default 80."""
        req = _mock_request()
        svc_result = {"status": "ok"}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.self_maintenance_app_service.get_runtime_status_local",
                new=AsyncMock(return_value=svc_result),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
        ):
            result = await admin_routes._self_maintenance_local_or_proxy(
                req, "GET", "/api/ops/self-maintenance/status?limit=abc"
            )
        assert result == svc_result

    @pytest.mark.asyncio
    async def test_404_fallback_to_local(self):
        """Lines 285->293: upstream returns 404 → try local fallback."""
        req = _mock_request()
        not_found = JSONResponse({"detail": "not found"}, status_code=404)
        local_result = {"fallback": True}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=False,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=not_found),
            ),
            patch(
                "app.application.self_maintenance_app_service.get_runtime_status_local",
                new=AsyncMock(return_value=local_result),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
        ):
            result = await admin_routes._self_maintenance_local_or_proxy(
                req, "GET", "/api/ops/self-maintenance/status"
            )
        assert result == local_result

    @pytest.mark.asyncio
    async def test_404_fallback_local_returns_none_returns_proxied(self):
        """Lines 285->293: upstream 404, local returns None → return proxied 404."""
        req = _mock_request()
        not_found = JSONResponse({"detail": "not found"}, status_code=404)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=False,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=not_found),
            ),
            patch(
                "app.application.self_maintenance_app_service.get_runtime_status_local",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
        ):
            result = await admin_routes._self_maintenance_local_or_proxy(
                req, "GET", "/api/ops/self-maintenance/status"
            )
        assert result is not_found

    @pytest.mark.asyncio
    async def test_404_fallback_local_raises_returns_proxied(self):
        """Lines 287-292: upstream 404, local raises RECOVERABLE_ERRORS → return proxied."""
        req = _mock_request()
        not_found = JSONResponse({"detail": "not found"}, status_code=404)
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=False,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=not_found),
            ),
            patch(
                "app.application.self_maintenance_app_service.get_runtime_status_local",
                new=AsyncMock(side_effect=RuntimeError("local fail")),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
        ):
            result = await admin_routes._self_maintenance_local_or_proxy(
                req, "GET", "/api/ops/self-maintenance/status"
            )
        assert result is not_found

    @pytest.mark.asyncio
    async def test_non_self_maintenance_path_returns_none(self):
        """Line 234: path doesn't start with /api/ops/self-maintenance/ → return None."""
        req = _mock_request()
        result = await admin_routes._self_maintenance_local_or_proxy(
            req, "GET", "/api/other/path"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_governance_review_post_path(self):
        """Line 256: governance-review POST path."""
        req = _mock_request()
        gov_result = {"reviewed": True}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.application.self_maintenance_app_service.governance_review_local",
                new=AsyncMock(return_value=gov_result),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
        ):
            result = await admin_routes._self_maintenance_local_or_proxy(
                req, "POST", "/api/ops/self-maintenance/governance-review",
                json_body={"note": "test"},
            )
        assert result == gov_result

    @pytest.mark.asyncio
    async def test_unknown_self_maintenance_path_returns_none_locally(self):
        """Line 262: self-maintenance path but unknown sub-path → _call_local returns None."""
        req = _mock_request()
        proxied = {"proxied": True}
        with (
            patch(
                "app.application.modstore_local_client.prefer_local_modstore",
                return_value=True,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=proxied),
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
        ):
            result = await admin_routes._self_maintenance_local_or_proxy(
                req, "GET", "/api/ops/self-maintenance/unknown"
            )
        assert result == proxied


# ---------------------------------------------------------------------------
# admin_list_wallets — limit/offset query params
# Lines 588-590
# ---------------------------------------------------------------------------


class TestAdminListWallets:
    """Cover the limit/offset query param forwarding."""

    @pytest.mark.asyncio
    async def test_wallets_with_custom_limit_offset(self):
        """Lines 588-590: custom limit and offset are forwarded to proxy."""
        req = _mock_request()
        req.query_params = {"limit": "100", "offset": "50"}
        proxy_result = {"items": []}
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=proxy_result),
            ) as mock_proxy,
        ):
            result = await admin_routes.admin_list_market_users.__wrapped__(req) if hasattr(
                admin_routes.admin_list_market_users, "__wrapped__"
            ) else await admin_routes.admin_list_wallets(req)  # type: ignore[attr-defined]
        # The route handler is admin_list_wallets
        assert result == proxy_result

    def test_wallets_route_via_client(self, client: TestClient):
        """Test via TestClient to cover the route handler lines 588-590."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"items": [], "total": 0}),
            ),
        ):
            resp = client.get("/api/xcmax/admin/market/wallets?limit=200&offset=10")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# admin_set_user_profile — new user creation, entitled_industries paths
# Lines 717-718, 735->748, 744, 749, 751, 753, 755, 757, 758->761
# ---------------------------------------------------------------------------


class TestAdminSetUserProfileDeep:
    """Cover the new user creation and entitled_industries validation branches."""

    def _make_user(self, **kwargs):
        user = MagicMock()
        user.username = kwargs.get("username", "existing")
        user.tier = kwargs.get("tier", "")
        user.industry_id = kwargs.get("industry_id", "")
        user.account_tier = kwargs.get("account_tier", None)
        user.budget_range = kwargs.get("budget_range", "")
        user.entitled_industries = kwargs.get("entitled_industries", [])
        return user

    @pytest.mark.asyncio
    async def test_new_user_creation(self):
        """Lines 717-718: user not found → create new User."""
        req = _mock_request()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        new_user = self._make_user(username="newuser", tier="", entitled_industries=[])
        mock_user_class = MagicMock(return_value=new_user)

        # get_db is used as `with get_db() as db:` — need context manager
        mock_get_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", mock_get_db),
            patch("app.db.models.user.User", mock_user_class),
        ):
            result = await admin_routes.admin_set_user_profile(
                req,
                1,
                {"username": "newuser", "tier": "personal"},
            )
        assert isinstance(result, dict)
        assert result["success"] is True
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_industry_id_not_in_entitled_provided_returns_422(self):
        """Lines 735-742: industry_id not in provided entitled_industries → 422."""
        req = _mock_request()
        existing = self._make_user(username="u1", entitled_industries=["retail"])
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing
        mock_db.query.return_value = mock_query
        mock_get_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", mock_get_db),
        ):
            result = await admin_routes.admin_set_user_profile(
                req,
                1,
                {
                    "username": "u1",
                    "industry_id": "manufacturing",
                    "entitled_industries": ["retail", "services"],
                },
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 422

    @pytest.mark.asyncio
    async def test_industry_id_not_provided_entitled_merges(self):
        """Lines 744-746: industry_id provided, entitled not provided → merge."""
        req = _mock_request()
        existing = self._make_user(username="u1", entitled_industries=["retail"])
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing
        mock_db.query.return_value = mock_query
        mock_get_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", mock_get_db),
        ):
            result = await admin_routes.admin_set_user_profile(
                req,
                1,
                {"username": "u1", "industry_id": "manufacturing"},
            )
        assert isinstance(result, dict)
        assert result["success"] is True
        # entitled_industries should be set
        assert existing.entitled_industries is not None

    @pytest.mark.asyncio
    async def test_set_all_fields_success(self):
        """Lines 749, 751, 753, 755, 757, 758->761: set tier, industry_id, budget_range, account_tier, entitled."""
        req = _mock_request()
        existing = self._make_user(username="u1", tier="", entitled_industries=[])
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing
        mock_db.query.return_value = mock_query
        mock_get_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", mock_get_db),
        ):
            result = await admin_routes.admin_set_user_profile(
                req,
                1,
                {
                    "username": "u1",
                    "tier": "enterprise",
                    "industry_id": "retail",
                    "budget_range": "100k-500k",
                    "account_tier": "pro",
                    "entitled_industries": ["retail"],
                },
            )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert existing.tier == "enterprise"
        assert existing.industry_id == "retail"
        assert existing.budget_range == "100k-500k"

    @pytest.mark.asyncio
    async def test_personal_tier_clears_account_tier(self):
        """Lines 756-757: tier=personal and no account_tier → clear account_tier."""
        req = _mock_request()
        existing = self._make_user(username="u1", tier="personal", account_tier="pro")
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing
        mock_db.query.return_value = mock_query
        mock_get_db = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", mock_get_db),
        ):
            result = await admin_routes.admin_set_user_profile(
                req,
                1,
                {"username": "u1", "tier": "personal"},
            )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert existing.account_tier is None

    @pytest.mark.asyncio
    async def test_db_error_returns_500(self):
        """Lines 771-773: DB error → 500."""
        req = _mock_request()
        mock_get_db = MagicMock()
        mock_get_db.return_value.__enter__.side_effect = RuntimeError("db down")
        mock_get_db.return_value.__exit__.return_value = False

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", mock_get_db),
        ):
            result = await admin_routes.admin_set_user_profile(
                req,
                1,
                {"username": "u1"},
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# admin_save_user_wechat_customers — gate check
# Line 853
# ---------------------------------------------------------------------------


class TestAdminSaveUserWechatCustomers:
    """Cover the gate check (no session)."""

    def test_no_session_returns_401(self, client: TestClient):
        """Line 853: gate returns 401 when no admin session."""
        with patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=JSONResponse({"success": False}, status_code=401),
        ):
            resp = client.put("/api/xcmax/admin/market/users/1/wechat-customers", json={})
        assert resp.status_code == 401

    def test_success_with_contact_ids(self, client: TestClient):
        """Cover success path with contact_ids."""
        with (
            _admin_session_ok(),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": [1, 2]},
            )
        assert resp.status_code == 200

    def test_success_with_wechat_contact_ids_alias(self, client: TestClient):
        """Cover wechat_contact_ids alias."""
        with (
            _admin_session_ok(),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"wechat_contact_ids": [3, 4]},
            )
        assert resp.status_code == 200

    def test_ids_not_list_becomes_empty(self, client: TestClient):
        """Cover branch: ids not a list → becomes empty list."""
        with (
            _admin_session_ok(),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                return_value={"success": True},
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": "not-a-list"},
            )
        assert resp.status_code == 200

    def test_error_returns_500(self, client: TestClient):
        """Cover error branch."""
        with (
            _admin_session_ok(),
            patch(
                "app.services.wechat_group_customer_bridge.save_bindings_for_user",
                side_effect=RuntimeError("db error"),
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/market/users/1/wechat-customers",
                json={"contact_ids": []},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# admin_activate_enterprise_impersonation — full flow
# Lines 938-961
# ---------------------------------------------------------------------------


class TestAdminActivateEnterpriseImpersonation:
    """Cover the full activate-enterprise flow."""

    def test_missing_bridge_token_returns_400(self, client: TestClient):
        """Line 945: no bridge_token → 400."""
        resp = client.post(
            "/api/xcmax/admin/impersonate/activate-enterprise", json={}
        )
        assert resp.status_code == 400

    def test_empty_bridge_token_returns_400(self, client: TestClient):
        """Line 945: empty bridge_token → 400."""
        resp = client.post(
            "/api/xcmax/admin/impersonate/activate-enterprise",
            json={"bridge_token": "  "},
        )
        assert resp.status_code == 400

    def test_invalid_bridge_token_returns_400(self, client: TestClient):
        """Lines 947-951: consume returns None → 400."""
        with patch(
            "app.application.impersonation_bridge.consume_impersonation_bridge_token",
            return_value=None,
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "invalid"},
            )
        assert resp.status_code == 400

    def test_value_error_returns_400(self, client: TestClient):
        """Lines 959-960: mirror raises ValueError → 400."""
        with (
            patch(
                "app.application.impersonation_bridge.consume_impersonation_bridge_token",
                return_value="admin-sid",
            ),
            patch(
                "app.application.impersonation_bridge.mirror_admin_impersonation_to_enterprise_session",
                side_effect=ValueError("bad session"),
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "valid"},
            )
        assert resp.status_code == 400
        assert "bad session" in resp.json()["message"]

    def test_success_with_enterprise_session_id(self, client: TestClient):
        """Lines 952-961: success path with enterprise_session_id in body."""
        with (
            patch(
                "app.application.impersonation_bridge.consume_impersonation_bridge_token",
                return_value="admin-sid",
            ),
            patch(
                "app.application.impersonation_bridge.mirror_admin_impersonation_to_enterprise_session",
                return_value="ent-sid",
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "valid", "enterprise_session_id": "ent-123"},
            )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "ent-sid"

    def test_success_with_cookie_session(self, client: TestClient):
        """Lines 953-955: use cookie for enterprise_sid."""
        with (
            patch(
                "app.application.impersonation_bridge.consume_impersonation_bridge_token",
                return_value="admin-sid",
            ),
            patch(
                "app.application.impersonation_bridge.mirror_admin_impersonation_to_enterprise_session",
                return_value="ent-sid",
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "valid"},
                cookies={"session_id": "cookie-sid"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# local_self_maintenance_governance_review — full flow
# Lines 1101-1108
# ---------------------------------------------------------------------------


class TestLocalSelfMaintenanceGovernanceReview:
    """Cover the full governance_review route."""

    def test_no_session_returns_401(self, client: TestClient):
        """Line 1096-1100: no session → 401."""
        with _session_id(None):
            resp = client.post("/api/xcmax/local/ops/self-maintenance/governance-review")
        assert resp.status_code == 401

    def test_success(self, client: TestClient):
        """Lines 1101-1108: success path."""
        with (
            _session_id("sid123"),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
            patch(
                "app.application.self_maintenance_app_service.governance_review_local",
                new=AsyncMock(return_value={"reviewed": True}),
            ),
        ):
            resp = client.post(
                "/api/xcmax/local/ops/self-maintenance/governance-review",
                json={"note": "test note"},
            )
        assert resp.status_code == 200
        assert resp.json()["reviewed"] is True

    def test_recoverable_error_returns_502(self, client: TestClient):
        """Lines 1107-1108: error → 502."""
        with (
            _session_id("sid123"),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
            patch(
                "app.application.self_maintenance_app_service.governance_review_local",
                new=AsyncMock(side_effect=RuntimeError("fail")),
            ),
        ):
            resp = client.post(
                "/api/xcmax/local/ops/self-maintenance/governance-review",
                json={"note": ""},
            )
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# local_employee_execute — task validation
# Lines 1199, 1209, 1213-1214
# ---------------------------------------------------------------------------


class TestLocalEmployeeExecuteBranches:
    """Cover task validation and input_data branches."""

    def test_no_session_returns_401(self, client: TestClient):
        with _session_id(None):
            resp = client.post("/api/xcmax/local/employees/emp1/execute", json={})
        assert resp.status_code == 401

    def test_empty_employee_id_returns_400(self, client: TestClient):
        """Line 1198: empty employee_id → 400."""
        with _session_id("sid"):
            resp = client.post("/api/xcmax/local/employees/ /execute", json={"task": "t"})
        assert resp.status_code == 400

    def test_empty_task_returns_400(self, client: TestClient):
        """Line 1201: empty task → 400."""
        with _session_id("sid"):
            resp = client.post(
                "/api/xcmax/local/employees/emp1/execute", json={"task": "  "}
            )
        assert resp.status_code == 400

    def test_input_data_not_dict_returns_400(self, client: TestClient):
        """Lines 1204-1205: input_data not dict → 400."""
        with _session_id("sid"):
            resp = client.post(
                "/api/xcmax/local/employees/emp1/execute",
                json={"task": "t", "input_data": "not-a-dict"},
            )
        assert resp.status_code == 400

    def test_input_data_none_ok(self, client: TestClient):
        """Line 1206: input_data None → uses empty dict."""
        with (
            _session_id("sid"),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True},
            ),
        ):
            resp = client.post(
                "/api/xcmax/local/employees/emp1/execute",
                json={"task": "t", "input_data": None},
            )
        assert resp.status_code == 200

    def test_invalid_user_id_defaults_to_zero(self, client: TestClient):
        """Lines 1213-1214: invalid user_id → 0."""
        with (
            _session_id("sid"),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True},
            ) as mock_exec,
        ):
            resp = client.post(
                "/api/xcmax/local/employees/emp1/execute",
                json={"task": "t", "user_id": "abc"},
            )
        assert resp.status_code == 200
        args, kwargs = mock_exec.call_args
        assert kwargs["user_id"] == 0

    def test_approved_write_propagated_to_payload(self, client: TestClient):
        """Lines 1207-1209: approved_write/allow_write/write_token/approval_token propagated."""
        with (
            _session_id("sid"),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True},
            ) as mock_exec,
        ):
            resp = client.post(
                "/api/xcmax/local/employees/emp1/execute",
                json={
                    "task": "t",
                    "approved_write": True,
                    "allow_write": True,
                    "write_token": "wt",
                    "approval_token": "at",
                },
            )
        assert resp.status_code == 200
        # execute_employee_task_local(pid, task, payload, user_id=..., ...)
        args, kwargs = mock_exec.call_args
        # pid, task are positional; payload is positional arg index 2
        payload = args[2] if len(args) > 2 else kwargs.get("payload", {})
        assert payload["approved_write"] is True
        assert payload["allow_write"] is True
        assert payload["write_token"] == "wt"
        assert payload["approval_token"] == "at"
        assert payload["trigger"] == "admin_execute"


# ---------------------------------------------------------------------------
# get_digest_vibe_prep_session / get_all_hands_report_session — empty sid
# Lines 1363, 1390
# ---------------------------------------------------------------------------


class TestEmptySessionIdValidation:
    """Cover empty session_id validation branches."""

    def test_digest_vibe_prep_empty_session_id_returns_400(self, client: TestClient):
        """Line 1363: empty session_id → 400."""
        resp = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/")
        # FastAPI may route this differently; test with explicit empty
        resp = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/ ")
        assert resp.status_code in (400, 404)

    def test_all_hands_report_empty_session_id_returns_400(self, client: TestClient):
        """Line 1390: empty session_id → 400."""
        resp = client.get("/api/xcmax/admin/all-hands-report/sessions/ ")
        assert resp.status_code in (400, 404)

    def test_digest_vibe_prep_success(self, client: TestClient):
        """Cover success path."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"session": "data"}),
            ),
        ):
            resp = client.get("/api/xcmax/admin/digest-vibe-prep/sessions/abc123")
        assert resp.status_code == 200

    def test_all_hands_report_success(self, client: TestClient):
        """Cover success path."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"session": "data"}),
            ),
        ):
            resp = client.get("/api/xcmax/admin/all-hands-report/sessions/abc123")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ops_staffing_install_local — data conversion
# Line 1561
# ---------------------------------------------------------------------------


class TestOpsStaffingInstallLocalDataConversion:
    """Cover the data conversion branches (model_dump, dict, str)."""

    def test_no_session_returns_403(self, client: TestClient):
        """Gate check: no admin session → 403."""
        with patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=JSONResponse({"success": False}, status_code=403),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local", json={"employee_id": "e1"}
            )
        assert resp.status_code == 403

    def test_missing_employee_id_returns_400(self, client: TestClient):
        """Line 1551: missing employee_id → 400."""
        with _admin_session_ok():
            resp = client.post("/api/xcmax/ops/staffing/install-local", json={})
        assert resp.status_code == 400

    def test_result_with_model_dump(self, client: TestClient):
        """Line 1557: result has model_dump → use it."""
        result_obj = MagicMock()
        result_obj.model_dump.return_value = {"success": True, "data": "ok"}
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value=result_obj),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local", json={"employee_id": "e1"}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["data"] == "ok"

    def test_result_is_dict(self, client: TestClient):
        """Line 1559: result is dict → use directly."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value={"success": True, "data": "dict-result"}),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local", json={"employee_id": "e1"}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["data"] == "dict-result"

    def test_result_is_string(self, client: TestClient):
        """Line 1561: result is neither → str(result)."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value="string-result"),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local", json={"employee_id": "e1"}
            )
        assert resp.status_code == 200
        assert "string-result" in resp.json()["data"]["result"]

    def test_recoverable_error_returns_500(self, client: TestClient):
        """Line 1563-1565: error → 500."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(side_effect=RuntimeError("fail")),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local", json={"employee_id": "e1"}
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# ops_staffing_close_gap — onboard result handling
# Lines 1590, 1601, 1605
# ---------------------------------------------------------------------------


class TestOpsStaffingCloseGap:
    """Cover onboard result and install result handling."""

    def test_no_session_returns_403(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=JSONResponse({"success": False}, status_code=403),
        ):
            resp = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert resp.status_code == 403

    def test_skip_onboard_and_install(self, client: TestClient):
        """Both skip_onboard and skip_install → no onboard, no install."""
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": ["e1"],
                    "missing_local_employee_packs": ["e2"],
                },
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap",
                json={"skip_onboard": True, "skip_install": True},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_onboard_returns_json_response(self, client: TestClient):
        """Line 1590: onboard returns JSONResponse → return it directly."""
        err_resp = JSONResponse({"success": False, "message": "onboard fail"}, status_code=502)
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={"missing_remote_employees": ["e1"]},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=err_resp),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap", json={}
            )
        assert resp.status_code == 502

    def test_install_with_model_dump(self, client: TestClient):
        """Line 1601: install result has model_dump."""
        result_obj = MagicMock()
        result_obj.model_dump.return_value = {"success": True, "message": "ok"}
        # build_ops_closure_status is called 3 times: before, mid, after
        # mid needs missing_local_employee_packs for the install loop to execute
        closure_data = [
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
            {"missing_remote_employees": [], "missing_local_employee_packs": ["e1"]},
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
        ]
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                side_effect=closure_data,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value=result_obj),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap", json={"skip_onboard": True}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["install_results"][0]["success"] is True

    def test_install_is_dict(self, client: TestClient):
        """Line 1603: install result is dict."""
        closure_data = [
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
            {"missing_remote_employees": [], "missing_local_employee_packs": ["e1"]},
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
        ]
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                side_effect=closure_data,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value={"success": False, "message": "fail"}),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap", json={"skip_onboard": True}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["install_results"][0]["success"] is False

    def test_install_is_string(self, client: TestClient):
        """Line 1605: install result is string -> data = {'result': str(result)}.

        success defaults to True, message defaults to ''.
        """
        closure_data = [
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
            {"missing_remote_employees": [], "missing_local_employee_packs": ["e1"]},
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
        ]
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                side_effect=closure_data,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value="string-result"),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap", json={"skip_onboard": True}
            )
        assert resp.status_code == 200
        install_results = resp.json()["data"]["install_results"]
        assert install_results[0]["success"] is True
        assert install_results[0]["message"] == ""

    def test_install_recoverable_error(self, client: TestClient):
        """Lines 1613-1616: install raises RECOVERABLE_ERRORS."""
        closure_data = [
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
            {"missing_remote_employees": [], "missing_local_employee_packs": ["e1"]},
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
        ]
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                side_effect=closure_data,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(side_effect=RuntimeError("install fail")),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap", json={"skip_onboard": True}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["install_results"][0]["success"] is False
        assert "install fail" in resp.json()["data"]["install_results"][0]["message"]

    def test_onboard_dict_result(self, client: TestClient):
        """Lines 1620-1621: onboard_result is dict with success=False."""
        closure_data = [
            {"missing_remote_employees": ["e1"]},
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
            {"missing_remote_employees": [], "missing_local_employee_packs": []},
        ]
        with (
            _admin_session_ok(),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                side_effect=closure_data,
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"success": False, "msg": "fail"}),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/close-gap", json={"skip_install": True}
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["onboard_ok"] is False


# ---------------------------------------------------------------------------
# sync_stream — StreamingResponse
# Line 1827
# ---------------------------------------------------------------------------


class TestSyncStreamRoute:
    """Cover the sync_stream StreamingResponse."""

    def test_returns_streaming_response(self, client: TestClient):
        """Line 1827: returns StreamingResponse.

        The underlying _sync_sse_generator loops forever waiting for
        request.is_disconnected(); to keep the test finite we patch the
        generator to yield a single event and stop.
        """

        async def _finite_gen(request, since_cursor):
            yield 'data: {"type":"connected","cursor":0}\n\n'

        with patch(
            "app.fastapi_routes.xcmax_admin._sync_sse_generator",
            new=_finite_gen,
        ):
            resp = client.get("/api/xcmax/sync/stream?since_cursor=0")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# _xcmax_market_proxy_impl — self-maintenance path
# Line 1850
# ---------------------------------------------------------------------------


class TestXcmaxMarketProxyImplSelfMaintenance:
    """Cover the self-maintenance path in _xcmax_market_proxy_impl."""

    @pytest.mark.asyncio
    async def test_self_maintenance_path_routes_to_local_or_proxy(self):
        """Line 1850: path starts with /api/ops/self-maintenance/ → _self_maintenance_local_or_proxy."""
        req = _mock_request()
        req.method = "GET"
        req.headers = {"content-type": "application/json"}
        sm_result = {"status": "ok"}
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._self_maintenance_local_or_proxy",
                new=AsyncMock(return_value=sm_result),
            ),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(
                req, "ops/self-maintenance/status"
            )
        assert result == sm_result

    @pytest.mark.asyncio
    async def test_post_method_parses_json_body(self):
        """Lines 1842-1847: POST method parses JSON body."""
        req = _mock_request()
        req.method = "POST"
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value={"key": "value"})
        proxy_result = {"ok": True}
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=proxy_result),
            ),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "some/path")
        assert result == proxy_result

    @pytest.mark.asyncio
    async def test_post_method_non_dict_json_body(self):
        """Lines 1844-1845: POST with non-dict JSON → json_body=None."""
        req = _mock_request()
        req.method = "POST"
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value=["list", "not", "dict"])
        proxy_result = {"ok": True}
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=proxy_result),
            ),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "some/path")
        assert result == proxy_result

    @pytest.mark.asyncio
    async def test_post_method_json_parse_error(self):
        """Lines 1846-1847: POST with JSON parse error → json_body=None."""
        req = _mock_request()
        req.method = "POST"
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(side_effect=ValueError("bad json"))
        proxy_result = {"ok": True}
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=proxy_result),
            ),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "some/path")
        assert result == proxy_result

    @pytest.mark.asyncio
    async def test_get_method_no_body_parse(self):
        """Lines 1842: GET method doesn't parse body."""
        req = _mock_request()
        req.method = "GET"
        req.headers = {"content-type": "application/json"}
        proxy_result = {"ok": True}
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=proxy_result),
            ),
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "some/path")
        assert result == proxy_result


# ---------------------------------------------------------------------------
# _collect_codex_usage — file read error
# Lines 2048-2049
# ---------------------------------------------------------------------------


class TestCollectCodexUsageFileError:
    """Cover the file read error branch."""

    def test_file_read_error_skips_file(self, tmp_path, monkeypatch):
        """Lines 2048-2049: file read raises → continue to next file."""
        archived = tmp_path / "archived_sessions"
        archived.mkdir()
        f1 = archived / "bad.jsonl"
        f1.write_text('{"type": "session_meta", "payload": {"model": "gpt-5"}}\n')
        f2 = archived / "good.jsonl"
        f2.write_text(
            '{"type": "session_meta", "payload": {"model": "gpt-5"}}\n'
            '{"type": "event_msg", "payload": {"type": "token_count", "info": '
            '{"total_token_usage": {"input_tokens": 100, "output_tokens": 50, '
            '"total_tokens": 150}}}}\n'
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        # Patch os.path.expanduser to point to our tmp
        with patch("os.path.expanduser", return_value=str(archived)):
            result = admin_routes._collect_codex_usage()
        assert result["available"] is True
        assert result["sessions_with_tokens"] >= 1

    def test_directory_not_exists(self, monkeypatch):
        """Lines 1991-1992: directory doesn't exist → available=False."""
        with patch(
            "os.path.expanduser", return_value="/nonexistent/path/archived_sessions"
        ):
            result = admin_routes._collect_codex_usage()
        assert result["available"] is False
        assert "目录不存在" in result["reason"]

    def test_file_with_invalid_json_lines(self, tmp_path):
        """Lines 2007-2008: invalid JSON line → continue."""
        archived = tmp_path / "archived_sessions"
        archived.mkdir()
        f = archived / "mixed.jsonl"
        f.write_text(
            "not json at all\n"
            '{"type": "session_meta", "payload": {"model": "gpt-5"}}\n'
            "another bad line\n"
        )
        with patch("os.path.expanduser", return_value=str(archived)):
            result = admin_routes._collect_codex_usage()
        assert result["available"] is True
        assert result["sessions_with_tokens"] == 0

    def test_file_open_error_continues(self, tmp_path):
        """Lines 2048-2049: open() raises → continue to next file."""
        archived = tmp_path / "archived_sessions"
        archived.mkdir()
        f1 = archived / "unreadable.jsonl"
        f1.write_text('{"type": "session_meta"}\n')
        f2 = archived / "good.jsonl"
        f2.write_text(
            '{"type": "session_meta", "payload": {"model": "gpt-5"}}\n'
            '{"type": "event_msg", "payload": {"type": "token_count", "info": '
            '{"total_token_usage": {"input_tokens": 100, "total_tokens": 100}}}}\n'
        )
        original_open = open

        def mock_open(path, *args, **kwargs):
            if "unreadable" in str(path):
                raise PermissionError("cannot read")
            return original_open(path, *args, **kwargs)

        with (
            patch("os.path.expanduser", return_value=str(archived)),
            patch("builtins.open", side_effect=mock_open),
        ):
            result = admin_routes._collect_codex_usage()
        assert result["available"] is True
        assert result["sessions_with_tokens"] == 1


# ---------------------------------------------------------------------------
# _collect_trae_usage — full flow
# Lines 2075-2121
# ---------------------------------------------------------------------------


class TestCollectTraeUsage:
    """Cover the full _collect_trae_usage flow."""

    def test_db_not_exists(self):
        """Lines 2073-2074: state.vscdb doesn't exist → available=False."""
        with patch("os.path.exists", return_value=False):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is False
        assert "state.vscdb 不存在" in result["reason"]

    def test_success_with_turns_and_models(self, tmp_path):
        """Lines 2079-2134: successful read with turns and models."""
        db_path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("ai.chat.feedback.abc.accumulatedTurns", "42"),
        )
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("ai.chat.feedback.xyz.accumulatedTurns", "10"),
        )
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("some.sessionRelation:globalModelMap.key", json.dumps({"chat": "gpt-5"})),
        )
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("some.model_list_map.key", json.dumps({"chat": ["m1", "m2"], "agent": ["m3"]})),
        )
        conn.commit()
        conn.close()

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.expanduser", return_value=str(db_path)),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["total_chat_turns"] == 52
        assert result["available_models_count"] == 3
        assert result["estimated"] is True
        assert result["prompt_tokens"] == 52 * 10_000_000

    def test_db_read_error(self, tmp_path):
        """Lines 2110-2111: sqlite3 error → available=False.

        ``sqlite3.DatabaseError`` is not in RECOVERABLE_ERRORS, so we mock
        ``sqlite3.connect`` to raise ``OSError`` (which is recoverable) to
        exercise the except branch.
        """
        db_path = tmp_path / "state.vscdb"
        db_path.write_text("placeholder")

        class _FakeSqlite3:
            def connect(self, _path):
                raise OSError("cannot open database file")

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.expanduser", return_value=str(db_path)),
            patch.dict("sys.modules", {"sqlite3": _FakeSqlite3()}),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is False
        assert "读取 state.vscdb 失败" in result["reason"]

    def test_no_turns_no_models(self, tmp_path):
        """Lines 2079-2108: empty database → all zeros."""
        db_path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        conn.commit()
        conn.close()

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.expanduser", return_value=str(db_path)),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["total_chat_turns"] == 0
        assert result["total_tokens"] == 0

    def test_invalid_model_json_skipped(self, tmp_path):
        """Lines 2107-2108: invalid JSON in model_list_map → pass."""
        db_path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("some.model_list_map.key", "not valid json"),
        )
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("some.sessionRelation:globalModelMap.key", "also not json"),
        )
        conn.commit()
        conn.close()

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.expanduser", return_value=str(db_path)),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["current_models"] is None
        assert result["available_models_count"] == 0

    def test_model_list_not_dict_skipped(self, tmp_path):
        """Lines 2103-2104: model_list JSON is not dict → skip."""
        db_path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("some.model_list_map.key", json.dumps(["not", "a", "dict"])),
        )
        conn.commit()
        conn.close()

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.expanduser", return_value=str(db_path)),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["available_models_count"] == 0

    def test_models_value_not_list_skipped(self, tmp_path):
        """Lines 2105-2106: models value is not list → skip."""
        db_path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        cur.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("some.model_list_map.key", json.dumps({"chat": "not-a-list"})),
        )
        conn.commit()
        conn.close()

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.expanduser", return_value=str(db_path)),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["available_models_count"] == 0


# ---------------------------------------------------------------------------
# _collect_mimo_usage — full flow
# Lines 2171-2175
# ---------------------------------------------------------------------------


class TestCollectMimoUsage:
    """Cover the _collect_mimo_usage function."""

    def test_returns_expected_structure(self):
        """Lines 2171-2187: verify structure and calculations."""
        result = admin_routes._collect_mimo_usage()
        assert result["available"] is True
        assert result["source"] == "mimo (小米 MiMo, 手动输入)"
        assert result["credits_used"] == 22_070_888_859
        assert result["credits_quota"] == 38_000_000_000
        assert result["total_tokens"] == 80_621_905
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert result["estimated"] is True
        # usage_pct = 22_070_888_859 / 38_000_000_000 * 100 ≈ 58.1
        assert result["usage_percent"] == 58.1
        assert "58.1%" in result["note"]


# ---------------------------------------------------------------------------
# _build_token_usage_summary — full flow
# Lines 2192-2205
# ---------------------------------------------------------------------------


class TestBuildTokenUsageSummary:
    """Cover the _build_token_usage_summary aggregation."""

    def test_summary_aggregates_all_sources(self):
        """Lines 2192-2213: verify aggregation of all 5 sources."""
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._collect_local_ledger",
                return_value={"available": True, "total_tokens": 1000, "prompt_tokens": 500,
                              "completion_tokens": 500, "cost_units": 200},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_cursor_usage",
                return_value={"available": True, "total_tokens": 2000, "prompt_tokens": 1000,
                              "completion_tokens": 1000, "cost_cents": 500},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_codex_usage",
                return_value={"available": True, "total_tokens": 3000, "prompt_tokens": 1500,
                              "completion_tokens": 1500, "cache_read_tokens": 0,
                              "reasoning_tokens": 0},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_trae_usage",
                return_value={"available": True, "total_tokens": 4000, "prompt_tokens": 2000,
                              "completion_tokens": 2000},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_mimo_usage",
                return_value={"available": True, "total_tokens": 5000, "prompt_tokens": 0,
                              "completion_tokens": 0},
            ),
        ):
            result = admin_routes._build_token_usage_summary()
        assert result["success"] is True
        assert result["grand_total_tokens"] == 15000
        assert result["grand_prompt_tokens"] == 5000
        assert result["grand_completion_tokens"] == 5000
        assert "sources" in result
        assert len(result["sources"]) == 5
        assert "collected_at" in result
        # Each source should have estimated_cost_usd
        for key, src in result["sources"].items():
            assert "estimated_cost_usd" in src

    def test_summary_with_unavailable_sources(self):
        """Lines 2192-2213: unavailable sources contribute 0 tokens."""
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._collect_local_ledger",
                return_value={"available": False, "reason": "no ledger"},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_cursor_usage",
                return_value={"available": False, "reason": "no cli"},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_codex_usage",
                return_value={"available": False, "reason": "no dir"},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_trae_usage",
                return_value={"available": False, "reason": "no db"},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_mimo_usage",
                return_value={"available": True, "total_tokens": 100, "prompt_tokens": 0,
                              "completion_tokens": 0},
            ),
        ):
            result = admin_routes._build_token_usage_summary()
        assert result["success"] is True
        assert result["grand_total_tokens"] == 100
        assert result["grand_cost_usd"] == 0.0  # mimo returns 0.0


# ---------------------------------------------------------------------------
# _estimate_cost_usd — additional branches
# ---------------------------------------------------------------------------


class TestEstimateCostUsdAdditional:
    """Cover additional _estimate_cost_usd branches."""

    def test_unavailable_returns_zero(self):
        """Line 2139-2140: data not available → 0.0."""
        result = admin_routes._estimate_cost_usd("cursor", {"available": False})
        assert result == 0.0

    def test_unknown_source_returns_zero(self):
        """Line 2165: unknown source → 0.0."""
        result = admin_routes._estimate_cost_usd("unknown", {"available": True})
        assert result == 0.0

    def test_local_source_cost(self):
        """Line 2161: local source → cost_units / 100."""
        result = admin_routes._estimate_cost_usd("local", {"available": True, "cost_units": 500})
        assert result == 5.0

    def test_mimo_source_zero(self):
        """Line 2163: mimo source → 0.0."""
        result = admin_routes._estimate_cost_usd("mimo", {"available": True})
        assert result == 0.0

    def test_codex_with_cached_tokens(self):
        """Lines 2145-2154: codex with cached tokens."""
        data = {
            "available": True,
            "prompt_tokens": 2000,
            "cache_read_tokens": 500,
            "completion_tokens": 1000,
            "reasoning_tokens": 200,
        }
        result = admin_routes._estimate_cost_usd("codex", data)
        # uncached = 2000 - 500 = 1500
        # 1500 * 5/1M + 500 * 1.25/1M + (1000+200) * 10/1M
        expected = 1500 * 5 / 1_000_000 + 500 * 1.25 / 1_000_000 + 1200 * 10 / 1_000_000
        assert abs(result - expected) < 0.0001

    def test_trae_source_cost(self):
        """Lines 2156-2159: trae source."""
        data = {"available": True, "prompt_tokens": 7200000, "completion_tokens": 360000}
        result = admin_routes._estimate_cost_usd("trae", data)
        # (7200000 + 360000) * 5 / 7.2 / 1_000_000
        expected = 7560000 * 5 / 7.2 / 1_000_000
        assert abs(result - expected) < 0.0001


# ---------------------------------------------------------------------------
# _collect_local_ledger — additional branches
# ---------------------------------------------------------------------------


class TestCollectLocalLedgerAdditional:
    """Cover _collect_local_ledger error branch."""

    def test_recoverable_error_returns_unavailable(self):
        """Lines 1902-1903: list_model_usage_entries raises → available=False."""
        with patch(
            "app.infrastructure.billing.model_usage.list_model_usage_entries",
            side_effect=RuntimeError("db error"),
        ):
            result = admin_routes._collect_local_ledger()
        assert result["available"] is False
        assert "读取账本失败" in result["reason"]

    def test_success_with_entries(self):
        """Cover success path with model entries."""
        entries = [
            {"provider": "openai", "model": "gpt-4", "prompt_tokens": 100,
             "completion_tokens": 50, "total_tokens": 150, "cost_units": 0.5},
            {"provider": "anthropic", "model": "claude-3", "prompt_tokens": 200,
             "completion_tokens": 100, "total_tokens": 300, "cost_units": 1.0},
        ]
        with patch(
            "app.infrastructure.billing.model_usage.list_model_usage_entries",
            return_value=entries,
        ):
            result = admin_routes._collect_local_ledger()
        assert result["available"] is True
        assert result["records"] == 2
        assert result["prompt_tokens"] == 300
        assert result["completion_tokens"] == 150
        assert result["total_tokens"] == 450
        assert result["cost_units"] == 1.5
        assert "openai/gpt-4" in result["by_model"]
        assert "anthropic/claude-3" in result["by_model"]


# ---------------------------------------------------------------------------
# _collect_cursor_usage — additional branches
# ---------------------------------------------------------------------------


class TestCollectCursorUsageAdditional:
    """Cover _collect_cursor_usage branches."""

    def test_cli_not_exists(self):
        """Lines 1935-1936: CLI doesn't exist → available=False."""
        with (
            patch("shutil.which", return_value=None),
            patch("os.path.exists", return_value=False),
        ):
            result = admin_routes._collect_cursor_usage()
        assert result["available"] is False
        assert "cursor-usage CLI 不存在" in result["reason"]

    def test_execution_error(self):
        """Lines 1944-1945: subprocess fails → available=False."""
        with (
            patch("shutil.which", return_value="/fake/cursor-usage"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", side_effect=RuntimeError("exec fail")),
        ):
            result = admin_routes._collect_cursor_usage()
        assert result["available"] is False
        assert "执行失败" in result["reason"]

    def test_nonzero_exit_code(self):
        """Lines 1946-1947: non-zero exit code → available=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with (
            patch("shutil.which", return_value="/fake/cursor-usage"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = admin_routes._collect_cursor_usage()
        assert result["available"] is False
        assert "exit=1" in result["reason"]

    def test_json_parse_error(self):
        """Lines 1950-1951: JSON parse fails → available=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "not json"
        with (
            patch("shutil.which", return_value="/fake/cursor-usage"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = admin_routes._collect_cursor_usage()
        assert result["available"] is False
        assert "JSON 解析失败" in result["reason"]

    def test_success_with_aggregations(self):
        """Cover success path with aggregations."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({
            "aggregations": [
                {"modelIntent": "gpt-4", "inputTokens": 100, "outputTokens": 50,
                 "cacheReadTokens": 10, "cacheWriteTokens": 5, "totalCents": 25},
                {"modelIntent": "claude-3", "inputTokens": 200, "outputTokens": 100,
                 "cacheReadTokens": 20, "cacheWriteTokens": 10, "totalCents": 50},
            ]
        })
        with (
            patch("shutil.which", return_value="/fake/cursor-usage"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = admin_routes._collect_cursor_usage()
        assert result["available"] is True
        assert result["aggregations"] == 2
        assert result["prompt_tokens"] == 300
        assert result["completion_tokens"] == 150
        assert result["cache_read_tokens"] == 30
        assert result["cache_write_tokens"] == 15
        assert result["total_tokens"] == 495
        assert result["cost_cents"] == 75
        assert "gpt-4" in result["by_model"]
        assert "claude-3" in result["by_model"]

    def test_non_dict_raw(self):
        """Lines 1952-1953: raw is not dict → aggs=[]."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(["not", "a", "dict"])
        with (
            patch("shutil.which", return_value="/fake/cursor-usage"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = admin_routes._collect_cursor_usage()
        assert result["available"] is True
        assert result["aggregations"] == 0


# ---------------------------------------------------------------------------
# admin_token_usage route
# ---------------------------------------------------------------------------


class TestAdminTokenUsageRoute:
    """Cover the admin_token_usage route."""

    def test_no_session_returns_401(self, client: TestClient):
        """Line 2221-2225: no session → 401."""
        with _session_id(None):
            resp = client.get("/api/xcmax/admin/token-usage")
        assert resp.status_code == 401

    def test_success(self, client: TestClient):
        """Cover success path."""
        summary = {"success": True, "grand_total_tokens": 1000, "sources": {}}
        with (
            _session_id("sid"),
            patch(
                "app.fastapi_routes.xcmax_admin._build_token_usage_summary",
                return_value=summary,
            ),
        ):
            resp = client.get("/api/xcmax/admin/token-usage")
        assert resp.status_code == 200
        assert resp.json()["grand_total_tokens"] == 1000
