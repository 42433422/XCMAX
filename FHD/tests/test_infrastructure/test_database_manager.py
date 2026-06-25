"""Branch coverage for app.infrastructure.database.database_manager.

Covers sqlite vs postgresql engine init, session lifecycle, singleton (0/6 branches).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.database import database_manager as dm


class TestDatabaseManagerInit:
    def test_init_with_sqlite_url(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine
            mgr = dm.DatabaseManager(database_url="sqlite:///./test.db")
            # sqlite branch uses StaticPool + check_same_thread
            assert mock_create.called
            kwargs = mock_create.call_args.kwargs
            assert kwargs["connect_args"] == {"check_same_thread": False}
            assert mgr.get_engine() is mock_engine

    def test_init_with_postgresql_url(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine
            mgr = dm.DatabaseManager(
                database_url="postgresql+psycopg://u:p@localhost:5432/db",
                pool_size=3,
                max_overflow=7,
            )
            kwargs = mock_create.call_args.kwargs
            assert kwargs["pool_size"] == 3
            assert kwargs["max_overflow"] == 7
            assert "connect_args" not in kwargs
            assert mgr.get_engine() is mock_engine

    def test_init_falls_back_to_env_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./env.db")
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = dm.DatabaseManager()
            assert "sqlite" in mock_create.call_args.args[0]

    def test_init_falls_back_to_default_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = dm.DatabaseManager()
            assert "postgresql" in mock_create.call_args.args[0]

    def test_get_session_factory(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = dm.DatabaseManager(database_url="sqlite:///./t.db")
            assert mgr.get_session_factory() is not None


class TestGetSession:
    def test_session_commit_on_success(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = dm.DatabaseManager(database_url="sqlite:///./t.db")
            mock_session = MagicMock()
            mgr._session_factory = MagicMock(return_value=mock_session)
            with mgr.get_session() as session:
                assert session is mock_session
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()

    def test_session_rollback_on_recoverable_error(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = dm.DatabaseManager(database_url="sqlite:///./t.db")
            mock_session = MagicMock()
            mgr._session_factory = MagicMock(return_value=mock_session)
            with pytest.raises(RuntimeError, match="boom"):
                with mgr.get_session():
                    raise RuntimeError("boom")
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()

    def test_session_close_on_unrecoverable_error(self):
        # Programming errors (not in RECOVERABLE_ERRORS) still close the session
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = dm.DatabaseManager(database_url="sqlite:///./t.db")
            mock_session = MagicMock()
            mgr._session_factory = MagicMock(return_value=mock_session)
            with pytest.raises(AssertionError):
                with mgr.get_session():
                    raise AssertionError("bug")
            # No rollback for non-recoverable, but session still closed
            mock_session.rollback.assert_not_called()
            mock_session.close.assert_called_once()


class TestDispose:
    def test_dispose_with_engine(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine
            mgr = dm.DatabaseManager(database_url="sqlite:///./t.db")
            mgr.dispose()
            mock_engine.dispose.assert_called_once()

    def test_dispose_without_engine(self):
        # Engine is None — dispose should not raise
        mgr = object.__new__(dm.DatabaseManager)
        mgr._engine = None
        mgr.dispose()  # no error


class TestSingletons:
    def test_get_database_manager_singleton(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            dm._database_manager = None
            m1 = dm.get_database_manager()
            m2 = dm.get_database_manager()
            assert m1 is m2

    def test_init_database_manager_overrides_singleton(self):
        with patch("app.infrastructure.database.database_manager.create_engine") as mock_create:
            mock_create.return_value = MagicMock()
            dm._database_manager = None
            dm.init_database_manager("sqlite:///./override.db")
            assert dm._database_manager is not None
            assert dm._database_manager._database_url == "sqlite:///./override.db"
