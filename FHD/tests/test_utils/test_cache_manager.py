"""Tests for app.utils.cache_manager — LRU / LRUTTL / TimedCache / CacheManager / decorators."""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.utils.cache_manager import (
    CacheManager,
    CacheStats,
    LRUCache,
    LRUTTLCache,
    TimedCache,
    _read_env_int,
    cache_key,
    clear_all_caches,
    get_ai_response_cache,
    get_cache_manager,
    get_intent_deepseek_cache,
    get_intent_rule_cache,
    get_purchase_unit_cache,
    with_cache,
)


# ---------------------------------------------------------------------------
# _read_env_int
# ---------------------------------------------------------------------------


class TestReadEnvInt:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_X_VAR", raising=False)
        assert _read_env_int("TEST_X_VAR", 42) == 42

    def test_valid_value(self, monkeypatch):
        monkeypatch.setenv("TEST_X_VAR", "100")
        assert _read_env_int("TEST_X_VAR", 42) == 100

    def test_zero_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_X_VAR", "0")
        assert _read_env_int("TEST_X_VAR", 42) == 42

    def test_negative_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_X_VAR", "-5")
        assert _read_env_int("TEST_X_VAR", 42) == 42

    def test_non_int_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_X_VAR", "abc")
        assert _read_env_int("TEST_X_VAR", 42) == 42

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("TEST_X_VAR", "  200  ")
        assert _read_env_int("TEST_X_VAR", 42) == 200

    def test_empty_string_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_X_VAR", "   ")
        assert _read_env_int("TEST_X_VAR", 42) == 42


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_defaults(self):
        s = CacheStats()
        assert s.hits == 0
        assert s.misses == 0
        assert s.sets == 0
        assert s.evictions == 0

    def test_total(self):
        s = CacheStats(hits=3, misses=2)
        assert s.total == 5

    def test_hit_rate_zero_total(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_nonzero(self):
        s = CacheStats(hits=7, misses=3)
        assert abs(s.hit_rate - 0.7) < 1e-9

    def test_str(self):
        s = CacheStats(hits=8, misses=2)
        text = str(s)
        assert "80.00%" in text


# ---------------------------------------------------------------------------
# LRUCache
# ---------------------------------------------------------------------------


class TestLRUCache:
    def test_set_and_get(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_get_miss(self):
        c = LRUCache(max_size=10, name="test")
        assert c.get("missing") is None

    def test_eviction(self):
        c = LRUCache(max_size=3, name="test")
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.set("d", 4)  # evicts "a"
        assert c.get("a") is None
        assert c.get("d") == 4
        assert c.stats.evictions == 1

    def test_update_existing_key(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        c.set("k1", "v2")
        assert c.get("k1") == "v2"
        assert c.stats.sets == 2

    def test_lru_order(self):
        c = LRUCache(max_size=3, name="test")
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")  # access "a" so it's most recently used
        c.set("d", 4)  # evicts "b" (least recently used)
        assert c.get("a") == 1
        assert c.get("b") is None

    def test_has(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        assert c.has("k1") is True
        assert c.has("missing") is False

    def test_remove(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        assert c.remove("k1") is True
        assert c.get("k1") is None
        assert c.remove("k1") is False

    def test_clear(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        c.clear()
        assert c.size == 0
        assert c.get("k1") is None

    def test_size_and_len(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        c.set("k2", "v2")
        assert c.size == 2
        assert len(c) == 2

    def test_stats_tracking(self):
        c = LRUCache(max_size=10, name="test")
        c.set("k1", "v1")
        c.get("k1")  # hit
        c.get("missing")  # miss
        assert c.stats.hits == 1
        assert c.stats.misses == 1
        assert c.stats.sets == 1


# ---------------------------------------------------------------------------
# LRUTTLCache
# ---------------------------------------------------------------------------


class TestLRUTTLCache:
    def test_set_and_get(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_expired_item_returns_none(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=1, name="test")
        c.set("k1", "v1")
        # Manually expire the timestamp
        c._timestamps["k1"] = time.time() - 2
        assert c.get("k1") is None
        assert c.stats.misses == 1

    def test_has_expired(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=1, name="test")
        c.set("k1", "v1")
        c._timestamps["k1"] = time.time() - 2
        assert c.has("k1") is False

    def test_has_not_expired(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        c.set("k1", "v1")
        assert c.has("k1") is True

    def test_has_missing_key(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        assert c.has("missing") is False

    def test_eviction_on_set(self):
        c = LRUTTLCache(max_size=2, ttl_seconds=300, name="test")
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)  # evicts "a"
        assert c.get("a") is None

    def test_cleanup(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=1, name="test")
        c.set("k1", "v1")
        c._timestamps["k1"] = time.time() - 2
        removed = c.cleanup()
        assert removed == 1
        assert c.size == 0

    def test_remove_existing(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        c.set("k1", "v1")
        assert c.remove("k1") is True
        assert "k1" not in c._timestamps

    def test_remove_missing(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        assert c.remove("missing") is False

    def test_clear(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        c.set("k1", "v1")
        c.clear()
        assert c.size == 0
        assert len(c._timestamps) == 0

    def test_is_expired_no_timestamp(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        assert c._is_expired("missing") is True

    def test_update_existing_key(self):
        c = LRUTTLCache(max_size=10, ttl_seconds=300, name="test")
        c.set("k1", "v1")
        c.set("k1", "v2")
        assert c.get("k1") == "v2"


# ---------------------------------------------------------------------------
# TimedCache
# ---------------------------------------------------------------------------


class TestTimedCache:
    def test_set_and_get(self):
        c = TimedCache(ttl_seconds=300, name="test")
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_expired_returns_none(self):
        c = TimedCache(ttl_seconds=1, name="test")
        c.set("k1", "v1")
        # Manually backdate
        c._cache["k1"] = ("v1", time.time() - 2)
        assert c.get("k1") is None

    def test_miss(self):
        c = TimedCache(ttl_seconds=300, name="test")
        assert c.get("missing") is None

    def test_clear(self):
        c = TimedCache(ttl_seconds=300, name="test")
        c.set("k1", "v1")
        c.clear()
        assert c.size == 0

    def test_size(self):
        c = TimedCache(ttl_seconds=300, name="test")
        c.set("k1", "v1")
        c.set("k2", "v2")
        assert c.size == 2

    def test_stats(self):
        c = TimedCache(ttl_seconds=300, name="test")
        c.set("k1", "v1")
        c.get("k1")
        c.get("missing")
        assert c.stats.hits == 1
        assert c.stats.misses == 1
        assert c.stats.sets == 1


# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_deterministic(self):
        k1 = cache_key("func", "arg1", key="val")
        k2 = cache_key("func", "arg1", key="val")
        assert k1 == k2

    def test_different_args_different_key(self):
        k1 = cache_key("func", "arg1")
        k2 = cache_key("func", "arg2")
        assert k1 != k2

    def test_kwargs_sorted(self):
        k1 = cache_key("func", a="1", b="2")
        k2 = cache_key("func", b="2", a="1")
        assert k1 == k2

    def test_returns_hex_string(self):
        k = cache_key("func")
        assert len(k) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in k)


# ---------------------------------------------------------------------------
# with_cache decorator
# ---------------------------------------------------------------------------


class TestWithCache:
    def test_caches_result(self):
        cache = LRUCache(max_size=10, name="test")
        call_count = 0

        @with_cache(cache)
        def expensive(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10
        assert call_count == 1

    def test_custom_key_func(self):
        cache = LRUCache(max_size=10, name="test")

        def my_key(x, **kw):
            return f"custom:{x}"

        @with_cache(cache, key_func=my_key)
        def func(x):
            return x * 3

        assert func(7) == 21
        assert cache.get("custom:7") == 21

    def test_different_args_different_cache(self):
        cache = LRUCache(max_size=10, name="test")

        @with_cache(cache)
        def func(x):
            return x * 2

        assert func(1) == 2
        assert func(2) == 4


# ---------------------------------------------------------------------------
# CacheManager singleton
# ---------------------------------------------------------------------------


class TestCacheManager:
    def test_singleton(self):
        # Reset singleton for test isolation
        CacheManager._instance = None
        cm1 = CacheManager()
        cm2 = CacheManager()
        assert cm1 is cm2
        CacheManager._instance = None

    def test_default_caches_created(self):
        CacheManager._instance = None
        cm = CacheManager()
        assert cm.get_cache("intent_rule") is not None
        assert cm.get_cache("intent_deepseek") is not None
        assert cm.get_cache("ai_response") is not None
        assert cm.get_cache("purchase_unit") is not None
        assert cm.get_cache("product") is not None
        CacheManager._instance = None

    def test_get_cache_missing(self):
        CacheManager._instance = None
        cm = CacheManager()
        assert cm.get_cache("nonexistent") is None
        CacheManager._instance = None

    def test_register_cache(self):
        CacheManager._instance = None
        cm = CacheManager()
        custom = LRUCache(max_size=10, name="custom")
        cm.register_cache("custom", custom)
        assert cm.get_cache("custom") is custom
        CacheManager._instance = None

    def test_clear_all(self):
        CacheManager._instance = None
        cm = CacheManager()
        cm.get_cache("intent_rule").set("k", "v")
        cm.clear_all()
        assert cm.get_cache("intent_rule").get("k") is None
        CacheManager._instance = None

    def test_get_stats(self):
        CacheManager._instance = None
        cm = CacheManager()
        stats = cm.get_stats()
        assert "intent_rule" in stats
        assert isinstance(stats["intent_rule"], CacheStats)
        CacheManager._instance = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    def setup_method(self):
        # Reset singletons
        CacheManager._instance = None
        import app.utils.cache_manager as m
        m._cache_manager = None

    def teardown_method(self):
        CacheManager._instance = None
        import app.utils.cache_manager as m
        m._cache_manager = None

    def test_get_cache_manager(self):
        cm = get_cache_manager()
        assert isinstance(cm, CacheManager)

    def test_get_intent_rule_cache(self):
        c = get_intent_rule_cache()
        assert isinstance(c, LRUCache)

    def test_get_intent_deepseek_cache(self):
        c = get_intent_deepseek_cache()
        assert isinstance(c, LRUTTLCache)

    def test_get_ai_response_cache(self):
        c = get_ai_response_cache()
        assert isinstance(c, LRUTTLCache)

    def test_get_purchase_unit_cache(self):
        c = get_purchase_unit_cache()
        assert isinstance(c, LRUCache)

    def test_clear_all_caches(self):
        get_cache_manager().get_cache("intent_rule").set("k", "v")
        clear_all_caches()
        assert get_cache_manager().get_cache("intent_rule").get("k") is None


# ---------------------------------------------------------------------------
# Thread safety (basic smoke test)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_lru_access(self):
        c = LRUCache(max_size=100, name="thread_test")
        errors = []

        def writer(start):
            try:
                for i in range(100):
                    c.set(f"k_{start}_{i}", i)
            except RuntimeError as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(s,)) for s in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
