"""app/utils/error_handling 单测：结构化错误装饰器与 DB 错误映射。"""

from __future__ import annotations

import pytest

from app.errors import (
    AppError,
    DatabaseLockError,
    ErrorCode,
    ForeignKeyViolationError,
    ModAccessDeniedError,
    WorkflowError,
)
from app.utils.error_handling import (
    DEFAULT_RETRY_ATTEMPTS,
    handle_database_error,
    is_database_locked_error,
    with_error_handling,
    with_sqlite_retry,
)


class TestWithErrorHandling:
    def test_success_passthrough(self):
        @with_error_handling()
        def ok():
            return {"success": True}

        assert ok() == {"success": True}

    def test_import_error(self):
        @with_error_handling(error_code_prefix="x_")
        def boom():
            raise ImportError("no mod")

        out = boom()
        assert out["success"] is False
        assert out["error_code"] == "x_service_unavailable"

    def test_validation_error(self):
        @with_error_handling()
        def bad():
            raise ValueError("bad field")

        out = bad()
        assert out["success"] is False
        assert "validation_error" in out["error_code"]

    def test_database_lock(self):
        @with_error_handling()
        def locked():
            raise DatabaseLockError("busy")

        out = locked()
        assert out["error_code"].endswith("database_busy")

    def test_foreign_key(self):
        @with_error_handling()
        def fk():
            raise ForeignKeyViolationError("fk")

        out = fk()
        assert "fk_violation" in out["error_code"]

    def test_mod_access_denied(self):
        @with_error_handling()
        def denied():
            raise ModAccessDeniedError("nope")

        out = denied()
        assert "access_denied" in out["error_code"]

    def test_app_error_uses_code(self):
        @with_error_handling()
        def app_err():
            raise AppError(ErrorCode.INTERNAL_ERROR, "oops")

        out = app_err()
        assert out["error_code"] == ErrorCode.INTERNAL_ERROR.value

    def test_workflow_error(self):
        @with_error_handling(error_code_prefix="wf_")
        def wf():
            raise WorkflowError(message="plan failed")

        out = wf()
        assert out["error_code"] == ErrorCode.WORKFLOW_ERROR.value

    def test_unexpected_error(self):
        @with_error_handling()
        def boom():
            raise RuntimeError("boom")

        out = boom()
        assert out["error_code"].endswith("unexpected_error")

    def test_reraise_tuple(self):
        @with_error_handling(reraise=(ValueError,))
        def bad():
            raise ValueError("x")

        with pytest.raises(ValueError):
            bad()

    def test_fallback_called(self):
        def fb(*_a, **_k):
            return {"fallback": True}

        @with_error_handling(fallback=fb)
        def bad():
            raise TypeError("t")

        assert bad() == {"fallback": True}


class TestWithSqliteRetry:
    def test_succeeds_first_try(self, monkeypatch):
        monkeypatch.setattr("app.utils.error_handling.time.sleep", lambda _s: None)

        @with_sqlite_retry(max_attempts=3, base_delay=0.01, backoff=1.0)
        def ok():
            return 42

        assert ok() == 42

    def test_retries_then_raises(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr("app.utils.error_handling.time.sleep", lambda _s: None)

        @with_sqlite_retry(max_attempts=2, base_delay=0.01, backoff=1.0)
        def flaky():
            calls["n"] += 1
            raise DatabaseLockError("locked")

        with pytest.raises(DatabaseLockError, match="after 2 attempts"):
            flaky()
        assert calls["n"] == 2

    def test_non_retryable_propagates(self):
        @with_sqlite_retry(max_attempts=3)
        def boom():
            raise RuntimeError("x")

        with pytest.raises(RuntimeError):
            boom()


class TestDatabaseHelpers:
    def test_is_database_locked_error(self):
        assert is_database_locked_error(Exception("database is locked")) is True
        assert is_database_locked_error(Exception("other")) is False

    def test_handle_database_locked(self):
        out = handle_database_error(Exception("database is locked"), "insert")
        assert out["error_code"] == "database_locked"
        assert out["retryable"] is True

    def test_handle_foreign_key(self):
        out = handle_database_error(Exception("FOREIGN KEY constraint failed"))
        assert out["error_code"] == "foreign_key_violation"

    def test_handle_duplicate(self):
        out = handle_database_error(Exception("UNIQUE constraint failed: duplicate"))
        assert out["error_code"] == "duplicate_error"

    def test_handle_generic(self):
        out = handle_database_error(Exception("weird"), "select")
        assert out["error_code"] == "database_error"

    def test_defaults_constants(self):
        assert DEFAULT_RETRY_ATTEMPTS == 3
