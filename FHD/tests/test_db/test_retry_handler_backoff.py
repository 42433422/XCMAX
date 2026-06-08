"""Tests for app.db.retry_handler — coverage ramp C3.2-a.

Covers:
* ``is_database_locked_error`` recognition (str / type / mixed).
* ``with_sqlite_retry`` decorator: success path, lock retry, non-lock re-raise,
  exhaustion, ``on_retry`` callback (incl. callback that raises), and
  ``reraise_original=True`` flag.
* ``execute_with_retry`` function: same paths, dynamic invocation.
* ``safe_commit`` happy path.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.db.retry_handler import (
    execute_with_retry,
    is_database_locked_error,
    safe_commit,
    with_sqlite_retry,
)


class TestIsDatabaseLockedError:
    """String and exception-type recognition."""

    def test_message_database_is_locked(self) -> None:
        err = sqlite3.OperationalError("database is locked")
        assert is_database_locked_error(err) is True

    def test_message_database_locked(self) -> None:
        err = Exception("database locked for write")
        assert is_database_locked_error(err) is True

    def test_type_name_contains_operationalerror(self) -> None:
        err = sqlite3.OperationalError("some unrelated message")
        assert is_database_locked_error(err) is True

    def test_unrelated_error_returns_false(self) -> None:
        err = ValueError("not a db error")
        assert is_database_locked_error(err) is False

    def test_indicator_in_message(self) -> None:
        err = RuntimeError("connection locked by another tx")
        assert is_database_locked_error(err) is True

    def test_str_with_locked_keyword(self) -> None:
        err = Exception("table is locked")
        assert is_database_locked_error(err) is True


class TestWithSqliteRetry:
    """``with_sqlite_retry`` decorator behavior."""

    def test_success_first_attempt_does_not_sleep(self) -> None:
        sleep_calls: list[float] = []

        def fake_sleep(s: float) -> None:
            sleep_calls.append(s)

        @with_sqlite_retry(max_attempts=3, base_delay=0.5, backoff=2.0)
        def good_op() -> str:
            return "ok"

        with patch("app.db.retry_handler.time.sleep", side_effect=fake_sleep):
            assert good_op() == "ok"
        assert sleep_calls == []

    def test_locked_error_retries_with_exponential_backoff(self) -> None:
        sleep_calls: list[float] = []
        attempts: list[int] = []

        def fake_sleep(s: float) -> None:
            sleep_calls.append(s)

        @with_sqlite_retry(max_attempts=3, base_delay=0.5, backoff=2.0)
        def flaky_op() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise sqlite3.OperationalError("database is locked")
            return "recovered"

        with patch("app.db.retry_handler.time.sleep", side_effect=fake_sleep):
            assert flaky_op() == "recovered"

        assert len(attempts) == 3
        # First retry: 0.5, second retry: 1.0 (0.5 * 2.0)
        assert sleep_calls == [0.5, 1.0]

    def test_non_lock_error_reraises_immediately(self) -> None:
        attempts: list[int] = []

        @with_sqlite_retry(max_attempts=3, base_delay=0.5, backoff=2.0)
        def bad_op() -> str:
            attempts.append(1)
            raise ValueError("not a lock error")

        with patch("app.db.retry_handler.time.sleep") as mock_sleep:
            with pytest.raises(ValueError, match="not a lock error"):
                bad_op()
        assert len(attempts) == 1
        mock_sleep.assert_not_called()

    def test_exhausted_retries_raises_runtime_error(self) -> None:
        @with_sqlite_retry(max_attempts=2, base_delay=0.1, backoff=2.0)
        def always_locked() -> str:
            raise sqlite3.OperationalError("database is locked")

        with patch("app.db.retry_handler.time.sleep"):
            with pytest.raises(RuntimeError, match="Database is locked after 2 retry attempts"):
                always_locked()

    def test_exhausted_with_reraise_original_returns_original_error(self) -> None:
        original = sqlite3.OperationalError("database is locked")

        @with_sqlite_retry(max_attempts=2, base_delay=0.1, reraise_original=True)
        def always_locked() -> str:
            raise original

        with patch("app.db.retry_handler.time.sleep"):
            with pytest.raises(sqlite3.OperationalError):
                always_locked()

    def test_on_retry_callback_invoked_with_error_and_attempt(self) -> None:
        seen: list[tuple[Exception, int]] = []

        @with_sqlite_retry(
            max_attempts=3,
            base_delay=0.01,
            on_retry=lambda err, n: seen.append((err, n)),
        )
        def flaky() -> str:
            if len(seen) < 2:
                raise sqlite3.OperationalError("database is locked")
            return "done"

        with patch("app.db.retry_handler.time.sleep"):
            assert flaky() == "done"
        assert len(seen) == 2
        assert seen[0][1] == 1
        assert seen[1][1] == 2

    def test_on_retry_callback_exception_is_swallowed(self) -> None:
        def broken_cb(err: Exception, attempt: int) -> None:
            raise RuntimeError("callback boom")

        @with_sqlite_retry(
            max_attempts=3,
            base_delay=0.01,
            on_retry=broken_cb,
        )
        def flaky() -> str:
            if not hasattr(flaky, "called"):
                flaky.called = True  # type: ignore[attr-defined]
                raise sqlite3.OperationalError("database is locked")
            return "ok"

        with patch("app.db.retry_handler.time.sleep"):
            assert flaky() == "ok"

    def test_max_attempts_zero_calls_function_once(self) -> None:
        attempts: list[int] = []

        @with_sqlite_retry(max_attempts=0, base_delay=0.5)
        def op() -> str:
            attempts.append(1)
            return "once"

        with patch("app.db.retry_handler.time.sleep"):
            assert op() == "once"
        assert len(attempts) == 1


class TestExecuteWithRetry:
    """Non-decorator entry point."""

    def test_success_returns_value(self) -> None:
        op = MagicMock(return_value=42)
        with patch("app.db.retry_handler.time.sleep"):
            assert execute_with_retry(op, max_attempts=3) == 42
        op.assert_called_once()

    def test_locked_retries_with_backoff(self) -> None:
        sleeps: list[float] = []
        op = MagicMock(side_effect=[sqlite3.OperationalError("locked"), "ok"])
        with patch("app.db.retry_handler.time.sleep", side_effect=lambda s: sleeps.append(s)):
            assert execute_with_retry(op, max_attempts=3, base_delay=0.5, backoff=2.0) == "ok"
        assert sleeps == [0.5]

    def test_non_lock_reraises(self) -> None:
        op = MagicMock(side_effect=ValueError("nope"))
        with patch("app.db.retry_handler.time.sleep") as mock_sleep:
            with pytest.raises(ValueError):
                execute_with_retry(op)
        mock_sleep.assert_not_called()

    def test_exhausted_raises_runtime(self) -> None:
        op = MagicMock(side_effect=sqlite3.OperationalError("locked"))
        with patch("app.db.retry_handler.time.sleep"):
            with pytest.raises(RuntimeError, match="Database is locked after 1 retry attempts"):
                execute_with_retry(op, max_attempts=1)


class TestSafeCommit:
    """``safe_commit`` wraps session.commit with retry."""

    def test_commit_success(self) -> None:
        session = MagicMock()
        session.commit.return_value = None
        with patch("app.db.retry_handler.time.sleep"):
            safe_commit(session, max_attempts=3)
        session.commit.assert_called_once_with()

    def test_commit_locked_retries(self) -> None:
        session = MagicMock()
        session.commit.side_effect = [
            sqlite3.OperationalError("database is locked"),
            None,
        ]
        with patch("app.db.retry_handler.time.sleep"):
            safe_commit(session, max_attempts=3)
        assert session.commit.call_count == 2

    def test_commit_exhausted_raises(self) -> None:
        session = MagicMock()
        session.commit.side_effect = sqlite3.OperationalError("database is locked")
        with patch("app.db.retry_handler.time.sleep"), pytest.raises(RuntimeError):
            safe_commit(session, max_attempts=2)
