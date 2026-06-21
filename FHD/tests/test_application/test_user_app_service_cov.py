from __future__ import annotations

"""Branch coverage for app/application/user_app_service.py."""

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest


def _make_mock_user(
    user_id=1,
    username="alice",
    display_name="Alice",
    email="a@b.com",
    role="user",
    is_active=True,
    last_login=None,
    created_at=None,
):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.display_name = display_name
    u.email = email
    u.role = role
    u.is_active = is_active
    u.last_login = last_login
    u.created_at = created_at
    return u


class _FakeDB:
    """Context-manager DB mock that exposes query/add/commit/rollback/refresh."""

    def __init__(self, user=None):
        self._user = user
        self.committed = False
        self.rolled_back = False
        self.added = []
        self._refreshed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, model):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return self._user

    def offset(self, n):
        return self

    def limit(self, n):
        return self

    def all(self):
        return [self._user] if self._user else []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, obj):
        self._refreshed.append(obj)


class TestUserApplicationServiceGetUser:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_get_user_by_id_found(self):
        user = _make_mock_user(last_login=datetime(2026, 1, 1), created_at=datetime(2026, 1, 1))
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(user)):
            result = svc.get_user_by_id(1)
        assert result is not None
        assert result["username"] == "alice"
        assert "2026" in result["last_login"]
        assert "2026" in result["created_at"]

    def test_get_user_by_id_no_dates(self):
        user = _make_mock_user(last_login=None, created_at=None)
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(user)):
            result = svc.get_user_by_id(1)
        assert result["last_login"] is None
        assert result["created_at"] is None

    def test_get_user_by_id_not_found(self):
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(None)):
            result = svc.get_user_by_id(999)
        assert result is None

    def test_get_user_by_username_found(self):
        user = _make_mock_user()
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(user)):
            result = svc.get_user_by_username("alice")
        assert result is not None
        assert result["username"] == "alice"

    def test_get_user_by_username_not_found(self):
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(None)):
            result = svc.get_user_by_username("ghost")
        assert result is None


class TestUserApplicationServiceListUsers:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_list_users(self):
        user = _make_mock_user()
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(user)):
            result = svc.list_users()
        assert len(result) == 1
        assert result[0]["username"] == "alice"

    def test_list_users_empty(self):
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(None)):
            result = svc.list_users()
        assert result == []


class TestUserApplicationServiceCreate:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_create_user_success(self):
        db = _FakeDB()
        created_user = _make_mock_user()
        # After db.add + commit + refresh the user object should be available
        # We simulate by assigning it to db._user so that refresh works
        db._user = created_user

        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch("app.application.user_app_service.generate_password_hash", return_value="hashed"),
            patch("app.application.user_app_service.User") as MockUser,
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            MockUser.return_value = created_user
            svc = self._svc()
            result = svc.create_user("alice", "password123")
        assert result["success"] is True

    def test_create_user_db_error(self):
        class FailDB(_FakeDB):
            def commit(self):
                raise RuntimeError("DB fail")

        db = FailDB()
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch("app.application.user_app_service.generate_password_hash", return_value="h"),
            patch("app.application.user_app_service.User", return_value=_make_mock_user()),
        ):
            svc = self._svc()
            result = svc.create_user("alice", "pass")
        assert result["success"] is False

    def test_create_user_neuro_notify_fails_silently(self):
        created_user = _make_mock_user()
        db = _FakeDB()
        db._user = created_user

        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch("app.application.user_app_service.generate_password_hash", return_value="h"),
            patch("app.application.user_app_service.User", return_value=created_user),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                side_effect=RuntimeError("bus down"),
            ),
        ):
            svc = self._svc()
            result = svc.create_user("alice", "pass")
        # neuro error is swallowed — create should still succeed
        assert result["success"] is True


class TestUserApplicationServiceUpdate:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_update_user_not_found(self):
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(None)):
            result = svc.update_user(999)
        assert result["success"] is False

    def test_update_user_success(self):
        user = _make_mock_user()
        db = _FakeDB(user)

        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            svc = self._svc()
            result = svc.update_user(1, display_name="Bob", email="b@c.com", role="admin")
        assert result["success"] is True
        assert user.display_name == "Bob"
        assert user.email == "b@c.com"
        assert user.role == "admin"

    def test_update_user_partial(self):
        user = _make_mock_user()
        db = _FakeDB(user)

        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            svc = self._svc()
            result = svc.update_user(1)  # no fields → only existing values kept
        assert result["success"] is True

    def test_update_user_db_error(self):
        class FailDB(_FakeDB):
            def commit(self):
                raise RuntimeError("error")

        user = _make_mock_user()
        with (
            patch("app.application.user_app_service.get_db", return_value=FailDB(user)),
        ):
            svc = self._svc()
            result = svc.update_user(1, display_name="X")
        assert result["success"] is False


class TestUserApplicationServiceDelete:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_delete_user_not_found(self):
        svc = self._svc()
        with patch("app.application.user_app_service.get_db", return_value=_FakeDB(None)):
            result = svc.delete_user(999)
        assert result["success"] is False

    def test_delete_user_success(self):
        user = _make_mock_user()
        db = _FakeDB(user)

        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            svc = self._svc()
            result = svc.delete_user(1)
        assert result["success"] is True
        assert user.is_active is False

    def test_delete_user_db_error(self):
        class FailDB(_FakeDB):
            def commit(self):
                raise RuntimeError("fail")

        user = _make_mock_user()
        with (
            patch("app.application.user_app_service.get_db", return_value=FailDB(user)),
        ):
            svc = self._svc()
            result = svc.delete_user(1)
        assert result["success"] is False


class TestGetUserAppServiceSingleton:
    def test_singleton(self):
        import app.application.user_app_service as mod

        mod._user_app_service = None  # reset
        from app.application.user_app_service import get_user_app_service

        s1 = get_user_app_service()
        s2 = get_user_app_service()
        assert s1 is s2
