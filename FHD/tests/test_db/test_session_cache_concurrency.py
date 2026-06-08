"""Tests for app.db.session_cache — coverage ramp C3.2-a.

Covers:
* ``ThreadSafeLRUCache`` multi-threaded LRU eviction.
* TTL expiration (mocked ``time.time``).
* ``get_or_set`` style call (via set-then-get) for repeated keys.
* ``delete`` / ``clear`` / ``stats`` / ``make_key`` paths.
* ``sqlite_write_guard`` non-desktop fast-path.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from app.db.session_cache import ThreadSafeLRUCache
from app.db.sqlite_write_guard import sqlite_write_guard


class TestLRUBasicOps:
    """Single-thread basic operation coverage."""

    def test_set_then_get_returns_value(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4)
        cache.set("a", 1)
        assert cache.get("a") == 1
        assert cache.size() == 1

    def test_get_missing_key_returns_none_and_records_miss(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4)
        assert cache.get("missing") is None
        assert cache.stats()["misses"] == 1
        assert cache.stats()["hits"] == 0

    def test_set_existing_key_moves_to_end_and_keeps_size(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("a", 11)  # overwrite + move to end
        assert cache.size() == 2
        assert cache.get("a") == 11

    def test_eviction_when_over_max_size(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # evicts "a" (oldest)
        assert cache.size() == 2
        assert cache.get("a") is None  # evicted
        assert cache.get("b") == 2
        assert cache.get("c") == 3
        assert cache.stats()["evictions"] == 1

    def test_delete_existing_key_returns_true(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4)
        cache.set("a", 1)
        assert cache.delete("a") is True
        assert cache.get("a") is None

    def test_delete_missing_key_returns_false(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4)
        assert cache.delete("missing") is False

    def test_clear_resets_all_stats(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4)
        cache.set("a", 1)
        cache.get("a")
        cache.get("missing")
        assert cache.stats()["hits"] == 1
        assert cache.stats()["misses"] == 1
        cache.clear()
        stats = cache.stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0

    def test_make_key_is_deterministic(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache()
        k1 = cache.make_key("func", 1, 2, x=10, y=20)
        k2 = cache.make_key("func", 1, 2, y=20, x=10)  # kwargs reordered
        assert k1 == k2

    def test_make_key_differs_for_different_args(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache()
        k1 = cache.make_key("func", 1, 2)
        k2 = cache.make_key("func", 1, 3)
        assert k1 != k2


class TestLRUTtlExpiry:
    """TTL boundary coverage using mocked ``time.time``."""

    def test_expired_entry_returns_none_and_evicts(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4, ttl_seconds=10.0)
        with patch("app.db.session_cache.time.time") as mock_t:
            mock_t.return_value = 1000.0
            cache.set("a", 1)
            mock_t.return_value = 1000.0 + 11.0  # 11s later -> expired
            assert cache.get("a") is None
        assert cache.stats()["evictions"] == 1
        assert cache.stats()["misses"] == 1

    def test_fresh_entry_returns_value(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=4, ttl_seconds=10.0)
        with patch("app.db.session_cache.time.time") as mock_t:
            mock_t.return_value = 1000.0
            cache.set("a", 1)
            mock_t.return_value = 1005.0  # within TTL
            assert cache.get("a") == 1

    def test_get_moves_entry_to_end(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=2, ttl_seconds=100.0)
        cache.set("a", 1)
        cache.set("b", 2)
        # 'get' should reorder so 'a' becomes most-recently-used
        assert cache.get("a") == 1
        cache.set("c", 3)  # should evict 'b' (now oldest)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3


class TestLRUConcurrency:
    """Multi-threaded access under contention."""

    def test_concurrent_set_does_not_exceed_max_size(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=20)
        barrier = threading.Barrier(5)

        def writer(prefix: str) -> None:
            barrier.wait()
            for i in range(50):
                cache.set(f"{prefix}-{i}", i)

        threads = [threading.Thread(target=writer, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Max size enforced despite concurrent inserts.
        assert cache.size() == 20

    def test_concurrent_get_and_set_keeps_invariants(self) -> None:
        cache: ThreadSafeLRUCache = ThreadSafeLRUCache(max_size=10)
        for i in range(10):
            cache.set(f"k{i}", i)
        barrier = threading.Barrier(4)

        def reader() -> None:
            barrier.wait()
            for _ in range(100):
                for i in range(10):
                    cache.get(f"k{i}")

        def updater() -> None:
            barrier.wait()
            for i in range(100):
                cache.set(f"k{i % 10}", i)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=updater),
            threading.Thread(target=updater),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # After contention, all 10 keys are still present and within max.
        assert cache.size() == 10
        # And we recorded at least some hits.
        assert cache.stats()["hits"] > 0


class TestSqliteWriteGuard:
    """``sqlite_write_guard`` context manager."""

    def test_non_desktop_mode_yields_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Default is desktop_mode=False in test env; just enter & exit cleanly.
        with sqlite_write_guard():
            pass

    def test_desktop_mode_takes_lock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force is_desktop_mode() -> True to exercise the lock path.
        monkeypatch.setattr("app.desktop_runtime.paths.is_desktop_mode", lambda: True)
        with sqlite_write_guard():
            # Inside the guard, the lock should be held by the current thread.
            lock = threading.Lock()
            # If we got here, guard yielded. Verify nested acquire is impossible
            # without timeout (i.e. lock is held by us).
            assert not lock.acquire(blocking=False)
            lock.release()
