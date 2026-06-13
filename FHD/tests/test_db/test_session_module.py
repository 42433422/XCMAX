"""Tests for app.db.session query cache and get_db lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
