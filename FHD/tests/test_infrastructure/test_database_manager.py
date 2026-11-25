"""Branch coverage for app.infrastructure.database.database_manager.

Covers sqlite vs postgresql engine init, session lifecycle, singleton (0/6 branches).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

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


@pytest.fixture
def transaction_manager(tmp_path):
    manager = dm.DatabaseManager(database_url=f"sqlite:///{tmp_path / 'transaction.sqlite3'}")
    with manager.get_engine().begin() as connection:
        connection.exec_driver_sql("CREATE TABLE entries (value TEXT)")
    try:
        yield manager
    finally:
        manager.dispose()


class TestGetSession:
    def test_session_commit_on_success(self, transaction_manager):
        with transaction_manager.get_session() as session:
            session.execute(text("INSERT INTO entries VALUES ('committed')"))
        with transaction_manager.get_engine().connect() as independent_reader:
            assert independent_reader.execute(text("SELECT value FROM entries")).all() == [
                ("committed",)
            ]
        assert session.in_transaction() is False

    @pytest.mark.parametrize(
        "failure",
        [OSError, KeyError, IndexError, TypeError, AttributeError, RuntimeError, AssertionError],
    )
    def test_failure_rolls_back_and_propagates(self, transaction_manager, failure):
        error = failure("injected failure after writing")
        with pytest.raises(failure) as caught:
            with transaction_manager.get_session() as session:
                session.execute(text("INSERT INTO entries VALUES ('uncommitted')"))
                raise error
        assert caught.value is error
        with transaction_manager.get_engine().connect() as independent_reader:
            assert independent_reader.execute(text("SELECT count(*) FROM entries")).scalar() == 0
        assert session.in_transaction() is False


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
