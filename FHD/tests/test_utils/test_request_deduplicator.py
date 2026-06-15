"""app/utils/request_deduplicator 测试。"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.utils.request_deduplicator import (
    DedupRecord,
    RequestDeduplicator,
    deduplicate_request,
    get_request_deduplicator,
    idempotent_operation,
)


# ---------------------------------------------------------------------------
# DedupRecord
# ---------------------------------------------------------------------------


class TestDedupRecord:
    def test_default_values(self):
        record = DedupRecord(key="test")
        assert record.key == "test"
        assert record.result is None
        assert record.timestamp > 0
        assert record.is_processing is False
        assert record.waiters == []


# ---------------------------------------------------------------------------
# _make_key
# ---------------------------------------------------------------------------


class TestMakeKey:
    def test_generates_hash(self):
        dedup = RequestDeduplicator()
        key = dedup._make_key("func_name", "arg1", key1="val1")
        assert isinstance(key, str)
        assert len(key) == 32

    def test_deterministic(self):
        dedup = RequestDeduplicator()
        key1 = dedup._make_key("func", "a")
        key2 = dedup._make_key("func", "a")
        assert key1 == key2

    def test_different_args_different_key(self):
        dedup = RequestDeduplicator()
        key1 = dedup._make_key("func", "a")
        key2 = dedup._make_key("func", "b")
        assert key1 != key2

    def test_object_with_dict(self):
        dedup = RequestDeduplicator()

        class Obj:
            def __init__(self):
                self.__dict__ = {"x": 1}

        key = dedup._make_key("func", Obj())
        assert isinstance(key, str)


# ---------------------------------------------------------------------------
# _cleanup_expired
# ---------------------------------------------------------------------------


class TestCleanupExpired:
    def test_removes_expired(self):
        dedup = RequestDeduplicator(window_seconds=1)
        dedup._records["old"] = DedupRecord(key="old", timestamp=time.time() - 10)
        dedup._records["new"] = DedupRecord(key="new", timestamp=time.time())
        count = dedup._cleanup_expired()
        assert count == 1
        assert "old" not in dedup._records
        assert "new" in dedup._records

    def test_no_expired(self):
        dedup = RequestDeduplicator(window_seconds=3600)
        dedup._records["key"] = DedupRecord(key="key", timestamp=time.time())
        count = dedup._cleanup_expired()
        assert count == 0


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------


class TestDeduplicate:
    def test_first_call_executes(self):
        dedup = RequestDeduplicator()
        call_count = 0

        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        is_dup, result = dedup.deduplicate(my_func, 5)
        assert is_dup is False
        assert result == 10
        assert call_count == 1

    def test_duplicate_call_returns_cached(self):
        dedup = RequestDeduplicator(window_seconds=60)
        call_count = 0

        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        dedup.deduplicate(my_func, 5)
        is_dup, result = dedup.deduplicate(my_func, 5)
        assert is_dup is True
        assert result == 10
        assert call_count == 1

    def test_duplicate_without_cache(self):
        dedup = RequestDeduplicator(window_seconds=60)
        call_count = 0

        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        dedup.deduplicate(my_func, 5, cache_result=True)
        is_dup, result = dedup.deduplicate(my_func, 5, use_cache=False)
        assert is_dup is True
        assert result is None

    def test_no_cache_result(self):
        dedup = RequestDeduplicator(window_seconds=60)

        def my_func(x):
            return x * 2

        is_dup, result = dedup.deduplicate(my_func, 5, cache_result=False)
        assert is_dup is False
        assert result == 10
        # Record should be deleted since cache_result=False
        assert len(dedup._records) == 0

    def test_exception_removes_record(self):
        dedup = RequestDeduplicator()

        def my_func():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            dedup.deduplicate(my_func)
        assert len(dedup._records) == 0

    def test_max_keys_eviction(self):
        dedup = RequestDeduplicator(max_keys=2)

        def my_func(x):
            return x

        dedup.deduplicate(my_func, 1)
        dedup.deduplicate(my_func, 2)
        dedup.deduplicate(my_func, 3)
        assert len(dedup._records) <= 2


# ---------------------------------------------------------------------------
# check_and_wait
# ---------------------------------------------------------------------------


class TestCheckAndWait:
    def test_first_call_executes(self):
        dedup = RequestDeduplicator()

        def my_func(x):
            return x * 2

        is_dup, result = dedup.check_and_wait(my_func, 5)
        assert is_dup is False
        assert result == 10

    def test_exception_removes_record(self):
        dedup = RequestDeduplicator()

        def my_func():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            dedup.check_and_wait(my_func)
        assert len(dedup._records) == 0


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    def test_invalidate_specific_key(self):
        dedup = RequestDeduplicator()

        def my_func(x):
            return x

        dedup.deduplicate(my_func, 5)
        count = dedup.invalidate(my_func, 5)
        assert count == 1
        assert len(dedup._records) == 0

    def test_invalidate_nonexistent_key(self):
        dedup = RequestDeduplicator()

        def my_func(x):
            return x

        count = dedup.invalidate(my_func, 5)
        assert count == 0

    def test_invalidate_all(self):
        dedup = RequestDeduplicator()

        def my_func(x):
            return x

        dedup.deduplicate(my_func, 1)
        dedup.deduplicate(my_func, 2)
        count = dedup.invalidate()
        assert count == 2
        assert len(dedup._records) == 0


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty_stats(self):
        dedup = RequestDeduplicator()
        stats = dedup.stats
        assert stats["total_requests"] == 0
        assert stats["dedup_rate"] == 0.0
        assert stats["active_records"] == 0

    def test_stats_after_requests(self):
        dedup = RequestDeduplicator(window_seconds=60)

        def my_func(x):
            return x

        dedup.deduplicate(my_func, 1)
        dedup.deduplicate(my_func, 1)  # duplicate
        stats = dedup.stats
        assert stats["total_requests"] == 2
        assert stats["deduplicated"] == 1
        assert stats["dedup_rate"] == 50.0

    def test_reset_stats(self):
        dedup = RequestDeduplicator()

        def my_func(x):
            return x

        dedup.deduplicate(my_func, 1)
        dedup.reset_stats()
        stats = dedup.stats
        assert stats["total_requests"] == 0


# ---------------------------------------------------------------------------
# get_request_deduplicator
# ---------------------------------------------------------------------------


class TestGetRequestDeduplicator:
    def test_returns_instance(self):
        import app.utils.request_deduplicator as rd

        old = rd._deduplicator_instance
        rd._deduplicator_instance = None
        try:
            dedup = get_request_deduplicator()
            assert isinstance(dedup, RequestDeduplicator)
        finally:
            rd._deduplicator_instance = old


# ---------------------------------------------------------------------------
# deduplicate_request decorator
# ---------------------------------------------------------------------------


class TestDeduplicateRequestDecorator:
    def test_decorates_function(self):
        call_count = 0

        @deduplicate_request(window_seconds=60)
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = my_func(5)
        result2 = my_func(5)  # duplicate
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1


# ---------------------------------------------------------------------------
# idempotent_operation decorator
# ---------------------------------------------------------------------------


class TestIdempotentOperationDecorator:
    def test_decorates_function(self):
        import app.utils.request_deduplicator as rd
        # Reset the global deduplicator to avoid state from other tests
        rd._deduplicator_instance = None
        call_count = 0

        @idempotent_operation(lambda x: f"op:{x}", ttl=60)
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 3

        result1 = my_func(5)
        assert result1 == 15
        assert call_count == 1
        # Second call with same args is deduplicated
        result2 = my_func(5)
        assert result2 == 15
        assert call_count == 1  # still 1 because deduplicated
        rd._deduplicator_instance = None

    def test_without_key_func(self):
        import app.utils.request_deduplicator as rd
        rd._deduplicator_instance = None

        @idempotent_operation(ttl=60)
        def my_func(x):
            return x * 2

        result = my_func(5)
        assert result == 10
        rd._deduplicator_instance = None
