"""Extended tests for app.fastapi_routes.domains.auth.routes — helper functions and validation paths."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def auth_mod():
    from app.fastapi_routes.domains.auth import routes
    return routes


# ---------------------------------------------------------------------------
# _open_registration_allowed
# ---------------------------------------------------------------------------


class TestOpenRegistrationAllowed:
    def test_explicit_false(self, auth_mod, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "0")
        assert auth_mod._open_registration_allowed("generic") is False

    def test_explicit_true(self, auth_mod, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "1")
        assert auth_mod._open_registration_allowed("enterprise") is True

    def test_env_no_enterprise_allowed(self, auth_mod, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
        assert auth_mod._open_registration_allowed("generic") is True

    def test_env_no_enterprise_blocked(self, auth_mod, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_OPEN_REGISTRATION", raising=False)
        assert auth_mod._open_registration_allowed("enterprise") is False

    def test_false_variants(self, auth_mod, monkeypatch):
        for val in ("false", "no"):
            monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", val)
            assert auth_mod._open_registration_allowed("generic") is False

    def test_true_variants(self, auth_mod, monkeypatch):
        for val in ("true", "yes"):
            monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", val)
            assert auth_mod._open_registration_allowed("enterprise") is True


# ---------------------------------------------------------------------------
# _normalize_auth_email
# ---------------------------------------------------------------------------


class TestNormalizeAuthEmail:
    def test_normalizes(self, auth_mod):
        assert auth_mod._normalize_auth_email("  Test@Example.COM  ") == "test@example.com"

    def test_none_returns_empty(self, auth_mod):
        assert auth_mod._normalize_auth_email(None) == ""

    def test_empty_string(self, auth_mod):
        assert auth_mod._normalize_auth_email("") == ""


# ---------------------------------------------------------------------------
# _market_user_email_from_raw
# ---------------------------------------------------------------------------


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

    def test_data_no_user(self, auth_mod):
        assert auth_mod._market_user_email_from_raw({"data": {}}) == ""

    def test_data_user_no_email(self, auth_mod):
        assert auth_mod._market_user_email_from_raw({"data": {"user": {"name": "test"}}}) == ""


# ---------------------------------------------------------------------------
# _user_public_dict
# ---------------------------------------------------------------------------


class TestUserPublicDict:
    def test_basic_fields(self, auth_mod):
        user = MagicMock()
        user.id = 1
        user.username = "admin"
        user.display_name = "Admin"
        user.email = "admin@test.com"
        user.role = "admin"
        user.is_active = True
        user.wx_avatar_url = None
        with patch("app.utils.user_avatar_storage.public_avatar_url", return_value="/avatar/default.png"):
            result = auth_mod._user_public_dict(user)
        assert result["id"] == 1
        assert result["username"] == "admin"
        assert result["role"] == "admin"

    def test_with_avatar(self, auth_mod):
        user = MagicMock()
        user.id = 2
        user.username = "user2"
        user.display_name = "User 2"
        user.email = "u2@test.com"
        user.role = "user"
        user.is_active = True
        user.wx_avatar_url = "https://example.com/av.jpg"
        with patch("app.utils.user_avatar_storage.public_avatar_url", return_value="https://example.com/av.jpg"):
            result = auth_mod._user_public_dict(user)
        assert result["avatar_url"] == "https://example.com/av.jpg"


# ---------------------------------------------------------------------------
# _session_meta_for_response
# ---------------------------------------------------------------------------


class TestSessionMetaForResponse:
    def test_no_session_id(self, auth_mod):
        req = MagicMock()
        # routes.py binds session_id_from_request via ``from ... import`` at
        # module load, so patch the binding in routes, not the origin module;
        # otherwise the real fn runs and hits the DB with a MagicMock sid.
        with patch("app.fastapi_routes.domains.auth.routes.session_id_from_request", return_value=None):
            result = auth_mod._session_meta_for_response(req)
        assert result == {}

    def test_with_user(self, auth_mod):
        req = MagicMock()
        user = MagicMock()
        with patch("app.fastapi_routes.domains.auth.routes.session_id_from_request", return_value="sid1"), \
             patch("app.application.session_account_meta.enrich_session_meta_with_tenant", return_value={"account_kind": "enterprise"}):
            result = auth_mod._session_meta_for_response(req, user)
        assert result["account_kind"] == "enterprise"

    def test_without_user(self, auth_mod):
        req = MagicMock()
        with patch("app.fastapi_routes.domains.auth.routes.session_id_from_request", return_value="sid1"), \
             patch("app.application.session_account_meta.load_session_account_meta", return_value={"account_kind": "personal"}):
            result = auth_mod._session_meta_for_response(req)
        assert result["account_kind"] == "personal"

    def test_without_user_no_meta(self, auth_mod):
        req = MagicMock()
        with patch("app.fastapi_routes.domains.auth.routes.session_id_from_request", return_value="sid1"), \
             patch("app.application.session_account_meta.load_session_account_meta", return_value=None):
            result = auth_mod._session_meta_for_response(req)
        assert result == {}


# ---------------------------------------------------------------------------
# _attach_session_cookie
# ---------------------------------------------------------------------------


class TestAttachSessionCookie:
    def test_empty_session_id(self, auth_mod):
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={"ok": True})
        result = auth_mod._attach_session_cookie(resp, "")
        assert result is resp

    def test_none_session_id(self, auth_mod):
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={"ok": True})
        result = auth_mod._attach_session_cookie(resp, None)
        assert result is resp

    def test_sets_cookie(self, auth_mod, monkeypatch):
        from fastapi.responses import JSONResponse

        monkeypatch.setenv("SESSION_COOKIE_NAME", "test_session")
        resp = JSONResponse(content={"ok": True})
        result = auth_mod._attach_session_cookie(resp, "sid123")
        assert result is resp


# ---------------------------------------------------------------------------
# _enrich_register_with_tenant
# ---------------------------------------------------------------------------


class TestEnrichRegisterWithTenant:
    def test_no_user_id_returns_unchanged(self, auth_mod):
        result = auth_mod._enrich_register_with_tenant(
            result={"user": {}},
            username="test",
            session_id="sid1",
            sku="generic",
        )
        assert result == {"user": {}}

    def test_tenant_binding_success(self, auth_mod):
        with patch("app.application.enterprise_login_flow.bind_tenant_for_login", return_value={
            "tenant_id": 1, "tenant_name": "TestCo"
        }), patch("app.application.session_account_meta.persist_session_account_meta"):
            result = auth_mod._enrich_register_with_tenant(
                result={"user": {"id": 1}},
                username="test",
                session_id="sid1",
                sku="enterprise",
            )
        assert result["tenant_id"] == 1
        assert result["tenant_name"] == "TestCo"

    def test_infra_transient_returns_unchanged(self, auth_mod):
        with patch("app.application.enterprise_login_flow.bind_tenant_for_login", side_effect=RuntimeError("db down")):
            result = auth_mod._enrich_register_with_tenant(
                result={"user": {"id": 1}},
                username="test",
                session_id="sid1",
                sku="enterprise",
            )
        assert "tenant_id" not in result


# ---------------------------------------------------------------------------
# _jit_create_local_user_for_enterprise
# ---------------------------------------------------------------------------


class TestJitCreateLocalUser:
    def test_user_already_exists(self, auth_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = auth_mod._jit_create_local_user_for_enterprise("existing", "pass")
        assert result is False

    def test_create_success(self, auth_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db), \
             patch("app.utils.password_hash.generate_password_hash", return_value="hashed"):
            result = auth_mod._jit_create_local_user_for_enterprise("newuser", "pass", "e@e.com")
        assert result is True

    def test_infra_transient_returns_false(self, auth_mod):
        mock_db = MagicMock()
        mock_db.query.side_effect = RuntimeError("db down")
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = auth_mod._jit_create_local_user_for_enterprise("user", "pass")
        assert result is False


# ---------------------------------------------------------------------------
# _find_local_users_by_email
# ---------------------------------------------------------------------------


class TestFindLocalUsersByEmail:
    def test_invalid_email_returns_empty(self, auth_mod):
        assert auth_mod._find_local_users_by_email("") == []
        assert auth_mod._find_local_users_by_email("no-at-sign") == []

    def test_valid_email_queries(self, auth_mod):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.__enter__ = lambda s: mock_db
        mock_db.__exit__ = MagicMock(return_value=False)
        with patch("app.db.session.get_db", return_value=mock_db):
            result = auth_mod._find_local_users_by_email("test@example.com")
        assert result == []


# ---------------------------------------------------------------------------
# _sync_local_password_for_email
# ---------------------------------------------------------------------------


class TestSyncLocalPasswordForEmail:
    def test_no_users_returns_zero(self, auth_mod):
        with patch.object(auth_mod, "_find_local_users_by_email", return_value=[]):
            result = auth_mod._sync_local_password_for_email("a@b.com", "newpass")
        assert result == 0

    def test_updates_matching_users(self, auth_mod):
        user1 = MagicMock()
        user1.id = 1
        mock_auth = MagicMock()
        mock_auth.reset_password.return_value = {"success": True}
        with patch.object(auth_mod, "_find_local_users_by_email", return_value=[user1]), \
             patch("app.application.auth_app_service.get_auth_app_service", return_value=mock_auth):
            result = auth_mod._sync_local_password_for_email("a@b.com", "newpass")
        assert result == 1


# ---------------------------------------------------------------------------
# runtime_product_sku
# ---------------------------------------------------------------------------


class TestRuntimeProductSku:
    def test_returns_sku(self, auth_mod):
        with patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="enterprise"):
            result = auth_mod.runtime_product_sku()
        assert result["success"] is True
        assert result["data"]["sku"] == "enterprise"
        assert result["data"]["is_enterprise_edition"] is True

    def test_generic_sku(self, auth_mod):
        with patch("app.mod_sdk.product_skus.resolve_product_sku", return_value=None):
            result = auth_mod.runtime_product_sku()
        assert result["data"]["sku"] == "generic"
        assert result["data"]["is_enterprise_edition"] is False
