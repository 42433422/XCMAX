"""Tests for app.fastapi_routes.domains.auth.routes — deep coverage (ext3).

Focus: _user_public_dict, _session_meta_for_response, _market_user_email_from_raw,
_normalize_auth_email, _find_local_users_by_email, _open_registration_allowed,
_attach_session_cookie, _jit_create_local_user_for_enterprise.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _user_public_dict
# ---------------------------------------------------------------------------


class TestUserPublicDict:
    def test_with_user_object(self):
        from app.fastapi_routes.domains.auth.routes import _user_public_dict

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.display_name = "Test User"
        mock_user.email = "test@example.com"
        mock_user.role = "user"
        mock_user.is_active = True
        result = _user_public_dict(mock_user)
        assert isinstance(result, dict)
        assert result.get("id") == 1 or "id" in result

    def test_with_none_raises(self):
        from app.fastapi_routes.domains.auth.routes import _user_public_dict

        # _user_public_dict accesses user.id directly, so None raises AttributeError
        with pytest.raises(AttributeError):
            _user_public_dict(None)


# ---------------------------------------------------------------------------
# _session_meta_for_response
# ---------------------------------------------------------------------------


class TestSessionMetaForResponse:
    def test_with_no_user(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        mock_request = MagicMock()
        # Patch the binding in routes (not the origin module) so the real
        # session_id_from_request doesn't return a MagicMock sid that would
        # be passed to load_session_account_meta and hit the DB. Also stub
        # load_session_account_meta so no DB query is attempted.
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta", return_value=None
            ),
        ):
            result = _session_meta_for_response(mock_request, user=None)
        assert isinstance(result, dict)

    def test_with_user(self):
        from app.fastapi_routes.domains.auth.routes import _session_meta_for_response

        mock_request = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.enrich_session_meta_with_tenant",
                return_value={"account_kind": "enterprise"},
            ),
        ):
            result = _session_meta_for_response(mock_request, user=mock_user)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _market_user_email_from_raw
# ---------------------------------------------------------------------------


class TestMarketUserEmailFromRaw:
    def test_with_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        # _market_user_email_from_raw checks raw["user"]["email"] or raw["data"]["user"]["email"]
        raw = {"user": {"email": "test@example.com"}}
        result = _market_user_email_from_raw(raw)
        assert result == "test@example.com"

    def test_with_none(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        result = _market_user_email_from_raw(None)
        assert result == ""

    def test_with_empty_dict(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        result = _market_user_email_from_raw({})
        assert result == ""

    def test_with_data_user_email(self):
        from app.fastapi_routes.domains.auth.routes import _market_user_email_from_raw

        raw = {"data": {"user": {"email": "data@example.com"}}}
        result = _market_user_email_from_raw(raw)
        assert result == "data@example.com"


# ---------------------------------------------------------------------------
# _normalize_auth_email
# ---------------------------------------------------------------------------


class TestNormalizeAuthEmail:
    def test_lowercase(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        result = _normalize_auth_email("Test@Example.COM")
        assert result == "test@example.com"

    def test_strip_whitespace(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        result = _normalize_auth_email("  test@example.com  ")
        assert result.strip() == result

    def test_empty_string(self):
        from app.fastapi_routes.domains.auth.routes import _normalize_auth_email

        result = _normalize_auth_email("")
        assert result == ""


# ---------------------------------------------------------------------------
# _open_registration_allowed
# ---------------------------------------------------------------------------


class TestOpenRegistrationAllowed:
    def test_default_sku(self):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        result = _open_registration_allowed("community")
        assert isinstance(result, bool)

    def test_enterprise_sku(self):
        from app.fastapi_routes.domains.auth.routes import _open_registration_allowed

        result = _open_registration_allowed("enterprise")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _jit_create_local_user_for_enterprise
# ---------------------------------------------------------------------------


class TestJitCreateLocalUserForEnterprise:
    @patch("app.db.session.get_db")
    def test_create_success(self, mock_get_db):
        from app.fastapi_routes.domains.auth.routes import _jit_create_local_user_for_enterprise

        mock_db = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        result = _jit_create_local_user_for_enterprise("newuser", "password123", "test@example.com")
        assert isinstance(result, bool)

    @patch("app.db.session.get_db")
    def test_create_failure(self, mock_get_db):
        from app.fastapi_routes.domains.auth.routes import _jit_create_local_user_for_enterprise

        mock_get_db.side_effect = RuntimeError("DB error")
        result = _jit_create_local_user_for_enterprise("newuser", "password123", "test@example.com")
        assert result is False


# ---------------------------------------------------------------------------
# _attach_session_cookie
# ---------------------------------------------------------------------------


class TestAttachSessionCookie:
    def test_with_session_id(self):
        from fastapi.responses import JSONResponse

        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        response = JSONResponse({"success": True})
        result = _attach_session_cookie(response, "test-session-id")
        assert isinstance(result, JSONResponse)

    def test_with_none_session_id(self):
        from fastapi.responses import JSONResponse

        from app.fastapi_routes.domains.auth.routes import _attach_session_cookie

        response = JSONResponse({"success": True})
        result = _attach_session_cookie(response, None)
        assert isinstance(result, JSONResponse)


# ---------------------------------------------------------------------------
# runtime_product_sku
# ---------------------------------------------------------------------------


class TestRuntimeProductSku:
    def test_returns_dict(self):
        from app.fastapi_routes.domains.auth.routes import runtime_product_sku

        result = runtime_product_sku()
        assert isinstance(result, dict)
        assert "success" in result
        assert "data" in result
