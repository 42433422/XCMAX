"""Branch coverage for app.infrastructure.auth.dependencies small helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.auth.dependencies import (
    CurrentUser,
    _allow_x_user_id_header,
    _write_lock_enabled,
    get_current_user,
    get_logged_in_user,
    require_admin_user,
    require_identified_user,
    require_permission,
    resolve_session_user,
    session_id_from_request,
)


def _req(*, headers=None, cookies=None):
    request = MagicMock()
    request.headers = headers or {}
    request.cookies = cookies or {}
    return request


class TestWriteLockAndAllowHeader:
    def test_write_lock_enabled_default(self, monkeypatch):
        monkeypatch.delenv("FHD_DISABLE_DB_WRITE_LOCK", raising=False)
        assert _write_lock_enabled() is True

    def test_write_lock_disabled_variants(self, monkeypatch):
        for v in ("1", "true", "YES", "on"):
            monkeypatch.setenv("FHD_DISABLE_DB_WRITE_LOCK", v)
            assert _write_lock_enabled() is False

    def test_allow_x_user_id_header(self, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
        assert _allow_x_user_id_header() is False
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "true")
        assert _allow_x_user_id_header() is True


class TestCurrentUser:
    def test_is_identified_and_repr(self):
        u = CurrentUser(user_id=7, raw_header="7")
        assert u.is_identified is True
        assert "7" in repr(u)
        assert CurrentUser(None).is_identified is False


class TestSessionIdFromRequest:
    def test_prefers_x_session_id(self):
        req = _req(headers={"X-Session-ID": "  sid-a  ", "Authorization": "Bearer jwt"})
        assert session_id_from_request(req) == "sid-a"

    def test_bearer_fallback(self):
        req = _req(headers={"Authorization": "Bearer tok-1"})
        assert session_id_from_request(req) == "tok-1"

    def test_cookie_fallback(self):
        req = _req(cookies={"session_id": " cookie-sid "})
        with patch(
            "app.infrastructure.auth.client_shell_session.session_cookie_name_for_request",
            return_value="session_id",
        ):
            assert session_id_from_request(req) == "cookie-sid"

    def test_empty(self):
        req = _req()
        with patch(
            "app.infrastructure.auth.client_shell_session.session_cookie_name_for_request",
            return_value="session_id",
        ):
            assert session_id_from_request(req) == ""


class TestResolveSessionUser:
    def test_no_sid_returns_none(self):
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="",
        ):
            assert resolve_session_user(_req()) is None

    def test_valid_session(self):
        user = SimpleNamespace(id=1)
        svc = MagicMock()
        svc.validate_session.return_value = user
        with (
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="s1",
            ),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=svc,
            ),
        ):
            assert resolve_session_user(_req()) is user

    def test_jwt_fallback(self):
        svc = MagicMock()
        svc.validate_session.return_value = None
        jwt_user = SimpleNamespace(id=9)
        with (
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="jwt",
            ),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=svc,
            ),
            patch(
                "app.security.web_jwt.resolve_user_from_web_jwt",
                return_value=jwt_user,
            ),
        ):
            assert resolve_session_user(_req()) is jwt_user

    def test_jwt_import_error_returns_none(self):
        svc = MagicMock()
        svc.validate_session.return_value = None
        import builtins

        real_import = builtins.__import__

        def _imp(name, *a, **k):
            if name == "app.security.web_jwt" or (
                isinstance(name, str) and name.startswith("app.security.web_jwt")
            ):
                raise ImportError("no jwt")
            return real_import(name, *a, **k)

        with (
            patch(
                "app.infrastructure.auth.dependencies.session_id_from_request",
                return_value="jwt",
            ),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=svc,
            ),
            patch("builtins.__import__", side_effect=_imp),
        ):
            assert resolve_session_user(_req()) is None


class TestGetCurrentUser:
    def test_from_session(self):
        user = SimpleNamespace(id=3)
        req = _req()
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ):
            cu = get_current_user(req, x_user_id="99")
        assert cu.user_id == 3
        assert cu.raw_header == "99"

    def test_x_user_id_when_allowed(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        req = _req()
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ):
            cu = get_current_user(req, x_user_id="42")
        assert cu.user_id == 42

    def test_x_user_id_invalid_digits(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        req = _req()
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ):
            cu = get_current_user(req, x_user_id="not-a-number")
        assert cu.user_id is None

    def test_x_user_id_int_raises_value_error(self, monkeypatch):
        """isdigit passes but int() raises → uid stays None (lines 56-57)."""
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        req = _req()
        real_int = int

        def _int_maybe(v, *a, **k):
            if isinstance(v, str) and v.strip() == "42":
                raise ValueError("forced")
            return real_int(v, *a, **k)

        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
            patch("builtins.int", side_effect=_int_maybe),
        ):
            cu = get_current_user(req, x_user_id="42")
        assert cu.user_id is None

    def test_no_header_fallback_when_disallowed(self, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
        req = _req()
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ):
            cu = get_current_user(req, x_user_id="42")
        assert cu.user_id is None


class TestRequireIdentifiedUser:
    def test_401_when_unidentified_and_lock_on(self, monkeypatch):
        monkeypatch.delenv("FHD_DISABLE_DB_WRITE_LOCK", raising=False)
        req = _req()
        with patch(
            "app.infrastructure.auth.dependencies.get_current_user",
            return_value=CurrentUser(None),
        ):
            with pytest.raises(HTTPException) as ei:
                require_identified_user(req)
        assert ei.value.status_code == 401

    def test_passes_when_lock_disabled(self, monkeypatch):
        monkeypatch.setenv("FHD_DISABLE_DB_WRITE_LOCK", "1")
        req = _req()
        with patch(
            "app.infrastructure.auth.dependencies.get_current_user",
            return_value=CurrentUser(None),
        ):
            cu = require_identified_user(req)
        assert cu.user_id is None


class TestGetLoggedInUser:
    def test_401_when_missing(self):
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as ei:
                get_logged_in_user(_req())
        assert ei.value.status_code == 401

    def test_403_when_inactive(self):
        user = SimpleNamespace(id=1, is_active=False)
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ):
            with pytest.raises(HTTPException) as ei:
                get_logged_in_user(_req())
        assert ei.value.status_code == 403

    def test_ok(self):
        user = SimpleNamespace(id=1, is_active=True)
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ):
            assert get_logged_in_user(_req()) is user


class TestRequirePermission:
    def test_forbidden(self):
        user = SimpleNamespace(id=1, is_active=True)
        auth = MagicMock()
        auth.has_permission.return_value = False
        dep = require_permission("admin:x")
        with (
            patch(
                "app.infrastructure.auth.dependencies.get_logged_in_user",
                return_value=user,
            ),
            patch(
                "app.application.facades.session_facade.get_auth_service",
                return_value=auth,
            ),
        ):
            with pytest.raises(HTTPException) as ei:
                dep(_req())
        assert ei.value.status_code == 403

    def test_ok(self):
        user = SimpleNamespace(id=1, is_active=True)
        auth = MagicMock()
        auth.has_permission.return_value = True
        dep = require_permission("admin:x")
        with (
            patch(
                "app.infrastructure.auth.dependencies.get_logged_in_user",
                return_value=user,
            ),
            patch(
                "app.application.facades.session_facade.get_auth_service",
                return_value=auth,
            ),
        ):
            assert dep(_req()) is user


class TestRequireAdminUser:
    def test_non_admin_403(self):
        user = SimpleNamespace(id=1, is_active=True, tier="personal")
        with patch(
            "app.infrastructure.auth.dependencies.get_logged_in_user",
            return_value=user,
        ):
            with pytest.raises(HTTPException) as ei:
                require_admin_user(_req())
        assert ei.value.status_code == 403

    def test_admin_ok(self):
        user = SimpleNamespace(id=1, is_active=True, tier="admin")
        with patch(
            "app.infrastructure.auth.dependencies.get_logged_in_user",
            return_value=user,
        ):
            assert require_admin_user(_req()) is user
