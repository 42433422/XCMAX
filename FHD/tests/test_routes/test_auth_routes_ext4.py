"""Tests for app.fastapi_routes.domains.auth.routes — additional coverage (ext4).

Focus: _sync_local_password_for_email, _enrich_register_with_tenant,
auth_session_validate enterprise branch, auth_me disabled user branch,
auth_forgot_account, auth_forgot_password_send_code, auth_forgot_password_reset,
auth_register enterprise/local branches, auth_login error paths,
auth_oidc_callback error branches, auth_qr_status confirmed/expired branches,
users_* admin routes, auth_profile_patch, auth_password_change, auth_logout,
auth_update_company_brand.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse, RedirectResponse

# ---------------------------------------------------------------------------
# _sync_local_password_for_email
# ---------------------------------------------------------------------------


class TestSyncLocalPasswordForEmail:
    @patch("app.fastapi_routes.domains.auth.routes._find_local_users_by_email")
    @patch("app.application.auth_app_service.get_auth_app_service")
    def test_updates_matching_users(self, mock_get_service, mock_find_users):
        from app.fastapi_routes.domains.auth.routes import _sync_local_password_for_email

        mock_user1 = MagicMock()
        mock_user1.id = 1
        mock_user2 = MagicMock()
        mock_user2.id = 2
        mock_find_users.return_value = [mock_user1, mock_user2]

        mock_service = MagicMock()
        mock_service.reset_password.return_value = {"success": True}
        mock_get_service.return_value = mock_service

        result = _sync_local_password_for_email("test@example.com", "newpass123")
        assert result == 2

    @patch("app.fastapi_routes.domains.auth.routes._find_local_users_by_email")
    @patch("app.application.auth_app_service.get_auth_app_service")
    def test_skips_failed_resets(self, mock_get_service, mock_find_users):
        from app.fastapi_routes.domains.auth.routes import _sync_local_password_for_email

        mock_user = MagicMock()
        mock_user.id = 1
        mock_find_users.return_value = [mock_user]

        mock_service = MagicMock()
        mock_service.reset_password.return_value = {"success": False}
        mock_get_service.return_value = mock_service

        result = _sync_local_password_for_email("test@example.com", "newpass123")
        assert result == 0

    @patch("app.fastapi_routes.domains.auth.routes._find_local_users_by_email")
    @patch("app.application.auth_app_service.get_auth_app_service")
    def test_no_users_found(self, mock_get_service, mock_find_users):
        from app.fastapi_routes.domains.auth.routes import _sync_local_password_for_email

        mock_find_users.return_value = []
        result = _sync_local_password_for_email("test@example.com", "newpass123")
        assert result == 0


# ---------------------------------------------------------------------------
# _enrich_register_with_tenant
# ---------------------------------------------------------------------------


class TestEnrichRegisterWithTenant:
    def test_returns_result_when_no_user_id(self):
        from app.fastapi_routes.domains.auth.routes import _enrich_register_with_tenant

        result = {"success": True, "user": {}}
        out = _enrich_register_with_tenant(
            result=result, username="user", session_id="sid", sku="generic"
        )
        assert out is result

    @patch("app.application.enterprise_login_flow.bind_tenant_for_login")
    def test_enriches_with_tenant_id(self, mock_bind):
        from app.fastapi_routes.domains.auth.routes import _enrich_register_with_tenant

        mock_bind.return_value = {"tenant_id": 100, "tenant_name": "Acme"}
        result = {"success": True, "user": {"id": 5}}

        with patch(
            "app.application.session_account_meta.persist_session_account_meta"
        ) as mock_persist:
            out = _enrich_register_with_tenant(
                result=result,
                username="user",
                session_id="sid",
                sku="enterprise",
                company_brand="Acme",
            )
        assert out["tenant_id"] == 100
        assert out["tenant_name"] == "Acme"
        assert out["account_kind"] == "enterprise"
        mock_persist.assert_called_once()

    @patch("app.application.enterprise_login_flow.bind_tenant_for_login")
    def test_skips_persist_when_no_session_id(self, mock_bind):
        from app.fastapi_routes.domains.auth.routes import _enrich_register_with_tenant

        mock_bind.return_value = {"tenant_id": 100, "tenant_name": "Acme"}
        result = {"success": True, "user": {"id": 5}}

        with patch(
            "app.application.session_account_meta.persist_session_account_meta"
        ) as mock_persist:
            out = _enrich_register_with_tenant(
                result=result,
                username="user",
                session_id=None,
                sku="generic",
                company_brand="Acme",
            )
        assert out["tenant_id"] == 100
        mock_persist.assert_not_called()

    @patch(
        "app.application.enterprise_login_flow.bind_tenant_for_login",
        side_effect=RuntimeError("tenant fail"),
    )
    def test_handles_infra_transient(self, mock_bind):
        from app.fastapi_routes.domains.auth.routes import _enrich_register_with_tenant
        from app.utils.operational_errors import INFRA_TRANSIENT

        # Patch INFRA_TRANSIENT to include RuntimeError for this test
        with patch(
            "app.fastapi_routes.domains.auth.routes.INFRA_TRANSIENT",
            (RuntimeError,),
        ):
            result = {"success": True, "user": {"id": 5}}
            out = _enrich_register_with_tenant(
                result=result,
                username="user",
                session_id="sid",
                sku="generic",
            )
        # Should not raise, returns result unchanged
        assert out is result

    @patch("app.application.enterprise_login_flow.bind_tenant_for_login")
    def test_personal_sku_account_kind(self, mock_bind):
        from app.fastapi_routes.domains.auth.routes import _enrich_register_with_tenant

        mock_bind.return_value = {"tenant_id": None, "tenant_name": ""}
        result = {"success": True, "user": {"id": 5}}

        with patch(
            "app.application.session_account_meta.persist_session_account_meta"
        ) as mock_persist:
            out = _enrich_register_with_tenant(
                result=result,
                username="user",
                session_id="sid",
                sku="generic",
                company_brand="",
            )
        assert out["account_kind"] == "personal"


# ---------------------------------------------------------------------------
# auth_me
# ---------------------------------------------------------------------------


class TestAuthMe:
    def test_no_session_user(self):
        from app.fastapi_routes.domains.auth.routes import auth_me

        request = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=None,
        ):
            result = auth_me(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    def test_disabled_user(self):
        from app.fastapi_routes.domains.auth.routes import auth_me

        request = MagicMock()
        mock_user = MagicMock()
        mock_user.is_active = False
        with patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=mock_user,
        ):
            result = auth_me(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    def test_active_user(self):
        from app.fastapi_routes.domains.auth.routes import auth_me

        request = MagicMock()
        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.id = 1
        mock_user.username = "u"
        mock_user.display_name = "U"
        mock_user.email = "e@x.com"
        mock_user.role = "user"

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=mock_user,
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._session_meta_for_response",
                return_value={},
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.get_user_permissions.return_value = ["read"]
            mock_get.return_value = mock_service
            result = auth_me(request)
        assert isinstance(result, dict)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# auth_session_validate
# ---------------------------------------------------------------------------


class TestAuthSessionValidate:
    @pytest.mark.asyncio
    async def test_no_session_id(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.session_id_from_request",
            return_value=None,
        ):
            result = await auth_session_validate(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_session(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.session_manager.get_session_info.return_value = None
            mock_get.return_value = mock_service
            result = await auth_session_validate(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_enterprise_no_market_token(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_for_session",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._session_meta_for_response",
                return_value={},
            ),
        ):
            mock_service = MagicMock()
            mock_service.session_manager.get_session_info.return_value = {"user_id": 1}
            mock_get.return_value = mock_service
            result = await auth_session_validate(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_enterprise_with_market_token(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value="Bearer xyz"),
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_for_session",
                new=AsyncMock(return_value=["mod1", "mod2"]),
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._session_meta_for_response",
                return_value={"account_kind": "enterprise"},
            ),
        ):
            mock_service = MagicMock()
            mock_service.session_manager.get_session_info.return_value = {"user_id": 1}
            mock_get.return_value = mock_service
            result = await auth_session_validate(request)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["entitled_mod_ids"] == ["mod1", "mod2"]

    @pytest.mark.asyncio
    async def test_enterprise_cached_entitlements(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value="Bearer xyz"),
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_for_session",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=["cached_mod"],
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._session_meta_for_response",
                return_value={},
            ),
        ):
            mock_service = MagicMock()
            mock_service.session_manager.get_session_info.return_value = {"user_id": 1}
            mock_get.return_value = mock_service
            result = await auth_session_validate(request)
        assert isinstance(result, dict)
        assert result["entitled_mod_ids"] == ["cached_mod"]


# ---------------------------------------------------------------------------
# auth_forgot_account
# ---------------------------------------------------------------------------


class TestAuthForgotAccount:
    def test_invalid_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        result = auth_forgot_account({"email": "not-an-email"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_empty_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        result = auth_forgot_account({"email": ""})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_users_found(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        mock_user = MagicMock()
        mock_user.username = "alice"
        with patch(
            "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
            return_value=[mock_user],
        ):
            result = auth_forgot_account({"email": "alice@example.com"})
        assert result["success"] is True
        assert result["data"]["found"] is True

    def test_no_users_found(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        with patch(
            "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
            return_value=[],
        ):
            result = auth_forgot_account({"email": "nobody@example.com"})
        assert result["success"] is True
        assert result["data"]["found"] is False


# ---------------------------------------------------------------------------
# auth_forgot_password_send_code
# ---------------------------------------------------------------------------


class TestAuthForgotPasswordSendCode:
    @pytest.mark.asyncio
    async def test_invalid_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        result = await auth_forgot_password_send_code({"email": "bad"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_send_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.market_account.send_market_reset_password_code",
                new=AsyncMock(return_value={"success": True, "message": "ok"}),
            ),
        ):
            result = await auth_forgot_password_send_code({"email": "a@b.com"})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_failure_no_local_users(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.market_account.send_market_reset_password_code",
                new=AsyncMock(return_value={"success": False, "message": "fail"}),
            ),
        ):
            result = await auth_forgot_password_send_code({"email": "a@b.com"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_send_failure_with_local_users(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        mock_user = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[mock_user],
            ),
            patch(
                "app.fastapi_routes.market_account.send_market_reset_password_code",
                new=AsyncMock(return_value={"success": False, "message": "fail"}),
            ),
        ):
            result = await auth_forgot_password_send_code({"email": "a@b.com"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502


# ---------------------------------------------------------------------------
# auth_forgot_password_reset
# ---------------------------------------------------------------------------


class TestAuthForgotPasswordReset:
    @pytest.mark.asyncio
    async def test_invalid_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        result = await auth_forgot_password_reset({"email": "bad"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_weak_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        result = await auth_forgot_password_reset({"email": "a@b.com", "new_password": "123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_market_reset_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        with patch(
            "app.fastapi_routes.market_account.reset_market_password_with_code",
            new=AsyncMock(return_value={"success": False, "message": "bad code"}),
        ):
            result = await auth_forgot_password_reset(
                {"email": "a@b.com", "code": "123456", "new_password": "newpass123"}
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        with (
            patch(
                "app.fastapi_routes.market_account.reset_market_password_with_code",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._sync_local_password_for_email",
                return_value=2,
            ),
        ):
            result = await auth_forgot_password_reset(
                {"email": "a@b.com", "code": "123456", "new_password": "newpass123"}
            )
        assert result["success"] is True
        assert result["data"]["local_users_updated"] == 2


# ---------------------------------------------------------------------------
# auth_register
# ---------------------------------------------------------------------------


class TestAuthRegister:
    @pytest.mark.asyncio
    async def test_missing_username_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        result = await auth_register(request, {"username": "", "password": ""})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_weak_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        result = await auth_register(request, {"username": "u", "password": "123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_enterprise_missing_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"):
            result = await auth_register(request, {"username": "u", "password": "pass123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_enterprise_market_register_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.register_market_user",
                new=AsyncMock(return_value={"success": False, "message": "exists"}),
            ),
        ):
            result = await auth_register(
                request,
                {"username": "u", "password": "pass123", "email": "a@b.com"},
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_enterprise_local_login_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.register_market_user",
                new=AsyncMock(
                    return_value={
                        "success": True,
                        "raw": {"user": {"email": "a@b.com"}},
                        "token": "tok",
                        "refresh_token": "rtok",
                        "market_user_id": 61,
                    }
                ),
            ),
            patch(
                "app.fastapi_routes.market_account.ensure_market_enterprise_profile",
                new=AsyncMock(return_value={"success": True}),
            ) as mock_profile,
            patch(
                "app.fastapi_routes.market_account.enterprise_mod_ids_for_industry",
                return_value=["coating-industry"],
            ) as mock_mod_ids,
            patch(
                "app.fastapi_routes.domains.auth.routes._jit_create_local_user_for_enterprise",
                return_value=True,
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.login.return_value = {"success": False, "message": "no user"}
            mock_get.return_value = mock_service
            result = await auth_register(
                request,
                {
                    "username": "u",
                    "password": "pass123",
                    "email": "a@b.com",
                    "industry_id": "涂料",
                },
            )
        assert isinstance(result, JSONResponse)
        mock_mod_ids.assert_called_once_with("涂料")
        mock_profile.assert_awaited_once()
        assert mock_profile.await_args.kwargs["mod_ids"] == ["coating-industry"]
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_enterprise_market_enterprise_profile_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.register_market_user",
                new=AsyncMock(
                    return_value={
                        "success": True,
                        "raw": {"user": {"id": 61, "email": "a@b.com"}},
                        "token": "tok",
                        "refresh_token": "rtok",
                        "market_user_id": 61,
                    }
                ),
            ),
            patch(
                "app.fastapi_routes.market_account.ensure_market_enterprise_profile",
                new=AsyncMock(return_value={"success": False, "message": "mark failed"}),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._jit_create_local_user_for_enterprise",
                return_value=True,
            ) as mock_jit,
        ):
            result = await auth_register(
                request,
                {"username": "u", "password": "pass123", "email": "a@b.com"},
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502
        mock_jit.assert_not_called()

    @pytest.mark.asyncio
    async def test_enterprise_full_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.fastapi_routes.market_account.register_market_user",
                new=AsyncMock(
                    return_value={
                        "success": True,
                        "raw": {"user": {"email": "a@b.com"}},
                        "token": "tok",
                        "refresh_token": "rtok",
                        "market_user_id": 61,
                    }
                ),
            ),
            patch(
                "app.fastapi_routes.market_account.ensure_market_enterprise_profile",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._jit_create_local_user_for_enterprise",
                return_value=True,
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.fastapi_routes.domains.auth.routes._enrich_register_with_tenant",
                side_effect=lambda **kw: kw["result"],
            ),
        ):
            mock_service = MagicMock()
            mock_service.login.return_value = {
                "success": True,
                "session_id": "sid",
            }
            mock_get.return_value = mock_service
            result = await auth_register(
                request,
                {"username": "u", "password": "pass123", "email": "a@b.com"},
            )
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_local_registration_disabled(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.fastapi_routes.domains.auth.routes._open_registration_allowed",
                return_value=False,
            ),
        ):
            result = await auth_register(request, {"username": "u", "password": "pass123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_local_create_user_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.fastapi_routes.domains.auth.routes._open_registration_allowed",
                return_value=True,
            ),
            patch("app.application.get_user_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.create_user.return_value = {
                "success": False,
                "message": "用户名已存在",
            }
            mock_get.return_value = mock_service
            result = await auth_register(request, {"username": "u", "password": "pass123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_local_login_after_register_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.fastapi_routes.domains.auth.routes._open_registration_allowed",
                return_value=True,
            ),
            patch("app.application.get_user_app_service") as mock_get_user,
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get_auth,
        ):
            mock_user_service = MagicMock()
            mock_user_service.create_user.return_value = {
                "success": True,
                "user": {"id": 1},
            }
            mock_get_user.return_value = mock_user_service
            mock_auth_service = MagicMock()
            mock_auth_service.login.return_value = {"success": False, "message": "fail"}
            mock_get_auth.return_value = mock_auth_service
            result = await auth_register(request, {"username": "u", "password": "pass123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_local_full_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_register

        request = MagicMock()
        with (
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.fastapi_routes.domains.auth.routes._open_registration_allowed",
                return_value=True,
            ),
            patch("app.application.get_user_app_service") as mock_get_user,
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get_auth,
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new=AsyncMock(return_value={"success": True, "token": "t", "refresh_token": "r"}),
            ),
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.fastapi_routes.domains.auth.routes._enrich_register_with_tenant",
                side_effect=lambda **kw: kw["result"],
            ),
        ):
            mock_user_service = MagicMock()
            mock_user_service.create_user.return_value = {
                "success": True,
                "user": {"id": 1},
            }
            mock_get_user.return_value = mock_user_service
            mock_auth_service = MagicMock()
            mock_auth_service.login.return_value = {
                "success": True,
                "session_id": "sid",
            }
            mock_get_auth.return_value = mock_auth_service
            result = await auth_register(request, {"username": "u", "password": "pass123"})
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_login
# ---------------------------------------------------------------------------


class TestAuthLogin:
    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        with patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric:
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(request, {"username": "", "password": ""})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_login_with_error(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        err_resp = JSONResponse({"success": False}, status_code=401)
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, err_resp)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(request, {"username": "u", "password": "p"})
        assert result is err_resp

    @pytest.mark.asyncio
    async def test_login_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid"}, None)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(request, {"username": "u", "password": "p"})
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_login_with_phone_code
# ---------------------------------------------------------------------------


class TestAuthLoginWithPhoneCode:
    @pytest.mark.asyncio
    async def test_missing_phone_or_code(self):
        from app.fastapi_routes.domains.auth.routes import auth_login_with_phone_code

        request = MagicMock()
        with patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric:
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login_with_phone_code(request, {"phone": "", "code": ""})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_login_with_error(self):
        from app.fastapi_routes.domains.auth.routes import auth_login_with_phone_code

        request = MagicMock()
        err_resp = JSONResponse({"success": False}, status_code=401)
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.fastapi_routes.market_account.login_market_with_phone_code",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, err_resp)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login_with_phone_code(
                request, {"phone": "13800000000", "code": "1234"}
            )
        assert result is err_resp

    @pytest.mark.asyncio
    async def test_login_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_login_with_phone_code

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.fastapi_routes.market_account.login_market_with_phone_code",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid"}, None)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login_with_phone_code(
                request, {"phone": "13800000000", "code": "1234"}
            )
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_oidc_status / auth_oidc_start / auth_oidc_callback
# ---------------------------------------------------------------------------


class TestAuthOidcStatus:
    def test_returns_status(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_status

        with patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True):
            result = auth_oidc_status()
        assert result["success"] is True
        assert result["data"]["enabled"] is True


class TestAuthOidcStart:
    @pytest.mark.asyncio
    async def test_oidc_disabled(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_start

        request = MagicMock()
        with patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=False):
            result = await auth_oidc_start(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_oidc_enabled(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_start

        request = MagicMock()
        request.query_params = {"return": "/dashboard"}
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True),
            patch("app.infrastructure.auth.oidc_provider.sign_oidc_state", return_value="state123"),
            patch(
                "app.infrastructure.auth.oidc_provider.build_authorize_url",
                new=AsyncMock(return_value="https://idp/authorize"),
            ),
        ):
            result = await auth_oidc_start(request)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 302


class TestAuthOidcCallback:
    @pytest.mark.asyncio
    async def test_oidc_disabled(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=False),
            patch(
                "app.infrastructure.auth.oidc_provider.frontend_redirect_path",
                return_value="/",
            ),
        ):
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)
        assert "OIDC_DISABLED" in result.headers["location"]

    @pytest.mark.asyncio
    async def test_invalid_state(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        request.query_params = {"code": "abc", "state": "bad"}
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True),
            patch(
                "app.infrastructure.auth.oidc_provider.frontend_redirect_path",
                return_value="/",
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(False, None),
            ),
        ):
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)
        assert "OIDC_STATE" in result.headers["location"]

    @pytest.mark.asyncio
    async def test_missing_code(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        request.query_params = {"code": "", "state": "ok"}
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True),
            patch(
                "app.infrastructure.auth.oidc_provider.frontend_redirect_path",
                return_value="/",
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, None),
            ),
        ):
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)
        assert "OIDC_STATE" in result.headers["location"]

    @pytest.mark.asyncio
    async def test_exchange_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        request.query_params = {"code": "abc", "state": "ok"}
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True),
            patch(
                "app.infrastructure.auth.oidc_provider.frontend_redirect_path",
                return_value="/",
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, None),
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.exchange_oidc_authorization",
                new=AsyncMock(side_effect=RuntimeError("exchange failed")),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes.INFRA_TRANSIENT",
                (RuntimeError,),
            ),
        ):
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)
        assert "OIDC_EXCHANGE" in result.headers["location"]

    @pytest.mark.asyncio
    async def test_auth_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        request.query_params = {"code": "abc", "state": "ok"}
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True),
            patch(
                "app.infrastructure.auth.oidc_provider.frontend_redirect_path",
                return_value="/",
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, None),
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
                "message": "no user",
            }
            mock_get.return_value = mock_service
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)
        assert "OIDC_AUTH" in result.headers["location"]

    @pytest.mark.asyncio
    async def test_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        request.query_params = {"code": "abc", "state": "ok"}
        with (
            patch("app.infrastructure.auth.oidc_provider.oidc_enabled", return_value=True),
            patch(
                "app.infrastructure.auth.oidc_provider.frontend_redirect_path",
                return_value="/",
            ),
            patch(
                "app.infrastructure.auth.oidc_provider.verify_oidc_state",
                return_value=(True, None),
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
                new=AsyncMock(return_value={"session_id": "sid"}),
            ),
        ):
            mock_service = MagicMock()
            mock_service.authenticate_oidc_user.return_value = {
                "success": True,
                "session_id": "sid",
                "user": {"username": "u"},
            }
            mock_get.return_value = mock_service
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)
        assert "oidc=ok" in result.headers["location"]


# ---------------------------------------------------------------------------
# auth_qr_issue / auth_qr_status
# ---------------------------------------------------------------------------


class TestAuthQrIssue:
    @pytest.mark.asyncio
    async def test_issue(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_issue

        request = MagicMock()
        request.headers = {"User-Agent": "test-agent"}
        with patch(
            "app.security.auth_qr_login.issue_auth_qr",
            return_value={"qr_id": "q1", "poll_secret": "s1"},
        ):
            result = await auth_qr_issue(request, {"client_hint": "hint"})
        assert result["success"] is True
        assert result["data"]["qr_id"] == "q1"


class TestAuthQrStatus:
    @pytest.mark.asyncio
    async def test_qr_not_found(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with patch("app.security.auth_qr_login.poll_auth_qr", return_value=None):
            result = await auth_qr_status(qr_id="bad", poll_secret="x")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_qr_pending(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with patch(
            "app.security.auth_qr_login.poll_auth_qr",
            return_value={"status": "pending"},
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert result["data"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_qr_expired(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with patch(
            "app.security.auth_qr_login.poll_auth_qr",
            return_value={"status": "expired"},
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert result["data"]["status"] == "expired"

    @pytest.mark.asyncio
    async def test_qr_confirmed_with_session(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with (
            patch(
                "app.security.auth_qr_login.poll_auth_qr",
                return_value={"status": "confirmed"},
            ),
            patch(
                "app.security.auth_qr_login.consume_confirmed_qr",
                return_value={
                    "session_id": "sid",
                    "login_payload": {"user": {"id": 1}},
                },
            ),
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert isinstance(result, JSONResponse)
        assert result.body  # has content

    @pytest.mark.asyncio
    async def test_qr_confirmed_no_session(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with (
            patch(
                "app.security.auth_qr_login.poll_auth_qr",
                return_value={"status": "confirmed"},
            ),
            patch(
                "app.security.auth_qr_login.consume_confirmed_qr",
                return_value={"session_id": None},
            ),
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert result["data"]["status"] == "confirmed"


# ---------------------------------------------------------------------------
# auth_profile_get / auth_profile_patch
# ---------------------------------------------------------------------------


class TestAuthProfileGet:
    def test_returns_user(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_get

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "u"
        mock_user.display_name = "U"
        mock_user.email = "e@x.com"
        mock_user.role = "user"
        mock_user.is_active = True
        result = auth_profile_get(user=mock_user)
        assert result["success"] is True


class TestAuthProfilePatch:
    def test_no_fields(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_patch

        mock_user = MagicMock()
        mock_user.id = 1
        result = auth_profile_patch(body={}, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_update_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_patch

        mock_user = MagicMock()
        mock_user.id = 1
        with patch("app.application.user_app_service.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": False,
                "message": "fail",
            }
            mock_get.return_value = mock_service
            result = auth_profile_patch(body={"display_name": "New"}, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_user_not_found_after_update(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_patch

        mock_user = MagicMock()
        mock_user.id = 1
        with (
            patch("app.application.user_app_service.get_user_app_service") as mock_get,
            patch("app.db.session.get_db") as mock_get_db,
        ):
            mock_service = MagicMock()
            mock_service.update_user.return_value = {"success": True}
            mock_get.return_value = mock_service
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = auth_profile_patch(body={"display_name": "New"}, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    def test_update_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_patch

        mock_user = MagicMock()
        mock_user.id = 1
        with (
            patch("app.application.user_app_service.get_user_app_service") as mock_get,
            patch("app.db.session.get_db") as mock_get_db,
        ):
            mock_service = MagicMock()
            mock_service.update_user.return_value = {"success": True}
            mock_get.return_value = mock_service
            mock_row = MagicMock()
            mock_row.id = 1
            mock_row.username = "u"
            mock_row.display_name = "New"
            mock_row.email = "e@x.com"
            mock_row.role = "user"
            mock_row.is_active = True
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_row
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = auth_profile_patch(
                body={"display_name": "New", "email": "new@x.com"}, user=mock_user
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# auth_password_change
# ---------------------------------------------------------------------------


class TestAuthPasswordChange:
    def test_missing_fields(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        result = auth_password_change(body={"old_password": "", "new_password": ""}, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_weak_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        result = auth_password_change(
            body={"old_password": "old", "new_password": "123"}, user=mock_user
        )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_change_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        mock_user.id = 1
        with patch("app.application.auth_app_service.get_auth_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.change_password.return_value = {
                "success": False,
                "message": "wrong old",
            }
            mock_get.return_value = mock_service
            result = auth_password_change(
                body={"old_password": "old", "new_password": "newpass123"},
                user=mock_user,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_change_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        mock_user.id = 1
        with patch("app.application.auth_app_service.get_auth_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.change_password.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = auth_password_change(
                body={"old_password": "old", "new_password": "newpass123"},
                user=mock_user,
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# auth_logout
# ---------------------------------------------------------------------------


class TestAuthLogout:
    def test_no_session(self):
        from app.fastapi_routes.domains.auth.routes import auth_logout

        request = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.session_id_from_request",
            return_value=None,
        ):
            result = auth_logout(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_logout_success(self):
        from app.fastapi_routes.domains.auth.routes import auth_logout

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.fastapi_routes.market_account.clear_session_market_token"),
            patch("app.enterprise.mod_entitlements.clear_session_entitlements"),
        ):
            mock_service = MagicMock()
            mock_service.logout.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = auth_logout(request)
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_subscription_status
# ---------------------------------------------------------------------------


class TestAuthSubscriptionStatus:
    def test_no_user(self):
        from app.fastapi_routes.domains.auth.routes import auth_subscription_status

        request = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=None,
        ):
            result = auth_subscription_status(request)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    def test_with_user(self):
        from app.fastapi_routes.domains.auth.routes import auth_subscription_status

        request = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=mock_user,
            ),
            patch(
                "app.application.tenant_subscription_app_service.subscription_status_for_user",
                return_value={"plan": "trial"},
            ),
        ):
            result = auth_subscription_status(request)
        assert result["success"] is True
        assert result["data"]["plan"] == "trial"


# ---------------------------------------------------------------------------
# auth_update_company_brand
# ---------------------------------------------------------------------------


class TestAuthUpdateCompanyBrand:
    @pytest.mark.asyncio
    async def test_no_session(self):
        from app.fastapi_routes.domains.auth.routes import auth_update_company_brand

        request = MagicMock()
        mock_user = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.session_id_from_request",
            return_value=None,
        ):
            result = await auth_update_company_brand(
                request, {"company_brand": "Acme"}, user=mock_user
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_with_session_no_market_token(self):
        from app.fastapi_routes.domains.auth.routes import auth_update_company_brand

        request = MagicMock()
        mock_user = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise"},
            ),
            patch("app.application.session_account_meta.persist_session_account_meta"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await auth_update_company_brand(
                request, {"company_brand": "Acme"}, user=mock_user
            )
        assert result["success"] is True
        assert result["company_brand"] == "Acme"

    @pytest.mark.asyncio
    async def test_with_session_and_market_token(self):
        from app.fastapi_routes.domains.auth.routes import auth_update_company_brand

        request = MagicMock()
        mock_user = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "enterprise"},
            ),
            patch("app.application.session_account_meta.persist_session_account_meta"),
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value="Bearer xyz"),
            ),
            patch("app.fastapi_routes.market_account._proxy_json", new=AsyncMock()),
        ):
            result = await auth_update_company_brand(
                request, {"company_brand": "Acme"}, user=mock_user
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# users_list / users_get / users_create / users_update / users_delete
# ---------------------------------------------------------------------------


class TestUsersList:
    def test_list_default(self):
        from app.fastapi_routes.domains.auth.routes import users_list

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.list_users.return_value = [
                {"id": 1, "is_active": True},
                {"id": 2, "is_active": False},
            ]
            mock_get.return_value = mock_service
            result = users_list(include_inactive="false", _user=mock_admin)
        assert result["data"]["count"] == 1

    def test_list_include_inactive(self):
        from app.fastapi_routes.domains.auth.routes import users_list

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.list_users.return_value = [
                {"id": 1, "is_active": True},
                {"id": 2, "is_active": False},
            ]
            mock_get.return_value = mock_service
            result = users_list(include_inactive="true", _user=mock_admin)
        assert result["data"]["count"] == 2


class TestUsersGet:
    def test_user_not_found(self):
        from app.fastapi_routes.domains.auth.routes import users_get

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_user.return_value = None
            mock_get.return_value = mock_service
            result = users_get(user_id=999, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    def test_user_found(self):
        from app.fastapi_routes.domains.auth.routes import users_get

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_user.return_value = {"id": 1, "username": "u"}
            mock_get.return_value = mock_service
            result = users_get(user_id=1, _user=mock_admin)
        assert result["success"] is True


class TestUsersCreate:
    def test_missing_fields(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        result = users_create(body={"username": "", "password": ""}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_weak_password(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        result = users_create(body={"username": "u", "password": "123"}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_invalid_role(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        result = users_create(
            body={"username": "u", "password": "pass123", "role": "superadmin"},
            _user=mock_admin,
        )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_create_failure(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.create_user.return_value = {
                "success": False,
                "error": "exists",
            }
            mock_get.return_value = mock_service
            result = users_create(
                body={"username": "u", "password": "pass123", "role": "viewer"},
                _user=mock_admin,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_create_success(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.create_user.return_value = {
                "success": True,
                "user": {"id": 1},
            }
            mock_get.return_value = mock_service
            result = users_create(
                body={"username": "u", "password": "pass123", "role": "viewer"},
                _user=mock_admin,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 201


class TestUsersUpdate:
    def test_invalid_role(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        result = users_update(user_id=1, body={"role": "superadmin"}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_update_failure(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": False,
                "error": "no user",
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={"display_name": "New"}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_update_success(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1},
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={"display_name": "New"}, _user=mock_admin)
        assert result["success"] is True


class TestUsersDelete:
    def test_self_delete(self):
        from app.fastapi_routes.domains.auth.routes import users_delete

        mock_admin = MagicMock()
        mock_admin.id = 1
        result = users_delete(user_id=1, user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_delete_failure(self):
        from app.fastapi_routes.domains.auth.routes import users_delete

        mock_admin = MagicMock()
        mock_admin.id = 1
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.delete_user.return_value = {"success": False}
            mock_get.return_value = mock_service
            result = users_delete(user_id=2, user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_delete_success(self):
        from app.fastapi_routes.domains.auth.routes import users_delete

        mock_admin = MagicMock()
        mock_admin.id = 1
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.delete_user.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = users_delete(user_id=2, user=mock_admin)
        assert result["success"] is True


class TestUsersResetPassword:
    def test_missing_password(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        result = users_reset_password(user_id=1, body={"new_password": ""}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_weak_password(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        result = users_reset_password(user_id=1, body={"new_password": "123"}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_reset_failure(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        with patch("app.application.auth_app_service.get_auth_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.reset_password.return_value = {
                "success": False,
                "message": "fail",
            }
            mock_get.return_value = mock_service
            result = users_reset_password(
                user_id=1, body={"new_password": "newpass123"}, _user=mock_admin
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_reset_success(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        with patch("app.application.auth_app_service.get_auth_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.reset_password.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = users_reset_password(
                user_id=1, body={"new_password": "newpass123"}, _user=mock_admin
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _find_local_users_by_email
# ---------------------------------------------------------------------------


class TestFindLocalUsersByEmail:
    @patch("app.db.session.get_db")
    def test_invalid_email_no_at(self, mock_get_db):
        from app.fastapi_routes.domains.auth.routes import _find_local_users_by_email

        result = _find_local_users_by_email("not-an-email")
        assert result == []

    @patch("app.db.session.get_db")
    def test_empty_email(self, mock_get_db):
        from app.fastapi_routes.domains.auth.routes import _find_local_users_by_email

        result = _find_local_users_by_email("")
        assert result == []

    @patch("app.db.session.get_db")
    def test_valid_email(self, mock_get_db):
        from app.fastapi_routes.domains.auth.routes import _find_local_users_by_email

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_user
        ]
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        result = _find_local_users_by_email("a@b.com")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _open_registration_allowed additional branches
# ---------------------------------------------------------------------------


class TestOpenRegistrationAllowedAdditional:
    def test_env_false(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "false")
        assert _open_registration_allowed("generic") is False

    def test_env_true(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "1")
        assert _open_registration_allowed("enterprise") is True

    def test_env_no(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "no")
        assert _open_registration_allowed("generic") is False

    def test_env_yes(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "yes")
        assert _open_registration_allowed("generic") is True

    def test_env_unset_generic(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
        assert _open_registration_allowed("generic") is True

    def test_env_unset_enterprise(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
        assert _open_registration_allowed("enterprise") is False
