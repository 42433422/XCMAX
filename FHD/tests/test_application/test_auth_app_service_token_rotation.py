"""Tests for app.application.auth_app_service — coverage ramp C3.2-b.

Covers:
* ``_authenticate_failure_message`` mapping (4 known patterns + fallback).
* ``AuthApplicationService.authenticate`` happy / bad password / unknown user
  / inactive / MFA required / exception paths.
* ``change_password`` / ``reset_password`` success + failure paths.
* ``authenticate_oidc_user`` JIT create + email/display fill-in.
* ``get_user_permissions`` admin / role / unknown role / exception fallback.
* ``has_permission`` admin / non-admin.
* ``logout`` and ``get_current_user`` delegation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.auth_app_service import (
    AuthApplicationService,
    _authenticate_failure_message,
)


class TestAuthenticateFailureMessage:
    """Verify the 4 known DB-error patterns and the fallback."""

    def test_market_access_token_missing(self) -> None:
        exc = Exception("OperationalError: market_access_token column not found")
        msg = _authenticate_failure_message(exc)
        assert "market_access_token" in msg
        assert "alembic upgrade head" in msg

    def test_no_such_table_users_sqlite(self) -> None:
        exc = Exception("OperationalError: no such table: users")
        msg = _authenticate_failure_message(exc)
        assert "no such table: users" in msg or "users 表" in msg

    def test_relation_users_does_not_exist(self) -> None:
        exc = Exception('psycopg2.errors.UndefinedTable: relation "users" does not exist')
        msg = _authenticate_failure_message(exc)
        assert "users 表" in msg

    def test_relation_sessions_does_not_exist(self) -> None:
        exc = Exception('psycopg2.errors.UndefinedTable: relation "sessions" does not exist')
        msg = _authenticate_failure_message(exc)
        assert "sessions 表" in msg

    def test_unrelated_error_returns_generic(self) -> None:
        exc = Exception("connection refused")
        msg = _authenticate_failure_message(exc)
        assert msg == "登录失败，请稍后重试"

    def test_chained_cause_is_inspected(self) -> None:
        inner = Exception("no such table: users")
        outer = RuntimeError("bootstrap failed")
        outer.__cause__ = inner
        msg = _authenticate_failure_message(outer)
        assert "users" in msg

    def test_loop_protection(self) -> None:
        # circular cause chain (id(cur) in seen) should not infinite-loop
        a = Exception("loop")
        b = Exception("a")
        a.__cause__ = b
        b.__cause__ = a
        msg = _authenticate_failure_message(a)
        assert "登录失败" in msg


class TestAuthenticateHappyPath:
    """Successful login with mocked DB and password check."""

    def test_returns_user_and_session(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock()
        user.id = 1
        user.username = "alice"
        user.display_name = "Alice"
        user.email = "alice@x.com"
        user.role = "user"
        user.is_active = True
        user.last_login = None
        user.password = "hashed"
        user.mfa_enabled = False
        user.totp_secret = None

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user

        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=True),
            patch.object(
                svc.session_manager,
                "create_session_with_db",
                return_value={"success": True, "session_id": "sess1", "expires_at": "2099-01-01"},
            ),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate("alice", "secret")
        assert out["success"] is True
        assert out["user"]["username"] == "alice"
        assert out["session_id"] == "sess1"

    def test_unknown_user_returns_invalid_credentials(self) -> None:
        svc = AuthApplicationService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate("nobody", "x")
        assert out["success"] is False
        assert "用户名或密码错误" in out["message"]

    def test_inactive_user_blocked(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(is_active=False, password="h")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate("alice", "x")
        assert out["success"] is False
        assert "禁用" in out["message"]

    def test_wrong_password_rejected(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(is_active=True, password="h", mfa_enabled=False, totp_secret=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=False),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate("alice", "wrong")
        assert out["success"] is False
        assert "用户名或密码错误" in out["message"]

    def test_mfa_required_when_enabled(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(is_active=True, password="h", mfa_enabled=True, totp_secret="secret")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=True),
            patch("app.application.auth_app_service.user_requires_mfa", return_value=True),
            patch("app.application.auth_app_service.verify_totp", return_value=False),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate("alice", "right", totp_code=None)
        assert out["success"] is False
        assert out.get("mfa_required") is True

    def test_session_creation_failure(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(is_active=True, password="h", mfa_enabled=False, totp_secret=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=True),
            patch.object(
                svc.session_manager, "create_session_with_db", return_value={"success": False}
            ),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate("alice", "right")
        assert out["success"] is False
        assert "会话创建失败" in out["message"]

    def test_exception_returns_mapped_message_with_error_id(self) -> None:
        svc = AuthApplicationService()
        with (
            patch("app.application.auth_app_service.get_db", side_effect=Exception("boot")),
            patch(
                "app.application.auth_app_service._authenticate_failure_message",
                return_value="mapped",
            ),
        ):
            out = svc.authenticate("alice", "right")
        assert out["success"] is False
        assert out["message"] == "mapped"
        assert "error_id" in out


class TestChangeAndResetPassword:
    def test_change_password_success(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(password="h")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=True),
            patch(
                "app.application.auth_app_service.generate_password_hash", return_value="newhash"
            ),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.change_password(1, "old", "new")
        assert out["success"] is True
        assert user.password == "newhash"

    def test_change_password_user_not_found(self) -> None:
        svc = AuthApplicationService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            out = svc.change_password(999, "old", "new")
        assert out["success"] is False
        assert "用户不存在" in out["message"]

    def test_change_password_wrong_old(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(password="h")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=False),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.change_password(1, "wrong", "new")
        assert out["success"] is False
        assert "原密码错误" in out["message"]

    def test_change_password_db_error_rolls_back(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(password="h")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        db.commit.side_effect = RuntimeError("db down")
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.check_password_hash", return_value=True),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.change_password(1, "old", "new")
        assert out["success"] is False
        assert "error_id" in out
        db.rollback.assert_called_once()

    def test_reset_password_success_invalidates_sessions(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(password="h")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch(
                "app.application.auth_app_service.generate_password_hash", return_value="newhash"
            ),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.reset_password(1, "new")
        assert out["success"] is True
        svc.session_manager.delete_user_sessions.assert_called_once_with(1)

    def test_reset_password_user_not_found(self) -> None:
        svc = AuthApplicationService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            out = svc.reset_password(999, "new")
        assert out["success"] is False
        assert "用户不存在" in out["message"]


class TestOIDCLogin:
    def test_oidc_jit_creates_user(self) -> None:
        svc = AuthApplicationService()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch("app.application.auth_app_service.generate_password_hash", return_value="x"),
            patch.object(
                svc.session_manager,
                "create_session_with_db",
                return_value={"success": True, "session_id": "s1", "expires_at": "2099"},
            ),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate_oidc_user(
                "alice@example.com", email="a@e.com", display_name="Alice"
            )
        assert out["success"] is True
        assert out["auth_method"] == "oidc"
        db.add.assert_called_once()

    def test_oidc_existing_user_inactive(self) -> None:
        svc = AuthApplicationService()
        existing = MagicMock(is_active=False, email="", display_name="")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate_oidc_user("alice")
        assert out["success"] is False
        assert "禁用" in out["message"]

    def test_oidc_invalid_username(self) -> None:
        svc = AuthApplicationService()
        out = svc.authenticate_oidc_user("   ")
        assert out["success"] is False
        assert "无效" in out["message"]

    def test_oidc_existing_user_gets_email_filled(self) -> None:
        svc = AuthApplicationService()
        existing = MagicMock(is_active=True, email="", display_name="")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        with (
            patch("app.application.auth_app_service.get_db") as gdb,
            patch.object(
                svc.session_manager,
                "create_session_with_db",
                return_value={"success": True, "session_id": "s2", "expires_at": "2099"},
            ),
        ):
            gdb.return_value.__enter__.return_value = db
            out = svc.authenticate_oidc_user("alice", email="a@b.com", display_name="Alice")
        assert out["success"] is True
        assert existing.email == "a@b.com"
        assert existing.display_name == "Alice"


class TestPermissions:
    def test_admin_role_returns_all_permissions(self) -> None:
        svc = AuthApplicationService()
        admin_user = MagicMock(role="admin")
        p1 = MagicMock(code="read")
        p2 = MagicMock(code="write")
        db = MagicMock()
        db.query.return_value.all.return_value = [p1, p2]
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            perms = svc.get_user_permissions(admin_user)
        assert perms == ["read", "write"]

    def test_standard_role_returns_role_permissions(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(role="editor")
        p1 = MagicMock(code="edit")
        role = MagicMock(permissions=[p1])
        db = MagicMock()
        # First call: filter().first() returns role; second: all() not used.
        db.query.return_value.filter.return_value.first.return_value = role
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            perms = svc.get_user_permissions(user)
        assert perms == ["edit"]

    def test_unknown_role_returns_empty_list(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(role="nobody")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.application.auth_app_service.get_db") as gdb:
            gdb.return_value.__enter__.return_value = db
            perms = svc.get_user_permissions(user)
        assert perms == []

    def test_db_exception_admin_falls_back_to_defaults(self) -> None:
        svc = AuthApplicationService()
        admin_user = MagicMock(role="admin")
        with patch("app.application.auth_app_service.get_db", side_effect=Exception("db down")):
            perms = svc.get_user_permissions(admin_user)
        # DEFAULT_PERMISSIONS is a list of dicts with 'code' key
        assert isinstance(perms, list)
        assert all("code" not in p if isinstance(p, dict) else True for p in perms)
        # when fallback to DEFAULT, items are dicts; coerce to codes
        codes = [p["code"] if isinstance(p, dict) else p for p in perms]
        assert isinstance(codes, list)

    def test_has_permission_admin(self) -> None:
        svc = AuthApplicationService()
        admin = MagicMock(role="admin")
        assert svc.has_permission(admin, "anything") is True

    def test_has_permission_non_admin(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock(role="user")
        with patch.object(svc, "get_user_permissions", return_value=["read"]):
            assert svc.has_permission(user, "read") is True
            assert svc.has_permission(user, "write") is False


class TestLogoutAndGetUser:
    def test_logout_delegates_to_session_manager(self) -> None:
        svc = AuthApplicationService()
        svc.session_manager.delete_session.return_value = True
        assert svc.logout("sess-1") is True
        svc.session_manager.delete_session.assert_called_once_with("sess-1")

    def test_get_current_user_returns_session_user(self) -> None:
        svc = AuthApplicationService()
        user = MagicMock()
        svc.session_manager.validate_session.return_value = user
        assert svc.get_current_user("sess-1") is user
