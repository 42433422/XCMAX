"""COVERAGE_RAMP C3.0: Redis 缓存 fallback 路径 / 序列化 / 锁 / Pipeline 失败。

覆盖：
- is_available / ping 失败
- get/set/delete 成功与失败回退（错误计数）
- 本地 L1 缓存命中与 TTL
- 分布式锁 acquire/release（含 token 校验 Lua）
- Pipeline 批量操作
- 空值防护（CACHE_NULL_TTL）
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

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
# is_available
# ---------------------------------------------------------------------------


def test_is_available_when_redis_set(cache, fake_redis):
    assert cache.is_available is True


def test_is_available_when_redis_none():
    c = rc.RedisCache(redis_client=None)
    assert c.is_available is False


def test_is_available_ping_exception():
    r = MagicMock()
    r.ping.side_effect = Exception("boom")
    c = rc.RedisCache(redis_client=r)
    assert c.is_available is False


# ---------------------------------------------------------------------------
# get / set / delete
# ---------------------------------------------------------------------------


def test_make_key(cache):
    assert cache._make_key("foo") == "test:foo"


def test_set_and_get_string(cache, fake_redis):
    fake_redis.get.return_value = json.dumps("hello")
    assert cache.set("k", "hello", ttl=60) is True
    assert cache.get("k") == "hello"
    assert cache._stats["hits"] == 1


def test_get_miss(cache, fake_redis):
    fake_redis.get.return_value = None
    assert cache.get("k") is None
    assert cache._stats["misses"] == 1


def test_get_redis_error_returns_none(cache, fake_redis):
    fake_redis.get.side_effect = Exception("boom")
    assert cache.get("k") is None
    assert cache._stats["errors"] == 1


def test_set_redis_error_returns_false(cache, fake_redis):
    fake_redis.set.side_effect = Exception("boom")
    assert cache.set("k", "v", ttl=10) is False
    assert cache._stats["errors"] == 1


def test_delete_success(cache, fake_redis):
    fake_redis.delete.return_value = 1
    assert cache.delete("k") is True
    assert cache._stats["deletes"] == 1


def test_delete_redis_error(cache, fake_redis):
    fake_redis.delete.side_effect = Exception("boom")
    assert cache.delete("k") is False


def test_local_cache_hit_avoids_redis(cache, fake_redis):
    cache.set("k1", "v1", ttl=60, use_local=True)
    # 重置 redis.get 计数以确认没打 redis
    fake_redis.get.reset_mock()
    assert cache.get("k1", use_local=True) == "v1"
    fake_redis.get.assert_not_called()


def test_local_cache_ttl_expired(cache):
    cache._local_cache["k1"] = ("v1", time.time() - 1)
    fake_redis = cache._redis
    fake_redis.get.return_value = None
    assert cache.get("k1", use_local=True) is None


def test_local_cache_size_cap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rc.os.environ, "get", rc.os.environ.get)  # noop
    c = rc.RedisCache(redis_client=MagicMock(), prefix="x:")
    c._local_cache_size = 2
    c.set("a", 1, ttl=60, use_local=True)
    c.set("b", 2, ttl=60, use_local=True)
    c.set("c", 3, ttl=60, use_local=True)
    # 第三个 set 会触发 LRU 淘汰
    assert "a" not in c._local_cache


def test_get_with_redis_uses_l1_when_enabled(cache, fake_redis):
    cache.set("k2", {"x": 1}, ttl=60, use_local=True)
    fake_redis.get.reset_mock()
    fake_redis.get.return_value = None  # redis 未命中
    # 走 L1 仍能拿到
    assert cache.get("k2", use_local=True) == {"x": 1}


def test_set_uses_default_ttl_when_zero(cache, fake_redis):
    cache.set("k", "v", ttl=0)
    # 应使用 DEFAULT_REDIS_TTL = 300
    args, kwargs = fake_redis.set.call_args
    # key, value, ex=...
    assert args[0] == "test:k"
    assert args[1] == '"v"'
    assert kwargs.get("ex") == rc.DEFAULT_REDIS_TTL


# ---------------------------------------------------------------------------
# Null-value protection
# ---------------------------------------------------------------------------


def test_set_null_uses_cache_null_ttl(cache, fake_redis):
    cache.set_null("missing", ttl=0)
    args, kwargs = fake_redis.set.call_args
    assert kwargs.get("ex") == rc.CACHE_NULL_TTL


def test_get_null_marker(cache, fake_redis):
    fake_redis.get.return_value = rc._NULL_MARKER
    assert cache.get("k", allow_null=True) is None
    assert cache._stats["misses"] == 0  # null 是命中


# ---------------------------------------------------------------------------
# Distributed lock
# ---------------------------------------------------------------------------


def test_acquire_lock_success(cache, fake_redis):
    fake_redis.set.return_value = True
    token = cache.acquire_lock("res", ttl=10)
    assert token is not None
    assert isinstance(token, str)


def test_acquire_lock_fail(cache, fake_redis):
    fake_redis.set.return_value = False
    assert cache.acquire_lock("res", ttl=10) is None


def test_release_lock_match(cache, fake_redis):
    fake_redis.eval.return_value = 1
    assert cache.release_lock("res", "token-abc") is True


def test_release_lock_mismatch(cache, fake_redis):
    fake_redis.eval.return_value = 0
    assert cache.release_lock("res", "wrong-token") is False


def test_release_lock_redis_error(cache, fake_redis):
    fake_redis.eval.side_effect = Exception("boom")
    assert cache.release_lock("res", "t") is False


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_pipeline_get_many(cache, fake_redis):
    pipe = MagicMock()
    fake_redis.pipeline.return_value = pipe
    pipe.execute.return_value = [b'"a"', b'"b"']
    out = cache.get_many(["k1", "k2"])
    assert out == {"k1": "a", "k2": "b"}


def test_pipeline_get_many_redis_error(cache, fake_redis):
    pipe = MagicMock()
    fake_redis.pipeline.return_value = pipe
    pipe.execute.side_effect = Exception("boom")
    assert cache.get_many(["k1", "k2"]) == {}


def test_pipeline_set_many(cache, fake_redis):
    pipe = MagicMock()
    fake_redis.pipeline.return_value = pipe
    pipe.execute.return_value = [True, True]
    assert cache.set_many({"a": 1, "b": 2}, ttl=60) is True


def test_pipeline_set_many_error(cache, fake_redis):
    pipe = MagicMock()
    fake_redis.pipeline.return_value = pipe
    pipe.execute.side_effect = Exception("boom")
    assert cache.set_many({"a": 1}, ttl=60) is False


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_stats_counters(cache, fake_redis):
    fake_redis.get.return_value = json.dumps(42)
    cache.get("x")
    cache.get("y")
    assert cache._stats["hits"] == 2
    assert cache._stats["misses"] == 0


def test_get_stats_returns_dict(cache):
    assert "hits" in cache.get_stats()
    assert "misses" in cache.get_stats()
