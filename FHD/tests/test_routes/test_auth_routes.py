"""Comprehensive tests for app.fastapi_routes.domains.auth.routes.

Covers: helper functions and route validation/error paths.
Route tests that require DB are tested via direct function calls with mocked dependencies.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def auth_mod():
    from app.fastapi_routes.domains.auth import routes

    return routes


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestNormalizeAuthEmail:
    def test_normalizes(self, auth_mod):
        assert auth_mod._normalize_auth_email("  Test@Example.COM  ") == "test@example.com"

    def test_none_returns_empty(self, auth_mod):
        assert auth_mod._normalize_auth_email(None) == ""

    def test_empty_string(self, auth_mod):
        assert auth_mod._normalize_auth_email("") == ""


class TestMarketUserEmailFromRaw:
    def test_dict_with_user_email(self, auth_mod):
        raw = {"user": {"email": "  a@b.com  "}}
        assert auth_mod._market_user_email_from_raw(raw) == "a@b.com"

    def test_dict_with_data_user_email(self, auth_mod):
        raw = {"data": {"user": {"email": "x@y.com"}}}
        assert auth_mod._market_user_email_from_raw(raw) == "x@y.com"

    def test_not_dict(self, auth_mod):
        assert auth_mod._market_user_email_from_raw("not a dict") == ""

    def test_no_email(self, auth_mod):
        assert auth_mod._market_user_email_from_raw({"user": {}}) == ""

    def test_none(self, auth_mod):
        assert auth_mod._market_user_email_from_raw(None) == ""


class TestOpenRegistrationAllowed:
    def test_env_true(self, auth_mod, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "true")
        assert auth_mod._open_registration_allowed("generic") is True

    def test_env_false(self, auth_mod, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "0")
        assert auth_mod._open_registration_allowed("generic") is False

    def test_enterprise_default_false(self, auth_mod, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
        assert auth_mod._open_registration_allowed("enterprise") is False

    def test_personal_default_true(self, auth_mod, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
        assert auth_mod._open_registration_allowed("personal") is True

    def test_env_yes(self, auth_mod, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "yes")
        assert auth_mod._open_registration_allowed("enterprise") is True

    def test_env_no(self, auth_mod, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "no")
        assert auth_mod._open_registration_allowed("personal") is False


class TestAttachSessionCookie:
    def test_empty_sid_returns_unchanged(self, auth_mod):
        resp = MagicMock()
        result = auth_mod._attach_session_cookie(resp, "")
        assert result is resp

    def test_none_sid_returns_unchanged(self, auth_mod):
        resp = MagicMock()
        result = auth_mod._attach_session_cookie(resp, None)
        assert result is resp

    def test_sets_cookie(self, auth_mod):
        resp = MagicMock()
        auth_mod._attach_session_cookie(resp, "sid-123")
        resp.set_cookie.assert_called_once()


class TestUserPublicDict:
    def test_basic(self, auth_mod):
        user = MagicMock()
        user.id = 1
        user.username = "test"
        user.display_name = "Test User"
        user.email = "t@e.com"
        user.role = "admin"
        user.is_active = True
        user.wx_avatar_url = None
        with patch("app.utils.user_avatar_storage.public_avatar_url", return_value=""):
            d = auth_mod._user_public_dict(user)
            assert d["id"] == 1
            assert d["username"] == "test"
            assert d["is_active"] is True


class TestFindLocalUsersByEmail:
    def test_invalid_email_returns_empty(self, auth_mod):
        with patch("app.db.session.get_db"):
            result = auth_mod._find_local_users_by_email("no-at-sign")
            assert result == []

    def test_empty_email_returns_empty(self, auth_mod):
        result = auth_mod._find_local_users_by_email("")
        assert result == []


class TestSyncLocalPasswordForEmail:
    def test_no_users(self, auth_mod):
        with patch(
            "app.fastapi_routes.domains.auth.routes._find_local_users_by_email", return_value=[]
        ):
            result = auth_mod._sync_local_password_for_email("a@b.com", "newpass")
            assert result == 0

    def test_updates_matching_users(self, auth_mod):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_auth = MagicMock()
        mock_auth.reset_password.return_value = {"success": True}
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes._find_local_users_by_email",
                return_value=[mock_user],
            ),
            patch("app.application.auth_app_service.get_auth_app_service", return_value=mock_auth),
        ):
            result = auth_mod._sync_local_password_for_email("a@b.com", "newpass")
            assert result == 1


class TestJitCreateLocalUserForEnterprise:
    def test_user_exists_returns_false(self, auth_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = auth_mod._jit_create_local_user_for_enterprise("existing", "pass")
            assert result is False

    def test_creates_new_user(self, auth_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.utils.password_hash.generate_password_hash", return_value="hash"),
            patch("app.utils.time.utc_now_naive"),
        ):
            result = auth_mod._jit_create_local_user_for_enterprise("newuser", "pass", "e@e.com")
            assert result is True

    def test_db_error_returns_false(self, auth_mod):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(side_effect=RuntimeError("db fail"))
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = auth_mod._jit_create_local_user_for_enterprise("u", "p")
            assert result is False


class TestEnrichRegisterWithTenant:
    def test_no_user_id_returns_unchanged(self, auth_mod):
        result = auth_mod._enrich_register_with_tenant(
            result={}, username="u", session_id=None, sku="personal"
        )
        assert result == {}

    def test_with_tenant(self, auth_mod):
        with (
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": 1, "tenant_name": "T"},
            ),
            patch("app.application.session_account_meta.persist_session_account_meta"),
        ):
            result = auth_mod._enrich_register_with_tenant(
                result={"user": {"id": 1}}, username="u", session_id="sid", sku="enterprise"
            )
            assert result.get("tenant_id") == 1

    def test_tenant_error_handled(self, auth_mod):
        with patch(
            "app.application.enterprise_login_flow.bind_tenant_for_login",
            side_effect=RuntimeError("fail"),
        ):
            result = auth_mod._enrich_register_with_tenant(
                result={"user": {"id": 1}}, username="u", session_id=None, sku="personal"
            )
            assert "tenant_id" not in result


class TestSessionMetaForResponse:
    def test_no_session_id(self, auth_mod):
        mock_req = MagicMock()
        # routes.py binds session_id_from_request via ``from ... import`` at
        # module load, so the patch must target the binding in routes, not the
        # origin module — otherwise the real function runs and, when a DB is
        # active in the full suite, load_session_account_meta receives a
        # MagicMock sid and raises sqlite3.ProgrammingError.
        with patch(
            "app.fastapi_routes.domains.auth.routes.session_id_from_request", return_value=None
        ):
            result = auth_mod._session_meta_for_response(mock_req)
            assert result == {}

    def test_with_user(self, auth_mod):
        mock_req = MagicMock()
        mock_user = MagicMock()
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
            result = auth_mod._session_meta_for_response(mock_req, mock_user)
            assert result["account_kind"] == "enterprise"

    def test_without_user(self, auth_mod):
        mock_req = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "personal"},
            ),
        ):
            result = auth_mod._session_meta_for_response(mock_req, None)
            assert result["account_kind"] == "personal"

    def test_without_user_no_meta(self, auth_mod):
        mock_req = MagicMock()
        with (
            patch(
                "app.fastapi_routes.domains.auth.routes.session_id_from_request",
                return_value="sid-1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta", return_value=None
            ),
        ):
            result = auth_mod._session_meta_for_response(mock_req, None)
            assert result == {}
