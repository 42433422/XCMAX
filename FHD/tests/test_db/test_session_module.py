"""Tests for app.db.session query cache and get_db lifecycle."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing, contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, String, Table, create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, registry

from app import db as db_module
from app.db import session as session_mod


def test_query_cache_roundtrip():
    session_mod.clear_query_cache()
    key = session_mod.make_cache_key("fn", 1, page=2)
    session_mod.set_cached_query(key, {"success": True})
    assert session_mod.get_cached_query(key) == {"success": True}
    session_mod.clear_query_cache()
    assert session_mod.get_cached_query(key) is None


def test_timed_query_decorator_runs():
    @session_mod.timed_query("unit-test-query")
    def _work():
        return 42

    assert _work() == 42


def test_get_db_commits_on_success():
    mock_db = MagicMock()

    with patch.object(session_mod, "SessionLocal", return_value=mock_db):
        with session_mod.get_db() as db:
            assert db is mock_db
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


def test_get_db_rolls_back_on_error():
    mock_db = MagicMock()

    with patch.object(session_mod, "SessionLocal", return_value=mock_db):
        with pytest.raises(RuntimeError):
            with session_mod.get_db():
                raise RuntimeError("boom")
    mock_db.rollback.assert_called_once()
    mock_db.close.assert_called_once()


def test_get_db_dependency_yields_session():
    mock_db = MagicMock()

    with patch.object(session_mod, "SessionLocal", return_value=mock_db):
        gen = session_mod.get_db_dependency()
        db = next(gen)
        assert db is mock_db
        gen.close()
    mock_db.close.assert_called_once()


@pytest.fixture(params=["get_db", "get_host_db", "get_db_dependency"])
def sql_session_scope(request, tmp_path, monkeypatch):
    database = tmp_path / "session-transactions.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE entries (value TEXT UNIQUE)")
    session = Session(engine)
    monkeypatch.setattr(session_mod, "SessionLocal", lambda: session)
    monkeypatch.setattr(db_module, "HostSessionLocal", lambda: session)
    scope = getattr(session_mod, request.param)
    if request.param == "get_db_dependency":
        scope = contextmanager(scope)
    try:
        yield scope, session, engine, database
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    "failure",
    [
        OSError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        asyncio.CancelledError,
    ],
)
def test_session_failure_discards_writes_and_preserves_error(sql_session_scope, failure):
    scope, session, engine, database = sql_session_scope
    error = failure("failure after writing")
    with pytest.raises(failure) as caught:
        with scope() as db:
            db.execute(text("INSERT INTO entries VALUES ('uncommitted')"))
            raise error
    assert caught.value is error
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT count(*) FROM entries").fetchone() == (0,)


def test_session_success_commits_and_closes(sql_session_scope):
    scope, session, engine, database = sql_session_scope
    with scope() as db:
        db.execute(text("INSERT INTO entries VALUES ('committed')"))
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT value FROM entries").fetchall() == [("committed",)]


@pytest.mark.parametrize("hook", ["before_commit", "after_commit"])
def test_session_commit_hook_failure_preserves_error_and_closes(sql_session_scope, hook):
    scope, session, engine, database = sql_session_scope
    error = TypeError("commit hook failed")

    def fail_commit(_session):
        raise error

    event.listen(session, hook, fail_commit)
    with pytest.raises(TypeError) as caught:
        with scope() as db:
            db.execute(text("INSERT INTO entries VALUES ('uncommitted')"))
    assert caught.value is error
    assert getattr(error, "__notes__", []) == []
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT count(*) FROM entries").fetchone() == (
            int(hook == "after_commit"),
        )


def test_session_failed_flush_closes_the_partial_rollback(sql_session_scope):
    scope, session, engine, database = sql_session_scope
    mapping = registry()

    @mapping.mapped
    class Entry:
        __table__ = Table("entries", mapping.metadata, Column("value", String, primary_key=True))

    try:
        with pytest.raises(IntegrityError) as caught:
            with scope() as db:
                db.add_all([Entry(value="duplicate"), Entry(value="duplicate")])
                try:
                    db.flush()
                except IntegrityError:
                    assert db.is_active is False
                    assert db.in_transaction() is True
                    raise
        assert isinstance(caught.value.orig, sqlite3.IntegrityError)
        assert session.in_transaction() is False
        assert engine.pool.checkedout() == 0
        with closing(sqlite3.connect(database)) as reader:
            assert reader.execute("SELECT count(*) FROM entries").fetchone() == (0,)
    finally:
        mapping.dispose()


def test_session_failure_rolls_back_a_joined_transaction(sql_session_scope, monkeypatch):
    scope, _, engine, database = sql_session_scope
    error = TypeError("invalid database update")
    with engine.connect() as connection, connection.begin() as transaction:
        session = Session(connection, join_transaction_mode="rollback_only")
        monkeypatch.setattr(session_mod, "SessionLocal", lambda: session)
        monkeypatch.setattr(db_module, "HostSessionLocal", lambda: session)
        with pytest.raises(TypeError) as caught:
            with scope() as db:
                db.execute(text("INSERT INTO entries VALUES ('must be rolled back')"))
                raise error
        assert caught.value is error
        assert transaction.is_active is False
        assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT count(*) FROM entries").fetchone() == (0,)


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_session_cleanup_failure_preserves_original_error(sql_session_scope, failure):
    scope, session, engine, _ = sql_session_scope
    error = failure("original task failure")
    original_close = session.close

    def close_then_fail():
        original_close()
        raise OSError("close unavailable")

    with (
        patch.object(session, "rollback", side_effect=OSError("rollback unavailable")) as rollback,
        patch.object(session, "close", side_effect=close_then_fail) as close,
        patch.object(session, "commit", wraps=session.commit) as commit,
    ):
        with pytest.raises(failure) as caught:
            with scope() as db:
                db.execute(text("INSERT INTO entries VALUES ('uncommitted')"))
                raise error
        assert caught.value is error
        assert error.__notes__ == [
            "SQL session rollback failed: OSError('rollback unavailable')",
            "SQL session close failed: OSError('close unavailable')",
        ]
        rollback.assert_called_once_with()
        close.assert_called_once_with()
        commit.assert_not_called()
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0


def test_session_close_failure_without_original_error_propagates(sql_session_scope):
    scope, session, engine, database = sql_session_scope
    error = OSError("close unavailable")
    original_close = session.close

    def close_then_fail():
        original_close()
        raise error

    with patch.object(session, "close", side_effect=close_then_fail) as close:
        with pytest.raises(OSError) as caught:
            with scope() as db:
                db.execute(text("INSERT INTO entries VALUES ('committed')"))
        assert caught.value is error
        close.assert_called_once_with()
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT value FROM entries").fetchall() == [("committed",)]
