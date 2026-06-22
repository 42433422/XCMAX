"""Tests for app.fastapi_routes.domains.auth.routes — additional coverage (ext5).

Focus: _user_public_dict, _session_meta_for_response, _market_user_email_from_raw
additional branches, _normalize_auth_email, _jit_create_local_user_for_enterprise,
_attach_session_cookie, runtime_product_sku, auth_profile_avatar_upload/get
additional branches, auth_qr_issue client_hint from User-Agent, auth_session_validate
non-enterprise SKU and INFRA_TRANSIENT branches, auth_me with session_meta,
auth_logout with entitlements clear failure, auth_register enterprise with no token,
auth_register local with market sync failure, auth_oidc_callback with account_kind
from query_params, users_list with include_inactive variations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

# ---------------------------------------------------------------------------
# _user_public_dict
# ---------------------------------------------------------------------------


class TestUserPublicDict:
    """Cover _user_public_dict directly."""

    def test_basic_user(self):
        from app.fastapi_routes.domains.auth.routes import _user_public_dict

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "alice"
        mock_user.display_name = "Alice"
        mock_user.email = "alice@example.com"
        mock_user.role = "admin"
        mock_user.is_active = True
        mock_user.wx_avatar_url = "/avatars/1.png"

        with patch(
            "app.utils.user_avatar_storage.public_avatar_url",
            return_value="/avatars/1.png",
        ):
            result = _user_public_dict(mock_user)
        assert result["id"] == 1
        assert result["username"] == "alice"
        assert result["display_name"] == "Alice"
        assert result["email"] == "alice@example.com"
        assert result["role"] == "admin"
        assert result["is_active"] is True
        assert result["avatar_url"] == "/avatars/1.png"

    def test_user_no_avatar(self):
        from app.fastapi_routes.domains.auth.routes import _user_public_dict

        mock_user = MagicMock()
        mock_user.id = 2
        mock_user.username = "bob"
        mock_user.display_name = "Bob"
        mock_user.email = "bob@example.com"
        mock_user.role = "viewer"
        mock_user.is_active = False
        # wx_avatar_url attribute missing -> getattr returns None
        del mock_user.wx_avatar_url

        with patch(
            "app.utils.user_avatar_storage.public_avatar_url",
            return_value="",
        ):
            result = _user_public_dict(mock_user)
        assert result["avatar_url"] == ""
        assert result["is_active"] is False

    def test_user_with_none_avatar(self):
        from app.fastapi_routes.domains.auth.routes import _user_public_dict

        mock_user = MagicMock()
        mock_user.id = 3
        mock_user.username = "charlie"
        mock_user.display_name = "Charlie"
        mock_user.email = ""
        mock_user.role = "operator"
        mock_user.is_active = True
        mock_user.wx_avatar_url = None

        with patch(
            "app.utils.user_avatar_storage.public_avatar_url",
            return_value="",
        ):
            result = _user_public_dict(mock_user)
        assert result["email"] == ""
        assert result["role"] == "operator"


# ---------------------------------------------------------------------------
# _session_meta_for_response
# ---------------------------------------------------------------------------


class TestSessionMetaForResponse:
    """Cover _session_meta_for_response directly."""

    def test_no_sid(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        request = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.session_id_from_request",
            return_value=None,
        ):
            result = _session_meta_for_response(request)
        assert result == {}

    def test_no_sid_empty_string(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        request = MagicMock()
        with patch(
            "app.fastapi_routes.domains.auth.routes.session_id_from_request",
            return_value="",
        ):
            result = _session_meta_for_response(request)
        assert result == {}

    def test_with_user(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        request = MagicMock()
        mock_user = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid123",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                return_value={"account_kind": "enterprise", "tenant_id": 100},
            ) as mock_enrich,
        ):
            result = _session_meta_for_response(request, mock_user)
        assert result["account_kind"] == "enterprise"
        assert result["tenant_id"] == 100
        mock_enrich.assert_called_once_with("sid123", mock_user)

    def test_without_user_loads_meta(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid456",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "personal", "company_brand": "Acme"},
            ) as mock_load,
        ):
            result = _session_meta_for_response(request, None)
        assert result["account_kind"] == "personal"
        assert result["company_brand"] == "Acme"
        mock_load.assert_called_once_with("sid456")

    def test_without_user_meta_empty(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid789",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            result = _session_meta_for_response(request, None)
        assert result == {}

    def test_without_user_meta_returns_empty_dict(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid000",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={},
            ),
        ):
            result = _session_meta_for_response(request, None)
        assert result == {}


# ---------------------------------------------------------------------------
# _market_user_email_from_raw — additional branches
# ---------------------------------------------------------------------------


class TestMarketUserEmailFromRawAdditional:
    """Cover _market_user_email_from_raw additional branches."""

    def test_non_dict_input(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        assert _market_user_email_from_raw("not a dict") == ""
        assert _market_user_email_from_raw(None) == ""
        assert _market_user_email_from_raw([]) == ""
        assert _market_user_email_from_raw(42) == ""

    def test_user_dict_no_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"user": {"name": "alice"}}
        assert _market_user_email_from_raw(raw) == ""

    def test_user_dict_empty_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"user": {"email": ""}}
        assert _market_user_email_from_raw(raw) == ""

    def test_user_dict_whitespace_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"user": {"email": "  "}}
        assert _market_user_email_from_raw(raw) == ""

    def test_user_dict_valid_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"user": {"email": "alice@example.com"}}
        assert _market_user_email_from_raw(raw) == "alice@example.com"

    def test_user_dict_email_with_whitespace(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"user": {"email": "  alice@example.com  "}}
        assert _market_user_email_from_raw(raw) == "alice@example.com"

    def test_data_user_dict_valid_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"data": {"user": {"email": "bob@example.com"}}}
        assert _market_user_email_from_raw(raw) == "bob@example.com"

    def test_data_user_dict_no_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"data": {"user": {"name": "bob"}}}
        assert _market_user_email_from_raw(raw) == ""

    def test_data_not_dict(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"data": "not a dict"}
        assert _market_user_email_from_raw(raw) == ""

    def test_data_user_not_dict(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"data": {"user": "not a dict"}}
        assert _market_user_email_from_raw(raw) == ""

    def test_no_user_no_data(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"other": "value"}
        assert _market_user_email_from_raw(raw) == ""


# ---------------------------------------------------------------------------
# _normalize_auth_email
# ---------------------------------------------------------------------------


class TestNormalizeAuthEmail:
    """Cover _normalize_auth_email directly."""

    def test_basic(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        assert _normalize_auth_email("Alice@Example.COM") == "alice@example.com"

    def test_with_whitespace(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        assert _normalize_auth_email("  Alice@Example.COM  ") == "alice@example.com"

    def test_empty(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        assert _normalize_auth_email("") == ""

    def test_none(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        assert _normalize_auth_email(None) == ""

    def test_already_lower(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        assert _normalize_auth_email("alice@example.com") == "alice@example.com"


# ---------------------------------------------------------------------------
# _jit_create_local_user_for_enterprise
# ---------------------------------------------------------------------------


class TestJitCreateLocalUserForEnterprise:
    """Cover _jit_create_local_user_for_enterprise branches."""

    @patch("app.utils.time.utc_now_naive", return_value="2026-06-17T00:00:00")
    @patch("app.utils.password_hash.generate_password_hash", return_value="hashed")
    @patch("app.db.session.get_db")
    @patch("app.db.models.user.User")
    def test_create_success(self, mock_user_model, mock_get_db, mock_hash, mock_time):
        from app.fastapi_routes.domains.auth.routes import (
            _jit_create_local_user_for_enterprise,
        )

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = _jit_create_local_user_for_enterprise("newuser", "pass123", "a@b.com")
        assert result is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("app.utils.password_hash.generate_password_hash", return_value="hashed")
    @patch("app.db.session.get_db")
    @patch("app.db.models.user.User")
    def test_user_already_exists(self, mock_user_model, mock_get_db, mock_hash):
        from app.fastapi_routes.domains.auth.routes import (
            _jit_create_local_user_for_enterprise,
        )

        mock_db = MagicMock()
        mock_existing = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_existing
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = _jit_create_local_user_for_enterprise("existing", "pass123")
        assert result is False
        mock_db.add.assert_not_called()

    @patch("app.db.session.get_db")
    @patch("app.db.models.user.User")
    def test_infra_transient(self, mock_user_model, mock_get_db):
        from app.fastapi_routes.domains.auth.routes import (
            _jit_create_local_user_for_enterprise,
        )

        # Make get_db context manager raise a RuntimeError (which is in INFRA_TRANSIENT)
        mock_get_db.side_effect = RuntimeError("db connection failed")

        result = _jit_create_local_user_for_enterprise("user", "pass123")
        assert result is False

    @patch("app.utils.password_hash.generate_password_hash", return_value="hashed")
    @patch("app.db.session.get_db")
    @patch("app.db.models.user.User")
    def test_create_no_email(self, mock_user_model, mock_get_db, mock_hash):
        from app.fastapi_routes.domains.auth.routes import (
            _jit_create_local_user_for_enterprise,
        )

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = _jit_create_local_user_for_enterprise("newuser", "pass123")
        assert result is True


# ---------------------------------------------------------------------------
# _attach_session_cookie
# ---------------------------------------------------------------------------


class TestAttachSessionCookie:
    """Cover _attach_session_cookie directly."""

    def test_empty_session_id(self):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "")
        assert result is resp

    def test_none_session_id(self):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, None)
        assert result is resp

    def test_whitespace_session_id(self):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "   ")
        assert result is resp

    def test_valid_session_id_default_cookie(self):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp
        # Cookie should be set
        assert "set-cookie" in result.headers

    def test_custom_cookie_name(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_NAME", "custom_session")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_custom_max_age(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_MAX_AGE", "3600")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_httponly_disabled(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_HTTPONLY", "0")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_httponly_false(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_HTTPONLY", "false")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_secure_enabled(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_secure_true(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_secure_yes(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_SECURE", "yes")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp

    def test_custom_samesite(self, monkeypatch):
        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        monkeypatch.setenv("SESSION_COOKIE_SAMESITE", "Strict")
        resp = JSONResponse({"success": True})
        result = _attach_session_cookie(resp, "session123")
        assert result is resp


# ---------------------------------------------------------------------------
# runtime_product_sku
# ---------------------------------------------------------------------------


class TestRuntimeProductSku:
    """Cover runtime_product_sku directly."""

    def test_enterprise_sku(self):
        from app.fastapi_routes.domains.auth.routes import runtime_product_sku

        with patch(
            "app.mod_sdk.product_skus.resolve_product_sku",
            return_value="enterprise",
        ):
            result = runtime_product_sku()
        assert result["success"] is True
        assert result["data"]["sku"] == "enterprise"
        assert result["data"]["is_enterprise_edition"] is True

    def test_generic_sku(self):
        from app.fastapi_routes.domains.auth.routes import runtime_product_sku

        with patch(
            "app.mod_sdk.product_skus.resolve_product_sku",
            return_value="generic",
        ):
            result = runtime_product_sku()
        assert result["success"] is True
        assert result["data"]["sku"] == "generic"
        assert result["data"]["is_enterprise_edition"] is False

    def test_empty_sku_defaults_to_generic(self):
        from app.fastapi_routes.domains.auth.routes import runtime_product_sku

        with patch(
            "app.mod_sdk.product_skus.resolve_product_sku",
            return_value="",
        ):
            result = runtime_product_sku()
        assert result["success"] is True
        assert result["data"]["sku"] == "generic"
        assert result["data"]["is_enterprise_edition"] is False

    def test_none_sku_defaults_to_generic(self):
        from app.fastapi_routes.domains.auth.routes import runtime_product_sku

        with patch(
            "app.mod_sdk.product_skus.resolve_product_sku",
            return_value=None,
        ):
            result = runtime_product_sku()
        assert result["success"] is True
        assert result["data"]["sku"] == "generic"


# ---------------------------------------------------------------------------
# auth_profile_avatar_upload — additional branches
# ---------------------------------------------------------------------------


class TestAuthProfileAvatarUploadAdditional:
    """Cover auth_profile_avatar_upload additional branches."""

    @pytest.mark.asyncio
    async def test_no_file(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_user = MagicMock()
        mock_user.id = 1
        result = await auth_profile_avatar_upload(file=None, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_file_no_filename(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = ""
        mock_user = MagicMock()
        mock_user.id = 1
        result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_file_none_filename(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = None
        mock_user = MagicMock()
        mock_user.id = 1
        result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_value_error_on_save(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = "avatar.png"
        mock_file.read = AsyncMock(return_value=b"png data")
        mock_user = MagicMock()
        mock_user.id = 1

        with (
            patch("app.utils.secure_filename.secure_filename", return_value="avatar.png"),
            patch(
                "app.utils.user_avatar_storage.save_user_avatar_file",
                side_effect=ValueError("invalid file"),
            ),
        ):
            result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_os_error_on_save(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = "avatar.png"
        mock_file.read = AsyncMock(return_value=b"png data")
        mock_user = MagicMock()
        mock_user.id = 1

        with (
            patch("app.utils.secure_filename.secure_filename", return_value="avatar.png"),
            patch(
                "app.utils.user_avatar_storage.save_user_avatar_file",
                side_effect=OSError("disk full"),
            ),
        ):
            result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_success_no_ext(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = "avatar"  # no extension
        mock_file.read = AsyncMock(return_value=b"png data")
        mock_user = MagicMock()
        mock_user.id = 1

        with (
            patch("app.utils.secure_filename.secure_filename", return_value="avatar"),
            patch("app.utils.user_avatar_storage.save_user_avatar_file") as mock_save,
            patch("app.utils.user_avatar_storage.AVATAR_API_PATH", "/api/auth/avatar"),
            patch("app.db.session.get_db") as mock_get_db,
        ):
            mock_db = MagicMock()
            mock_row = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_row
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert result["success"] is True
        assert result["data"]["avatar_url"] == "/api/auth/avatar"
        mock_save.assert_called_once_with(1, b"png data", "png")

    @pytest.mark.asyncio
    async def test_success_with_ext(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = "photo.jpg"
        mock_file.read = AsyncMock(return_value=b"jpg data")
        mock_user = MagicMock()
        mock_user.id = 1

        with (
            patch("app.utils.secure_filename.secure_filename", return_value="photo.jpg"),
            patch("app.utils.user_avatar_storage.save_user_avatar_file") as mock_save,
            patch("app.utils.user_avatar_storage.AVATAR_API_PATH", "/api/auth/avatar"),
            patch("app.db.session.get_db") as mock_get_db,
        ):
            mock_db = MagicMock()
            mock_row = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_row
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert result["success"] is True
        mock_save.assert_called_once_with(1, b"jpg data", "jpg")

    @pytest.mark.asyncio
    async def test_success_user_not_found_in_db(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = "avatar.png"
        mock_file.read = AsyncMock(return_value=b"png data")
        mock_user = MagicMock()
        mock_user.id = 1

        with (
            patch("app.utils.secure_filename.secure_filename", return_value="avatar.png"),
            patch("app.utils.user_avatar_storage.save_user_avatar_file"),
            patch("app.utils.user_avatar_storage.AVATAR_API_PATH", "/api/auth/avatar"),
            patch("app.db.session.get_db") as mock_get_db,
        ):
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_secure_filename_returns_empty(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_upload

        mock_file = MagicMock()
        mock_file.filename = "../../etc/passwd"
        mock_file.read = AsyncMock(return_value=b"png data")
        mock_user = MagicMock()
        mock_user.id = 1

        with (
            patch("app.utils.secure_filename.secure_filename", return_value=""),
            patch("app.utils.user_avatar_storage.save_user_avatar_file") as mock_save,
            patch("app.utils.user_avatar_storage.AVATAR_API_PATH", "/api/auth/avatar"),
            patch("app.db.session.get_db") as mock_get_db,
        ):
            mock_db = MagicMock()
            mock_row = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_row
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = await auth_profile_avatar_upload(file=mock_file, user=mock_user)
        assert result["success"] is True
        # Should use default "avatar.png"
        mock_save.assert_called_once_with(1, b"png data", "png")


# ---------------------------------------------------------------------------
# auth_profile_avatar_get — additional branches
# ---------------------------------------------------------------------------


class TestAuthProfileAvatarGetAdditional:
    """Cover auth_profile_avatar_get additional branches."""

    def test_no_avatar_set(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_get

        mock_user = MagicMock()
        mock_user.id = 1
        with patch("app.utils.user_avatar_storage.avatar_file_for_user", return_value=None):
            result = auth_profile_avatar_get(user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    def test_avatar_exists(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_get

        mock_user = MagicMock()
        mock_user.id = 1
        with (
            patch(
                "app.utils.user_avatar_storage.avatar_file_for_user",
                return_value="/path/to/avatar.png",
            ),
            patch(
                "app.utils.user_avatar_storage.media_type_for_path",
                return_value="image/png",
            ),
        ):
            result = auth_profile_avatar_get(user=mock_user)
        assert isinstance(result, FileResponse)
        assert result.media_type == "image/png"

    def test_avatar_jpg(self):
        from app.fastapi_routes.domains.auth.routes import auth_profile_avatar_get

        mock_user = MagicMock()
        mock_user.id = 1
        with (
            patch(
                "app.utils.user_avatar_storage.avatar_file_for_user",
                return_value="/path/to/avatar.jpg",
            ),
            patch(
                "app.utils.user_avatar_storage.media_type_for_path",
                return_value="image/jpeg",
            ),
        ):
            result = auth_profile_avatar_get(user=mock_user)
        assert isinstance(result, FileResponse)
        assert result.media_type == "image/jpeg"


# ---------------------------------------------------------------------------
# auth_qr_issue — client_hint from User-Agent
# ---------------------------------------------------------------------------


class TestAuthQrIssueAdditional:
    """Cover auth_qr_issue client_hint from User-Agent."""

    @pytest.mark.asyncio
    async def test_client_hint_from_body(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_issue

        request = MagicMock()
        request.headers = {"User-Agent": "browser-agent"}
        with patch(
            "app.security.auth_qr_login.issue_auth_qr",
            return_value={"qr_id": "q1", "poll_secret": "s1"},
        ) as mock_issue:
            result = await auth_qr_issue(request, {"client_hint": "custom-hint"})
        assert result["success"] is True
        mock_issue.assert_called_once_with(client_hint="custom-hint")

    @pytest.mark.asyncio
    async def test_client_hint_from_user_agent(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_issue

        request = MagicMock()
        request.headers = {"User-Agent": "Mozilla/5.0"}
        with patch(
            "app.security.auth_qr_login.issue_auth_qr",
            return_value={"qr_id": "q1", "poll_secret": "s1"},
        ) as mock_issue:
            result = await auth_qr_issue(request, {})
        assert result["success"] is True
        mock_issue.assert_called_once_with(client_hint="Mozilla/5.0")

    @pytest.mark.asyncio
    async def test_client_hint_empty_no_user_agent(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_issue

        request = MagicMock()
        request.headers = {}
        with patch(
            "app.security.auth_qr_login.issue_auth_qr",
            return_value={"qr_id": "q1", "poll_secret": "s1"},
        ) as mock_issue:
            result = await auth_qr_issue(request, {})
        assert result["success"] is True
        mock_issue.assert_called_once_with(client_hint="")

    @pytest.mark.asyncio
    async def test_client_hint_truncated(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_issue

        request = MagicMock()
        long_hint = "x" * 500
        with patch(
            "app.security.auth_qr_login.issue_auth_qr",
            return_value={"qr_id": "q1", "poll_secret": "s1"},
        ) as mock_issue:
            result = await auth_qr_issue(request, {"client_hint": long_hint})
        assert result["success"] is True
        # Should be truncated to 256 chars
        called_hint = mock_issue.call_args.kwargs["client_hint"]
        assert len(called_hint) == 256


# ---------------------------------------------------------------------------
# auth_session_validate — additional branches
# ---------------------------------------------------------------------------


class TestAuthSessionValidateAdditional:
    """Cover auth_session_validate additional branches."""

    @pytest.mark.asyncio
    async def test_non_enterprise_sku(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_for_session",
                new=AsyncMock(return_value=["mod1"]),
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
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["entitled_mod_ids"] == ["mod1"]

    @pytest.mark.asyncio
    async def test_enterprise_market_check_infra_transient(self):
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
                new=AsyncMock(side_effect=RuntimeError("market down")),
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
        assert isinstance(result, dict)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_entitlements_sync_infra_transient(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_for_session",
                new=AsyncMock(side_effect=RuntimeError("entitlements down")),
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
        assert isinstance(result, dict)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_with_session_meta(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
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
                return_value={
                    "account_kind": "enterprise",
                    "company_brand": "Acme",
                    "market_is_admin": True,
                    "market_is_enterprise": False,
                    "market_user_id": 42,
                    "local_user_id": 1,
                    "tenant_id": 100,
                    "tenant_name": "Acme Inc",
                    "impersonating_market_user_id": None,
                    "impersonating_username": "",
                },
            ),
        ):
            mock_service = MagicMock()
            mock_service.session_manager.get_session_info.return_value = {"user_id": 1}
            mock_get.return_value = mock_service
            result = await auth_session_validate(request)
        assert isinstance(result, dict)
        assert result["account_kind"] == "enterprise"
        assert result["company_brand"] == "Acme"
        assert result["market_is_admin"] is True
        assert result["market_is_enterprise"] is False
        assert result["market_user_id"] == 42
        assert result["local_user_id"] == 1
        assert result["tenant_id"] == 100
        assert result["tenant_name"] == "Acme Inc"
        assert result["impersonating_market_user_id"] is None
        assert result["impersonating_username"] == ""

    @pytest.mark.asyncio
    async def test_no_entitled_mod_ids_no_session_meta(self):
        from app.fastapi_routes.domains.auth.routes import auth_session_validate

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
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
        assert isinstance(result, dict)
        assert "entitled_mod_ids" not in result
        assert "account_kind" not in result


# ---------------------------------------------------------------------------
# auth_me — with session_meta
# ---------------------------------------------------------------------------


class TestAuthMeAdditional:
    """Cover auth_me with session_meta branches."""

    def test_with_session_meta(self):
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
                return_value={
                    "account_kind": "enterprise",
                    "company_brand": "Acme",
                    "market_is_admin": True,
                    "market_is_enterprise": False,
                    "market_user_id": 42,
                    "local_user_id": 1,
                    "tenant_id": 100,
                    "tenant_name": "Acme Inc",
                    "impersonating_market_user_id": 99,
                    "impersonating_username": "admin",
                },
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.get_user_permissions.return_value = ["read", "write"]
            mock_get.return_value = mock_service
            result = auth_me(request)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["data"]["account_kind"] == "enterprise"
        assert result["data"]["company_brand"] == "Acme"
        assert result["data"]["market_is_admin"] is True
        assert result["data"]["market_is_enterprise"] is False
        assert result["data"]["market_user_id"] == 42
        assert result["data"]["local_user_id"] == 1
        assert result["data"]["tenant_id"] == 100
        assert result["data"]["tenant_name"] == "Acme Inc"
        assert result["data"]["impersonating_market_user_id"] == 99
        assert result["data"]["impersonating_username"] == "admin"

    def test_with_empty_session_meta(self):
        from app.fastapi_routes.domains.auth.routes import auth_me

        request = MagicMock()
        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.id = 5
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
            mock_service.get_user_permissions.return_value = []
            mock_get.return_value = mock_service
            result = auth_me(request)
        assert isinstance(result, dict)
        assert result["data"]["account_kind"] == "enterprise"
        assert result["data"]["company_brand"] == ""
        assert result["data"]["market_is_admin"] is False
        assert result["data"]["market_is_enterprise"] is False
        assert result["data"]["market_user_id"] is None
        assert result["data"]["local_user_id"] == 5
        assert result["data"]["tenant_id"] is None
        assert result["data"]["tenant_name"] == ""
        assert result["data"]["impersonating_market_user_id"] is None
        assert result["data"]["impersonating_username"] == ""

    def test_with_tenant_name_fallback(self):
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
                return_value={
                    "company_brand": "Fallback Brand",
                    # tenant_name missing -> should fallback to company_brand
                },
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.get_user_permissions.return_value = []
            mock_get.return_value = mock_service
            result = auth_me(request)
        assert isinstance(result, dict)
        assert result["data"]["tenant_name"] == "Fallback Brand"


# ---------------------------------------------------------------------------
# auth_logout — with entitlements clear failure
# ---------------------------------------------------------------------------


class TestAuthLogoutAdditional:
    """Cover auth_logout with entitlements clear failure."""

    def test_logout_with_entitlements_clear_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_logout

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.fastapi_routes.market_account.clear_session_market_token"),
            patch(
                "app.enterprise.mod_entitlements.clear_session_entitlements",
                side_effect=RuntimeError("cache down"),
            ),
        ):
            mock_service = MagicMock()
            mock_service.logout.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = auth_logout(request)
        assert isinstance(result, JSONResponse)

    def test_logout_with_entitlements_import_failure(self):
        from app.fastapi_routes.domains.auth.routes import auth_logout
        from app.utils.operational_errors import INFRA_TRANSIENT

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid",
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.fastapi_routes.market_account.clear_session_market_token"),
            patch.dict(
                "sys.modules",
                {"app.enterprise.mod_entitlements": None},
            ),
        ):
            mock_service = MagicMock()
            mock_service.logout.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = auth_logout(request)
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_register — enterprise with no token
# ---------------------------------------------------------------------------


class TestAuthRegisterAdditional:
    """Cover auth_register additional branches."""

    @pytest.mark.asyncio
    async def test_enterprise_no_market_token(self):
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
                        # no token, no refresh_token
                    }
                ),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._jit_create_local_user_for_enterprise",
                return_value=True,
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
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
    async def test_enterprise_with_refresh_token(self):
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
                    }
                ),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._jit_create_local_user_for_enterprise",
                return_value=True,
            ),
            patch("app.application.auth_app_service.get_auth_app_service") as mock_get,
            patch("app.fastapi_routes.market_account.save_session_market_token") as mock_save,
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
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_local_with_market_sync_failure(self):
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
                new=AsyncMock(side_effect=RuntimeError("market down")),
            ),
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

    @pytest.mark.asyncio
    async def test_local_market_login_no_success(self):
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
                new=AsyncMock(return_value={"success": False}),
            ),
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

    @pytest.mark.asyncio
    async def test_local_market_login_success_no_token(self):
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
                new=AsyncMock(return_value={"success": True, "token": "", "refresh_token": ""}),
            ),
            patch("app.fastapi_routes.market_account.save_session_market_token") as mock_save,
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
        # save_session_market_token should not be called since token is empty
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_create_user_failure_with_unique(self):
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
                "message": "UNIQUE constraint failed",
            }
            mock_get.return_value = mock_service
            result = await auth_register(request, {"username": "u", "password": "pass123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_local_create_user_failure_with_already_exists(self):
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


# ---------------------------------------------------------------------------
# auth_oidc_callback — additional branches
# ---------------------------------------------------------------------------


class TestAuthOidcCallbackAdditional:
    """Cover auth_oidc_callback additional branches."""

    @pytest.mark.asyncio
    async def test_enterprise_sku(self):
        from app.fastapi_routes.domains.auth.routes import auth_oidc_callback

        request = MagicMock()
        request.query_params = {"code": "abc", "state": "ok", "account_kind": "enterprise"}
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
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
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

    @pytest.mark.asyncio
    async def test_no_username_in_auth_result(self):
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
                "user": {},  # no username
            }
            mock_get.return_value = mock_service
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)

    @pytest.mark.asyncio
    async def test_no_session_id_in_auth_result(self):
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
                # no session_id
                "user": {"username": "u"},
            }
            mock_get.return_value = mock_service
            result = await auth_oidc_callback(request)
        assert isinstance(result, RedirectResponse)


# ---------------------------------------------------------------------------
# auth_login — additional branches
# ---------------------------------------------------------------------------


class TestAuthLoginAdditional:
    """Cover auth_login additional branches."""

    @pytest.mark.asyncio
    async def test_enterprise_sku(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid"}, None)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(request, {"username": "u", "password": "p"})
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_with_account_kind_enterprise(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid"}, None)),
            ) as mock_run,
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(
                request, {"username": "u", "password": "p", "account_kind": "enterprise"}
            )
        assert isinstance(result, JSONResponse)
        # Check that account_kind was normalized
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["account_kind"] == "enterprise"

    @pytest.mark.asyncio
    async def test_with_account_kind_personal(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=({"success": True, "session_id": "sid"}, None)),
            ) as mock_run,
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(
                request, {"username": "u", "password": "p", "account_kind": "personal"}
            )
        assert isinstance(result, JSONResponse)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["account_kind"] == "personal"

    @pytest.mark.asyncio
    async def test_result_none(self):
        from app.fastapi_routes.domains.auth.routes import auth_login

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
            patch(
                "app.application.enterprise_login_flow.run_market_first_login",
                new=AsyncMock(return_value=(None, None)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login(request, {"username": "u", "password": "p"})
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_login_with_phone_code — additional branches
# ---------------------------------------------------------------------------


class TestAuthLoginWithPhoneCodeAdditional:
    """Cover auth_login_with_phone_code additional branches."""

    @pytest.mark.asyncio
    async def test_enterprise_sku(self):
        from app.fastapi_routes.domains.auth.routes import auth_login_with_phone_code

        request = MagicMock()
        with (
            patch("app.utils.metrics.auth_login_duration_seconds") as mock_metric,
            patch("app.application.auth_app_service.get_auth_app_service"),
            patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"),
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

    @pytest.mark.asyncio
    async def test_with_username(self):
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
            ) as mock_run,
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login_with_phone_code(
                request, {"phone": "13800000000", "code": "1234", "username": "alice"}
            )
        assert isinstance(result, JSONResponse)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["username"] == "alice"

    @pytest.mark.asyncio
    async def test_result_none(self):
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
                new=AsyncMock(return_value=(None, None)),
            ),
        ):
            mock_labels = MagicMock()
            mock_metric.labels.return_value = mock_labels
            result = await auth_login_with_phone_code(
                request, {"phone": "13800000000", "code": "1234"}
            )
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# auth_forgot_password_reset — additional branches
# ---------------------------------------------------------------------------


class TestAuthForgotPasswordResetAdditional:
    """Cover auth_forgot_password_reset additional branches."""

    @pytest.mark.asyncio
    async def test_with_verification_code_field(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        with (
            patch(
                "app.fastapi_routes.market_account.reset_market_password_with_code",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._sync_local_password_for_email",
                return_value=1,
            ),
        ):
            result = await auth_forgot_password_reset(
                {
                    "email": "a@b.com",
                    "verification_code": "123456",
                    "new_password": "newpass123",
                }
            )
        assert result["success"] is True
        assert result["data"]["local_users_updated"] == 1

    @pytest.mark.asyncio
    async def test_with_password_field(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        with (
            patch(
                "app.fastapi_routes.market_account.reset_market_password_with_code",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch(
                "app.fastapi_routes.domains.auth.routes._sync_local_password_for_email",
                return_value=0,
            ),
        ):
            result = await auth_forgot_password_reset(
                {
                    "email": "a@b.com",
                    "code": "123456",
                    "password": "newpass123",
                }
            )
        assert result["success"] is True
        assert result["data"]["local_users_updated"] == 0

    @pytest.mark.asyncio
    async def test_empty_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        result = await auth_forgot_password_reset({"email": "", "new_password": "newpass123"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_no_at_in_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        result = await auth_forgot_password_reset(
            {"email": "notanemail", "new_password": "newpass123"}
        )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        result = await auth_forgot_password_reset({"email": "a@b.com", "new_password": ""})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_market_reset_no_message(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_reset

        with patch(
            "app.fastapi_routes.market_account.reset_market_password_with_code",
            new=AsyncMock(return_value={"success": False}),
        ):
            result = await auth_forgot_password_reset(
                {"email": "a@b.com", "code": "123456", "new_password": "newpass123"}
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# auth_forgot_password_send_code — additional branches
# ---------------------------------------------------------------------------


class TestAuthForgotPasswordSendCodeAdditional:
    """Cover auth_forgot_password_send_code additional branches."""

    @pytest.mark.asyncio
    async def test_success_with_message(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.market_account.send_market_reset_password_code",
                new=AsyncMock(
                    return_value={
                        "success": True,
                        "message": "Code sent",
                        "market_base_url": "https://market.example.com",
                    }
                ),
            ),
        ):
            result = await auth_forgot_password_send_code({"email": "a@b.com"})
        assert result["success"] is True
        assert result["message"] == "Code sent"
        assert result["data"]["market_base_url"] == "https://market.example.com"

    @pytest.mark.asyncio
    async def test_success_no_message(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.market_account.send_market_reset_password_code",
                new=AsyncMock(return_value={"success": True}),
            ),
        ):
            result = await auth_forgot_password_send_code({"email": "a@b.com"})
        assert result["success"] is True
        assert "若该邮箱已注册" in result["message"]

    @pytest.mark.asyncio
    async def test_failure_no_message(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_password_send_code

        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[],
            ),
            patch(
                "app.fastapi_routes.market_account.send_market_reset_password_code",
                new=AsyncMock(return_value={"success": False}),
            ),
        ):
            result = await auth_forgot_password_send_code({"email": "a@b.com"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502


# ---------------------------------------------------------------------------
# auth_forgot_account — additional branches
# ---------------------------------------------------------------------------


class TestAuthForgotAccountAdditional:
    """Cover auth_forgot_account additional branches."""

    def test_no_at_in_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        result = auth_forgot_account({"email": "notanemail"})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_none_email(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        result = auth_forgot_account({"email": None})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_no_email_key(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        result = auth_forgot_account({})
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_users_with_empty_username(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        mock_user1 = MagicMock()
        mock_user1.username = "alice"
        mock_user2 = MagicMock()
        mock_user2.username = ""  # empty username should be filtered out
        with patch(
            "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
            return_value=[mock_user1, mock_user2],
        ):
            result = auth_forgot_account({"email": "alice@example.com"})
        assert result["success"] is True
        assert result["data"]["usernames"] == ["alice"]
        assert result["data"]["found"] is True

    def test_users_with_none_username(self):
        from app.fastapi_routes.domains.auth.routes import auth_forgot_account

        mock_user = MagicMock()
        mock_user.username = None
        with patch(
            "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
            return_value=[mock_user],
        ):
            result = auth_forgot_account({"email": "alice@example.com"})
        assert result["success"] is True
        assert result["data"]["usernames"] == []
        # found is False because usernames is empty after filtering
        assert result["data"]["found"] is False


# ---------------------------------------------------------------------------
# auth_update_company_brand — additional branches
# ---------------------------------------------------------------------------


class TestAuthUpdateCompanyBrandAdditional:
    """Cover auth_update_company_brand additional branches."""

    @pytest.mark.asyncio
    async def test_with_company_field(self):
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
                request, {"company": "Acme Corp"}, user=mock_user
            )
        assert result["success"] is True
        assert result["company_brand"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_with_long_brand_truncated(self):
        from app.fastapi_routes.domains.auth.routes import auth_update_company_brand

        request = MagicMock()
        mock_user = MagicMock()
        long_brand = "x" * 500
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
                request, {"company_brand": long_brand}, user=mock_user
            )
        assert result["success"] is True
        assert len(result["company_brand"]) == 256

    @pytest.mark.asyncio
    async def test_with_empty_brand(self):
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
            result = await auth_update_company_brand(request, {"company_brand": ""}, user=mock_user)
        assert result["success"] is True
        assert result["company_brand"] == ""

    @pytest.mark.asyncio
    async def test_with_market_token_no_bearer_prefix(self):
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
                new=AsyncMock(return_value="raw_token"),
            ),
            patch("app.fastapi_routes.market_account._proxy_json", new=AsyncMock()) as mock_proxy,
        ):
            result = await auth_update_company_brand(
                request, {"company_brand": "Acme"}, user=mock_user
            )
        assert result["success"] is True
        # Should add Bearer prefix
        call_kwargs = mock_proxy.call_args.kwargs
        assert call_kwargs["authorization"] == "Bearer raw_token"

    @pytest.mark.asyncio
    async def test_with_market_token_already_bearer(self):
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
                new=AsyncMock(return_value="Bearer token123"),
            ),
            patch("app.fastapi_routes.market_account._proxy_json", new=AsyncMock()) as mock_proxy,
        ):
            result = await auth_update_company_brand(
                request, {"company_brand": "Acme"}, user=mock_user
            )
        assert result["success"] is True
        call_kwargs = mock_proxy.call_args.kwargs
        assert call_kwargs["authorization"] == "Bearer token123"

    @pytest.mark.asyncio
    async def test_with_meta_none(self):
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
                return_value=None,
            ),
            patch(
                "app.application.session_account_meta.persist_session_account_meta"
            ) as mock_persist,
            patch(
                "app.fastapi_routes.market_account.resolve_valid_market_access_token",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await auth_update_company_brand(
                request, {"company_brand": "Acme"}, user=mock_user
            )
        assert result["success"] is True
        # Should call persist with default account_kind "enterprise"
        call_kwargs = mock_persist.call_args.kwargs
        assert call_kwargs["account_kind"] == "enterprise"


# ---------------------------------------------------------------------------
# auth_subscription_status — additional branches
# ---------------------------------------------------------------------------


class TestAuthSubscriptionStatusAdditional:
    """Cover auth_subscription_status additional branches."""

    def test_with_user_id_zero(self):
        from app.fastapi_routes.domains.auth.routes import auth_subscription_status

        request = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 0
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.resolve_session_user",
                return_value=mock_user,
            ),
            patch(
                "app.application.tenant_subscription_app_service.subscription_status_for_user",
                return_value={"plan": "trial", "days_left": 30},
            ),
        ):
            result = auth_subscription_status(request)
        assert result["success"] is True
        assert result["data"]["plan"] == "trial"
        assert result["data"]["days_left"] == 30


# ---------------------------------------------------------------------------
# auth_qr_status — additional branches
# ---------------------------------------------------------------------------


class TestAuthQrStatusAdditional:
    """Cover auth_qr_status additional branches."""

    @pytest.mark.asyncio
    async def test_qr_confirmed_with_login_payload(self):
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
                    "login_payload": {
                        "user": {"id": 1, "username": "alice"},
                        "permissions": ["read"],
                    },
                },
            ),
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert isinstance(result, JSONResponse)
        # The payload should be spread into data
        import json

        body = json.loads(result.body)
        assert body["data"]["session_id"] == "sid"
        assert body["data"]["user"]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_qr_confirmed_no_login_payload(self):
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
                    "login_payload": None,
                },
            ),
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_qr_confirmed_consume_returns_none(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with (
            patch(
                "app.security.auth_qr_login.poll_auth_qr",
                return_value={"status": "confirmed"},
            ),
            patch(
                "app.security.auth_qr_login.consume_confirmed_qr",
                return_value=None,
            ),
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        # When consume returns None, falls through to return status
        assert result["data"]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_qr_status_other(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with patch(
            "app.security.auth_qr_login.poll_auth_qr",
            return_value={"status": "scanned"},
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        assert result["data"]["status"] == "scanned"

    @pytest.mark.asyncio
    async def test_qr_status_empty_dict_returns_404(self):
        from app.fastapi_routes.domains.auth.routes import auth_qr_status

        with patch(
            "app.security.auth_qr_login.poll_auth_qr",
            return_value={},
        ):
            result = await auth_qr_status(qr_id="q1", poll_secret="s1")
        # Empty dict is falsy, so returns 404
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# auth_password_change — additional branches
# ---------------------------------------------------------------------------


class TestAuthPasswordChangeAdditional:
    """Cover auth_password_change additional branches."""

    def test_only_old_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        result = auth_password_change(
            body={"old_password": "old", "new_password": ""}, user=mock_user
        )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_only_new_password(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        result = auth_password_change(
            body={"old_password": "", "new_password": "new"}, user=mock_user
        )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_no_body_fields(self):
        from app.fastapi_routes.domains.auth.routes import auth_password_change

        mock_user = MagicMock()
        result = auth_password_change(body={}, user=mock_user)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# users_list — additional branches
# ---------------------------------------------------------------------------


class TestUsersListAdditional:
    """Cover users_list additional branches."""

    def test_list_include_inactive_uppercase(self):
        from app.fastapi_routes.domains.auth.routes import users_list

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.list_users.return_value = [
                {"id": 1, "is_active": True},
                {"id": 2, "is_active": False},
            ]
            mock_get.return_value = mock_service
            result = users_list(include_inactive="TRUE", _user=mock_admin)
        # "TRUE".lower() == "true" so inactive users are included
        assert result["data"]["count"] == 2

    def test_list_empty_users(self):
        from app.fastapi_routes.domains.auth.routes import users_list

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.list_users.return_value = []
            mock_get.return_value = mock_service
            result = users_list(include_inactive="false", _user=mock_admin)
        assert result["data"]["count"] == 0
        assert result["data"]["users"] == []

    def test_list_users_no_is_active_key(self):
        from app.fastapi_routes.domains.auth.routes import users_list

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.list_users.return_value = [
                {"id": 1},  # no is_active key, defaults to True
                {"id": 2, "is_active": False},
            ]
            mock_get.return_value = mock_service
            result = users_list(include_inactive="false", _user=mock_admin)
        assert result["data"]["count"] == 1


# ---------------------------------------------------------------------------
# users_create — additional branches
# ---------------------------------------------------------------------------


class TestUsersCreateAdditional:
    """Cover users_create additional branches."""

    def test_create_admin_role(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.create_user.return_value = {
                "success": True,
                "user": {"id": 1, "role": "admin"},
            }
            mock_get.return_value = mock_service
            result = users_create(
                body={"username": "u", "password": "pass123", "role": "admin"},
                _user=mock_admin,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 201

    def test_create_operator_role(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.create_user.return_value = {
                "success": True,
                "user": {"id": 1, "role": "operator"},
            }
            mock_get.return_value = mock_service
            result = users_create(
                body={"username": "u", "password": "pass123", "role": "operator"},
                _user=mock_admin,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 201

    def test_create_default_role(self):
        from app.fastapi_routes.domains.auth.routes import users_create

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.create_user.return_value = {
                "success": True,
                "user": {"id": 1, "role": "viewer"},
            }
            mock_get.return_value = mock_service
            result = users_create(
                body={"username": "u", "password": "pass123"},
                _user=mock_admin,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 201

    def test_create_with_display_name_and_email(self):
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
                body={
                    "username": "u",
                    "password": "pass123",
                    "display_name": "Alice",
                    "email": "alice@example.com",
                },
                _user=mock_admin,
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 201


# ---------------------------------------------------------------------------
# users_update — additional branches
# ---------------------------------------------------------------------------


class TestUsersUpdateAdditional:
    """Cover users_update additional branches."""

    def test_update_no_role(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1},
            }
            mock_get.return_value = mock_service
            result = users_update(
                user_id=1,
                body={"display_name": "New", "email": "new@x.com"},
                _user=mock_admin,
            )
        assert result["success"] is True

    def test_update_valid_admin_role(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1, "role": "admin"},
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={"role": "admin"}, _user=mock_admin)
        assert result["success"] is True

    def test_update_valid_operator_role(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1, "role": "operator"},
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={"role": "operator"}, _user=mock_admin)
        assert result["success"] is True

    def test_update_valid_viewer_role(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1, "role": "viewer"},
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={"role": "viewer"}, _user=mock_admin)
        assert result["success"] is True

    def test_update_empty_body(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1},
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={}, _user=mock_admin)
        assert result["success"] is True

    def test_update_with_is_active(self):
        from app.fastapi_routes.domains.auth.routes import users_update

        mock_admin = MagicMock()
        with patch("app.application.get_user_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.update_user.return_value = {
                "success": True,
                "user": {"id": 1, "is_active": False},
            }
            mock_get.return_value = mock_service
            result = users_update(user_id=1, body={"is_active": False}, _user=mock_admin)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# users_reset_password — additional branches
# ---------------------------------------------------------------------------


class TestUsersResetPasswordAdditional:
    """Cover users_reset_password additional branches."""

    def test_reset_no_body(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        result = users_reset_password(user_id=1, body={}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_reset_empty_password(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        result = users_reset_password(user_id=1, body={"new_password": ""}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    def test_reset_exact_6_chars(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        with patch("app.application.auth_app_service.get_auth_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.reset_password.return_value = {"success": True}
            mock_get.return_value = mock_service
            result = users_reset_password(
                user_id=1, body={"new_password": "123456"}, _user=mock_admin
            )
        assert result["success"] is True

    def test_reset_5_chars(self):
        from app.fastapi_routes.domains.auth.routes import users_reset_password

        mock_admin = MagicMock()
        result = users_reset_password(user_id=1, body={"new_password": "12345"}, _user=mock_admin)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
