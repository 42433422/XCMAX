"""app/utils/redis_cache 补充测试（覆盖未测路径）。"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import app.utils.redis_cache as rc


@pytest.fixture
def fake_redis():
    r = MagicMock()
    r.ping.return_value = True
    return r


@pytest.fixture
def cache(fake_redis):
    return rc.RedisCache(redis_client=fake_redis, prefix="test:")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_serialize_string(self, cache):
        assert cache._serialize("hello") == '"hello"'

    def test_serialize_int(self, cache):
        assert cache._serialize(42) == "42"

    def test_serialize_float(self, cache):
        result = cache._serialize(3.14)
        assert "3.14" in result

    def test_serialize_bool(self, cache):
        assert cache._serialize(True) == "true"

    def test_serialize_none(self, cache):
        assert cache._serialize(None) == "null"

    def test_serialize_dict(self, cache):
        result = cache._serialize({"a": 1})
        parsed = json.loads(result)
        assert parsed == {"a": 1}

    def test_serialize_list(self, cache):
        result = cache._serialize([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_serialize_unsupported_type_raises_typeerror(self, cache):
        class CustomObj:
            pass

        # TypeError is NOT in RECOVERABLE_ERRORS, so it propagates
        with pytest.raises(TypeError, match="Redis cache only supports"):
            cache._serialize(CustomObj())

    def test_deserialize_json(self, cache):
        assert cache._deserialize('{"a": 1}') == {"a": 1}

    def test_deserialize_none(self, cache):
        assert cache._deserialize(None) is None

    def test_deserialize_invalid_json(self, cache):
        result = cache._deserialize("not json")
        assert result == "not json"


# ---------------------------------------------------------------------------
# set with prevent_null
# ---------------------------------------------------------------------------


class TestSetWithNull:
    def test_set_none_calls_set_null(self, cache, fake_redis):
        cache.set("k", None, prevent_null=True)
        fake_redis.set.assert_called()
        # Should have called with _NULL_MARKER
        args, kwargs = fake_redis.set.call_args
        assert args[1] == rc._NULL_MARKER

    def test_set_none_prevent_null_false(self, cache, fake_redis):
        # When prevent_null=False and value is None, it should try to serialize None
        result = cache.set("k", None, prevent_null=False)
        # It will serialize None to "null" and set it
        fake_redis.set.assert_called()

    def test_set_null_with_custom_ttl(self, cache, fake_redis):
        cache.set_null("k", ttl=120)
        args, kwargs = fake_redis.set.call_args
        assert kwargs.get("ex") == 120

    def test_set_null_default_ttl(self, cache, fake_redis):
        cache.set_null("k", ttl=0)
        args, kwargs = fake_redis.set.call_args
        assert kwargs.get("ex") == rc.CACHE_NULL_TTL


# ---------------------------------------------------------------------------
# get with allow_null
# ---------------------------------------------------------------------------


class TestGetWithNull:
    def test_get_null_marker_without_allow_null(self, cache, fake_redis):
        fake_redis.get.return_value = rc._NULL_MARKER
        result = cache.get("k", allow_null=False)
        assert result is None  # default is None

    def test_get_null_marker_with_allow_null(self, cache, fake_redis):
        fake_redis.get.return_value = rc._NULL_MARKER
        result = cache.get("k", allow_null=True)
        assert result is None  # returns None explicitly

    def test_get_with_default(self, cache, fake_redis):
        fake_redis.get.return_value = None
        result = cache.get("k", default="fallback")
        assert result == "fallback"


# ---------------------------------------------------------------------------
# set with nx flag
# ---------------------------------------------------------------------------


class TestSetNx:
    def test_set_with_nx(self, cache, fake_redis):
        fake_redis.set.return_value = True
        result = cache.set("k", "v", nx=True)
        assert result is True
        args, kwargs = fake_redis.set.call_args
        assert kwargs.get("nx") is True

    def test_set_nx_returns_false_when_exists(self, cache, fake_redis):
        fake_redis.set.return_value = False
        result = cache.set("k", "v", nx=True)
        assert result is False


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestExists:
    def test_exists_no_keys(self, cache):
        assert cache.exists() is False

    def test_exists_local_hit(self, cache):
        cache._set_local("test:k1", "v1")
        assert cache.exists("k1") is True

    def test_exists_redis_hit(self, cache, fake_redis):
        fake_redis.exists.return_value = 1
        assert cache.exists("k1") is True

    def test_exists_redis_error(self, cache, fake_redis):
        fake_redis.exists.side_effect = RuntimeError("boom")
        assert cache.exists("k1") is False

    def test_exists_no_redis(self):
        c = rc.RedisCache(redis_client=None)
        assert c.exists("k1") is False


# ---------------------------------------------------------------------------
# incr
# ---------------------------------------------------------------------------


class TestIncr:
    def test_incr_success(self, cache, fake_redis):
        pipe = MagicMock()
        pipe.incrby.return_value = None
        pipe.execute.return_value = [5]
        fake_redis.pipeline.return_value = pipe
        result = cache.incr("counter", amount=2)
        assert result == 5

    def test_incr_with_ttl(self, cache, fake_redis):
        pipe = MagicMock()
        pipe.incrby.return_value = None
        pipe.expire.return_value = None
        pipe.execute.return_value = [3, True]
        fake_redis.pipeline.return_value = pipe
        result = cache.incr("counter", amount=1, ttl=60)
        assert result == 3

    def test_incr_no_redis(self):
        c = rc.RedisCache(redis_client=None)
        assert c.incr("counter") == 0

    def test_incr_error(self, cache, fake_redis):
        fake_redis.pipeline.side_effect = RuntimeError("boom")
        assert cache.incr("counter") == 0


# ---------------------------------------------------------------------------
# expire / ttl
# ---------------------------------------------------------------------------


class TestExpireAndTtl:
    def test_expire_success(self, cache, fake_redis):
        fake_redis.expire.return_value = True
        assert cache.expire("k", 60) is True

    def test_expire_no_redis(self):
        c = rc.RedisCache(redis_client=None)
        assert c.expire("k", 60) is False

    def test_expire_error(self, cache, fake_redis):
        fake_redis.expire.side_effect = RuntimeError("boom")
        assert cache.expire("k", 60) is False

    def test_ttl_success(self, cache, fake_redis):
        fake_redis.ttl.return_value = 42
        assert cache.ttl("k") == 42

    def test_ttl_no_redis(self):
        c = rc.RedisCache(redis_client=None)
        assert c.ttl("k") == -1

    def test_ttl_error(self, cache, fake_redis):
        fake_redis.ttl.side_effect = RuntimeError("boom")
        assert cache.ttl("k") == -1


# ---------------------------------------------------------------------------
# lock / unlock
# ---------------------------------------------------------------------------


class TestLockUnlock:
    def test_lock_success(self, cache, fake_redis):
        fake_redis.set.return_value = True
        assert cache.lock("res", timeout=10) is True

    def test_lock_fail(self, cache, fake_redis):
        fake_redis.set.return_value = False
        assert cache.lock("res", timeout=10) is False

    def test_lock_no_redis(self):
        c = rc.RedisCache(redis_client=None)
        assert c.lock("res") is False

    def test_unlock_success(self, cache, fake_redis):
        fake_redis.set.return_value = True
        cache.lock("res", timeout=10)
        fake_redis.eval.return_value = 1
        assert cache.unlock("res") is True

    def test_unlock_no_token(self, cache, fake_redis):
        assert cache.unlock("res") is False

    def test_lock_with_blocking_timeout(self, cache, fake_redis):
        # First call fails, second succeeds
        fake_redis.set.side_effect = [False, True]
        with patch("time.sleep"):
            result = cache.lock("res", timeout=10, blocking_timeout=1)
        assert result is True


# ---------------------------------------------------------------------------
# clear_pattern
# ---------------------------------------------------------------------------


class TestClearPattern:
    def test_clear_pattern_success(self, cache, fake_redis):
        fake_redis.scan.return_value = (0, [b"test:prefix:k1", b"test:prefix:k2"])
        fake_redis.delete.return_value = 2
        result = cache.clear_pattern("prefix:*")
        assert result == 2

    def test_clear_pattern_no_redis(self):
        c = rc.RedisCache(redis_client=None)
        assert c.clear_pattern("prefix:*") == 0

    def test_clear_pattern_error(self, cache, fake_redis):
        fake_redis.scan.side_effect = RuntimeError("boom")
        assert cache.clear_pattern("prefix:*") == 0

    def test_clear_pattern_multiple_scans(self, cache, fake_redis):
        fake_redis.scan.side_effect = [
            (1, [b"test:p:k1"]),
            (0, [b"test:p:k2"]),
        ]
        fake_redis.delete.return_value = 1
        result = cache.clear_pattern("p:*")
        assert result == 2


# ---------------------------------------------------------------------------
# clear_local_cache / _exists_local
# ---------------------------------------------------------------------------


class TestLocalCache:
    def test_clear_local_cache(self, cache):
        cache._set_local("k1", "v1")
        cache.clear_local_cache()
        assert len(cache._local_cache) == 0

    def test_exists_local(self, cache):
        cache._set_local("k1", "v1")
        assert cache._exists_local("k1") is True
        assert cache._exists_local("k2") is False

    def test_local_cache_expired(self, cache):
        cache._local_cache["k1"] = ("v1", time.time() - 100)
        assert cache._get_local("k1") is None


# ---------------------------------------------------------------------------
# stats / get_stats / reset_stats
# ---------------------------------------------------------------------------


class TestStatsExtended:
    def test_hit_rate_calculation(self, cache, fake_redis):
        fake_redis.get.return_value = json.dumps("v")
        cache.get("k1")
        cache.get("k2")
        stats = cache.stats
        assert stats["hit_rate"] > 0

    def test_get_stats_returns_copy(self, cache):
        stats1 = cache.get_stats()
        stats2 = cache.get_stats()
        assert stats1 == stats2
        assert stats1 is not stats2

    def test_reset_stats(self, cache, fake_redis):
        fake_redis.get.return_value = json.dumps("v")
        cache.get("k1")
        cache.reset_stats()
        assert cache._stats["hits"] == 0
        assert cache._stats["misses"] == 0


# ---------------------------------------------------------------------------
# cache_decorator
# ---------------------------------------------------------------------------


class TestCacheDecorator:
    def test_caches_result(self, cache, fake_redis):
        fake_redis.get.return_value = None
        call_count = 0

        @rc.cache_decorator(cache, ttl=60, key_prefix="test:")
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result = my_func(5)
        assert result == 10
        assert call_count == 1

    def test_cache_hit(self, cache, fake_redis):
        fake_redis.get.return_value = 42
        call_count = 0

        @rc.cache_decorator(cache, ttl=60, key_prefix="test:")
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result = my_func(5)
        assert result == 42
        assert call_count == 0

    def test_cache_error_fallback(self, cache, fake_redis):
        fake_redis.get.side_effect = RuntimeError("boom")
        call_count = 0

        @rc.cache_decorator(cache, ttl=60, key_prefix="test:")
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result = my_func(5)
        assert result == 10
        assert call_count == 1

    def test_skip_args(self, cache, fake_redis):
        fake_redis.get.return_value = None

        @rc.cache_decorator(cache, ttl=60, key_prefix="test:", skip_args=[0])
        def my_func(self_arg, x):
            return x * 2

        result = my_func("self_val", 5)
        assert result == 10


# ---------------------------------------------------------------------------
# async_cache_decorator
# ---------------------------------------------------------------------------


class TestAsyncCacheDecorator:
    def test_cache_miss(self, cache, fake_redis):
        fake_redis.get.return_value = None

        @rc.async_cache_decorator(cache, ttl=60, key_prefix="test:")
        def my_func(x):
            return x * 2

        result = my_func(5)
        assert result["cached"] is False
        assert result["data"] == 10

    def test_cache_hit(self, cache, fake_redis):
        fake_redis.get.return_value = 42

        @rc.async_cache_decorator(cache, ttl=60, key_prefix="test:")
        def my_func(x):
            return x * 2

        result = my_func(5)
        assert result["cached"] is True
        assert result["data"] == 42

    def test_error_propagates(self, cache, fake_redis):
        fake_redis.get.return_value = None

        @rc.async_cache_decorator(cache, ttl=60, key_prefix="test:")
        def my_func():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            my_func()


# ---------------------------------------------------------------------------
# get_redis_cache / init_redis_cache_from_app
# ---------------------------------------------------------------------------


class TestGlobalFunctions:
    def test_get_redis_cache_creates_instance(self, monkeypatch):
        import app.utils.redis_cache as rc_mod

        old = rc_mod._redis_cache_instance
        rc_mod._redis_cache_instance = None
        try:
            cache = rc_mod.get_redis_cache()
            assert isinstance(cache, rc.RedisCache)
        finally:
            rc_mod._redis_cache_instance = old

    def test_get_redis_cache_returns_existing(self):
        import app.utils.redis_cache as rc_mod

        existing = rc_mod._redis_cache_instance
        if existing is None:
            rc_mod._redis_cache_instance = rc.RedisCache(None)
        try:
            cache = rc_mod.get_redis_cache()
            assert cache is rc_mod._redis_cache_instance
        finally:
            rc_mod._redis_cache_instance = existing

    def test_init_from_app_with_extensions(self):
        mock_app = MagicMock()
        mock_cache_ext = MagicMock()
        mock_cache_ext._client = MagicMock()
        mock_cache_ext._client.ping.return_value = True
        mock_app.extensions = {"cache": mock_cache_ext}
        result = rc.init_redis_cache_from_app(mock_app)
        assert result is not None

    def test_init_from_app_no_extensions(self, monkeypatch):
        mock_app = MagicMock(spec=[])
        # Even without extensions, init_redis_cache_from_app may still
        # find a redis URL from app.config or env, so it might return a cache
        # Just verify it doesn't crash
        result = rc.init_redis_cache_from_app(mock_app)
        # Result could be None or a RedisCache depending on env
        assert result is None or isinstance(result, rc.RedisCache)

    def test_init_from_app_with_config(self, monkeypatch):
        mock_app = MagicMock()
        mock_app.extensions = {}
        mock_app.config = {"CACHE_REDIS_URL": "redis://localhost:6379/0"}
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client
            result = rc.init_redis_cache_from_app(mock_app)
            assert result is not None
