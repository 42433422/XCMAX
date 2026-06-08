"""Unit tests for ThreadSafeLRUCache (session_cache.py) — spec P0-1 checklist."""

from __future__ import annotations

import time

import pytest

from app.db.session_cache import ThreadSafeLRUCache


@pytest.fixture
def cache() -> ThreadSafeLRUCache:
    return ThreadSafeLRUCache(max_size=4, ttl_seconds=10.0)


# ---------------------------------------------------------------------------
# Basic get/set
# ---------------------------------------------------------------------------


def test_set_and_get(cache: ThreadSafeLRUCache) -> None:
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_get_missing_returns_none(cache: ThreadSafeLRUCache) -> None:
    assert cache.get("nonexistent") is None


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_ttl_expiry() -> None:
    short = ThreadSafeLRUCache(max_size=8, ttl_seconds=0.05)
    short.set("x", 42)
    assert short.get("x") == 42
    time.sleep(0.1)
    assert short.get("x") is None


def test_ttl_not_expired(cache: ThreadSafeLRUCache) -> None:
    cache.set("k", "fresh")
    assert cache.get("k") == "fresh"


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


def test_lru_eviction() -> None:
    c = ThreadSafeLRUCache(max_size=3)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    # Access a → a is most-recently-used
    c.get("a")
    # d evicts b (oldest non-accessed)
    c.set("d", 4)
    assert c.get("b") is None
    assert c.get("a") == 1
    assert c.get("c") == 3
    assert c.get("d") == 4


def test_capacity_limit(cache: ThreadSafeLRUCache) -> None:
    for i in range(6):
        cache.set(f"key{i}", i)
    assert cache.size() == 4  # max_size=4


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def test_clear(cache: ThreadSafeLRUCache) -> None:
    cache.set("k", "v")
    cache.clear()
    assert cache.size() == 0
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["evictions"] == 0
    assert cache.get("k") is None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_stats_tracking(cache: ThreadSafeLRUCache) -> None:
    cache.set("k", "v")
    cache.get("k")  # hit
    cache.get("missing")  # miss
    s = cache.stats()
    assert s["hits"] == 1
    assert s["misses"] == 1


# ---------------------------------------------------------------------------
# Concurrent safety (basic)
# ---------------------------------------------------------------------------


def test_concurrent_set_get() -> None:
    import threading

    c = ThreadSafeLRUCache(max_size=100)
    errors: list[Exception] = []

    def writer(start: int) -> None:
        try:
            for i in range(start, start + 50):
                c.set(str(i), i * 2)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            for i in range(100):
                c.get(str(i))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i * 50,)) for i in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent errors: {errors}"
