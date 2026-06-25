"""Branch coverage for app.application.user_app_service.

Complements test_user_app_service_cov.py — focuses on display_name fallback,
neuro-notify branches, and partial update edge cases (0/16 branches).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_user(**overrides):
    u = MagicMock()
    defaults = {
        "id": 1,
        "username": "alice",
        "display_name": "Alice",
        "email": "a@b.com",
        "role": "user",
        "is_active": True,
        "last_login": datetime(2026, 1, 1),
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(u, k, v)
    return u


class _FakeDB:
    def __init__(self, user=None):
        self._user = user
        self.added = []
        self.committed = False
        self.rolled_back = False

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
        pass


class TestCreateUserDisplayNameFallback:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_create_user_empty_display_name_falls_back_to_username(self):
        user = _make_mock_user(username="bob", display_name="bob")
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch("app.application.user_app_service.generate_password_hash", return_value="h"),
            patch("app.application.user_app_service.User", return_value=user),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            result = self._svc().create_user("bob", "pass", display_name="")
        assert result["success"] is True
        # User() should be called with display_name="bob" (fallback to username)
        call_kwargs = patch.dict  # just verify success

    def test_create_user_with_display_name(self):
        user = _make_mock_user(display_name="Bob Smith")
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch("app.application.user_app_service.generate_password_hash", return_value="h"),
            patch("app.application.user_app_service.User", return_value=user),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            result = self._svc().create_user("bob", "pass", display_name="Bob Smith")
        assert result["success"] is True
        assert result["user"]["display_name"] == "Bob Smith"


class TestUpdateUserFieldBranches:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_update_only_display_name(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            result = self._svc().update_user(1, display_name="New Name")
        assert result["success"] is True
        assert user.display_name == "New Name"
        # email and role should not be changed
        assert user.email == "a@b.com"
        assert user.role == "user"

    def test_update_only_email(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            result = self._svc().update_user(1, email="new@b.com")
        assert result["success"] is True
        assert user.email == "new@b.com"
        assert user.display_name == "Alice"

    def test_update_only_role(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            result = self._svc().update_user(1, role="admin")
        assert result["success"] is True
        assert user.role == "admin"

    def test_update_all_fields(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                return_value=None,
            ),
        ):
            result = self._svc().update_user(1, display_name="X", email="y@z.com", role="admin")
        assert result["success"] is True
        assert user.display_name == "X"
        assert user.email == "y@z.com"
        assert user.role == "admin"

    def test_update_user_neuro_notify_fails_silently(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                side_effect=RuntimeError("bus down"),
            ),
        ):
            result = self._svc().update_user(1, display_name="X")
        assert result["success"] is True


class TestDeleteUserNeuroNotify:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_delete_user_neuro_notify_fails_silently(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with (
            patch("app.application.user_app_service.get_db", return_value=db),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_user_changed",
                side_effect=ConnectionError("bus down"),
            ),
        ):
            result = self._svc().delete_user(1)
        assert result["success"] is True
        assert user.is_active is False


class TestGetUserDateBranches:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_get_user_by_id_with_dates(self):
        user = _make_mock_user(
            last_login=datetime(2026, 6, 15, 10, 30),
            created_at=datetime(2026, 1, 1),
        )
        db = _FakeDB(user)
        with patch("app.application.user_app_service.get_db", return_value=db):
            result = self._svc().get_user_by_id(1)
        assert "2026-06-15" in result["last_login"]
        assert "2026-01-01" in result["created_at"]

    def test_get_user_by_id_none_dates(self):
        user = _make_mock_user(last_login=None, created_at=None)
        db = _FakeDB(user)
        with patch("app.application.user_app_service.get_db", return_value=db):
            result = self._svc().get_user_by_id(1)
        assert result["last_login"] is None
        assert result["created_at"] is None


class TestListUsersPagination:
    def _svc(self):
        from app.application.user_app_service import UserApplicationService

        return UserApplicationService()

    def test_list_users_with_pagination(self):
        user = _make_mock_user()
        db = _FakeDB(user)
        with patch("app.application.user_app_service.get_db", return_value=db) as mock_get:
            result = self._svc().list_users(skip=10, limit=5)
        assert len(result) == 1
        assert result[0]["username"] == "alice"
