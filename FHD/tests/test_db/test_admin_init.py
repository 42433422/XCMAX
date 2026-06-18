"""Tests for app.db.admin_init — admin user initialization."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestInitUserDb:
    def test_init_user_db_returns_true(self):
        mock_session = MagicMock()
        mock_session.execute = MagicMock(return_value=None)
        mock_session.commit = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("app.db.admin_init.SessionLocal", return_value=mock_session):
            from app.db.admin_init import init_user_db

            result = init_user_db()
        assert result is True
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestCreateAdminUser:
    def test_create_admin_user_already_exists(self):
        mock_session = MagicMock()
        mock_session.execute = MagicMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=(1,)))
        )
        mock_session.commit = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("app.db.admin_init.SessionLocal", return_value=mock_session):
            with patch("app.db.admin_init.init_user_db", return_value=True):
                from app.db.admin_init import create_admin_user

                result = create_admin_user(username="admin", password="pass123")
        assert result["success"] is True
        assert "已存在" in result["message"]

    def test_create_admin_user_creates_new(self):
        mock_session = MagicMock()
        # First call: SELECT finds no existing user
        # Second call: INSERT
        mock_session.execute = MagicMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),  # no existing user
                None,  # INSERT
            ]
        )
        mock_session.commit = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("app.db.admin_init.SessionLocal", return_value=mock_session):
            with patch("app.db.admin_init.init_user_db", return_value=True):
                with patch("app.db.admin_init.generate_password_hash", return_value="hashed_pw"):
                    from app.db.admin_init import create_admin_user

                    result = create_admin_user(
                        username="newadmin",
                        password="secret",
                        display_name="New Admin",
                        role="admin",
                    )
        assert result["success"] is True
        assert "已创建" in result["message"]
        # Verify INSERT was called
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    def test_create_admin_user_default_display_name(self):
        mock_session = MagicMock()
        mock_session.execute = MagicMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                None,
            ]
        )
        mock_session.commit = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("app.db.admin_init.SessionLocal", return_value=mock_session):
            with patch("app.db.admin_init.init_user_db", return_value=True):
                with patch("app.db.admin_init.generate_password_hash", return_value="hashed_pw"):
                    from app.db.admin_init import create_admin_user

                    result = create_admin_user(username="admin2", password="pw")
        assert result["success"] is True


class TestCreateAdminFromEnv:
    def test_create_admin_from_env_missing_username(self):
        with patch.dict(os.environ, {"ADMIN_USERNAME": "", "ADMIN_PASSWORD": "pw"}, clear=False):
            from app.db.admin_init import create_admin_from_env

            result = create_admin_from_env()
        assert result["success"] is False
        assert "缺少" in result["message"]

    def test_create_admin_from_env_missing_password(self):
        with patch.dict(os.environ, {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": ""}, clear=False):
            from app.db.admin_init import create_admin_from_env

            result = create_admin_from_env()
        assert result["success"] is False

    def test_create_admin_from_env_success(self):
        mock_session = MagicMock()
        mock_session.execute = MagicMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                None,
            ]
        )
        mock_session.commit = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "envadmin",
                "ADMIN_PASSWORD": "envpw",
                "ADMIN_DISPLAY_NAME": "Env Admin",
            },
            clear=False,
        ):
            with patch("app.db.admin_init.SessionLocal", return_value=mock_session):
                with patch("app.db.admin_init.init_user_db", return_value=True):
                    with patch("app.db.admin_init.generate_password_hash", return_value="hashed"):
                        from app.db.admin_init import create_admin_from_env

                        result = create_admin_from_env()
        assert result["success"] is True

    def test_create_admin_from_env_default_display_name(self):
        mock_session = MagicMock()
        mock_session.execute = MagicMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                None,
            ]
        )
        mock_session.commit = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        env = {"ADMIN_USERNAME": "admin3", "ADMIN_PASSWORD": "pw3"}
        with patch.dict(os.environ, env, clear=False):
            with patch("app.db.admin_init.SessionLocal", return_value=mock_session):
                with patch("app.db.admin_init.init_user_db", return_value=True):
                    with patch("app.db.admin_init.generate_password_hash", return_value="hashed"):
                        from app.db.admin_init import create_admin_from_env

                        result = create_admin_from_env()
        assert result["success"] is True
