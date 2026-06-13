"""
Redis 分布式缓存层

提供高性能的 Redis 缓存实现，支持：
- 多级缓存策略（L1 本地 + L2 Redis）
- 缓存穿透/击穿/雪崩防护
- JSON 序列化（无 pickle，避免反序列化 RCE）
- 命中率统计和监控
- 分布式锁（token + Lua compare-and-del）
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

REDIS_CACHE_PREFIX = os.environ.get("XCAGI_REDIS_CACHE_PREFIX", "xcagi:")
DEFAULT_REDIS_TTL = int(os.environ.get("XCAGI_DEFAULT_CACHE_TTL", "300"))
CACHE_NULL_TTL = int(os.environ.get("XCAGI_CACHE_NULL_TTL", "60"))
_NULL_MARKER = "__NULL__"

_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


class RedisCache:
    """Redis 分布式缓存封装（JSON only，无 pickle）。"""

    def __init__(self, redis_client=None, prefix: str = REDIS_CACHE_PREFIX):
        self._redis = redis_client
        self._prefix = prefix
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0,
        }
        self._local_cache: dict[str, tuple[Any, float]] = {}
        self._local_cache_size = int(os.environ.get("XCAGI_LOCAL_CACHE_SIZE", "1000"))
        self._local_cache_ttl = int(os.environ.get("XCAGI_LOCAL_CACHE_TTL", "10"))
        self._lock_tokens: dict[str, str] = {}

    @property
    def is_available(self) -> bool:
        if self._redis is None:
            return False
        try:
            return self._redis.ping()
        except RECOVERABLE_ERRORS:
            return False

    def _make_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _serialize(self, value: Any) -> str:
        try:
            if isinstance(value, _JSON_SCALAR_TYPES):
                return json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)
            raise TypeError(
                f"Redis cache only supports JSON-serializable types, got {type(value).__name__}"
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("序列化失败: %s", e)
            return json.dumps(str(value), ensure_ascii=False)

    def _deserialize(self, data: str) -> Any:
        if data is None:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, ValueError, TypeError):
            return data

    def get(
        self,
        key: str,
        default: Any = None,
        *,
        use_local: bool = True,
        allow_null: bool = False,
    ) -> Any | None:
        full_key = self._make_key(key)

        if use_local:
            local_hit = self._get_local(full_key)
            if local_hit is not None:
                self._stats["hits"] += 1
                return local_hit

        if not self.is_available:
            self._stats["misses"] += 1
            return default

        try:
            data = self._redis.get(full_key)
            if data is None:
                self._stats["misses"] += 1
                return default

            raw = data.decode("utf-8") if isinstance(data, bytes) else data
            if raw == _NULL_MARKER:
                self._stats["hits"] += 1
                return None if allow_null else default

            value = self._deserialize(raw)
            if use_local:
                self._set_local(full_key, value)
            self._stats["hits"] += 1
            return value

        except RECOVERABLE_ERRORS as e:
            logger.error("Redis GET 失败 [%s]: %s", key, e)
            self._stats["errors"] += 1
            return default

    def set(
        self,
        key: str,
        value: Any,
        ttl: int = DEFAULT_REDIS_TTL,
        nx: bool = False,
        prevent_null: bool = True,
        *,
        use_local: bool = True,
    ) -> bool:
        full_key = self._make_key(key)

        if prevent_null and value is None:
            return self.set_null(key, ttl=ttl)

        effective_ttl = ttl if ttl > 0 else DEFAULT_REDIS_TTL

        if not self.is_available:
            if use_local:
                self._set_local(full_key, value)
            return True

        try:
            serialized = self._serialize(value)
            result = self._redis.set(full_key, serialized, ex=effective_ttl, nx=nx)
            if use_local:
                self._set_local(full_key, value)
            if result:
                self._stats["sets"] += 1
            return bool(result)

        except RECOVERABLE_ERRORS as e:
            logger.error("Redis SET 失败 [%s]: %s", key, e)
            self._stats["errors"] += 1
            return False

    def set_null(self, key: str, ttl: int = 0) -> bool:
        full_key = self._make_key(key)
        effective_ttl = ttl if ttl > 0 else CACHE_NULL_TTL
        if not self.is_available:
            return True
        try:
            return bool(self._redis.set(full_key, _NULL_MARKER, ex=effective_ttl))
        except RECOVERABLE_ERRORS:
            return False

    def delete(self, *keys: str) -> bool:
        if not keys:
            return False

        full_keys = [self._make_key(k) for k in keys]
        for k in full_keys:
            self._local_cache.pop(k, None)

        if not self.is_available:
            return True

        try:
            deleted = self._redis.delete(*full_keys)
            self._stats["deletes"] += deleted
            return deleted > 0
        except RECOVERABLE_ERRORS as e:
            logger.error("Redis DELETE 失败: %s", e)
            self._stats["errors"] += 1
            return False

    def exists(self, *keys: str) -> bool:
        if not keys:
            return False
        for k in keys:
            if self._exists_local(self._make_key(k)):
                return True
        if not self.is_available:
            return False
        try:
            full_keys = [self._make_key(k) for k in keys]
            return bool(self._redis.exists(*full_keys))
        except RECOVERABLE_ERRORS as e:
            logger.error("Redis EXISTS 失败: %s", e)
            return False

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        if not keys or not self.is_available:
            return {}

        try:
            pipe = self._redis.pipeline(transaction=False)
            for key in keys:
                pipe.get(self._make_key(key))
            results = pipe.execute()
            out: dict[str, Any] = {}
            for key, data in zip(keys, results, strict=False):
                if data is None:
                    continue
                raw = data.decode("utf-8") if isinstance(data, bytes) else data
                if raw == _NULL_MARKER:
                    continue
                out[key] = self._deserialize(raw)
            return out
        except RECOVERABLE_ERRORS as e:
            logger.error("Redis MGET 失败: %s", e)
            self._stats["errors"] += 1
            return {}

    def set_many(self, mapping: dict[str, Any], ttl: int = DEFAULT_REDIS_TTL) -> bool:
        if not mapping or not self.is_available:
            return False
        try:
            pipe = self._redis.pipeline(transaction=False)
            for key, value in mapping.items():
                full_key = self._make_key(key)
                serialized = self._serialize(value)
                pipe.setex(full_key, ttl, serialized)
                self._set_local(full_key, value)
            results = pipe.execute()
            success_count = sum(1 for r in results if r)
            self._stats["sets"] += success_count
            return all(results)
        except RECOVERABLE_ERRORS as e:
            logger.error("Redis MSET 失败: %s", e)
            self._stats["errors"] += 1
            return False

    def incr(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        full_key = self._make_key(key)
        if not self.is_available:
            return 0
        try:
            pipe = self._redis.pipeline()
            pipe.incrby(full_key, amount)
            if ttl:
                pipe.expire(full_key, ttl)
            results = pipe.execute()
            return results[0]
        except RECOVERABLE_ERRORS as e:
            logger.error("Redis INCR 失败 [%s]: %s", key, e)
            self._stats["errors"] += 1
            return 0

    def expire(self, key: str, ttl: int) -> bool:
        if not self.is_available:
            return False
        try:
            return bool(self._redis.expire(self._make_key(key), ttl))
        except RECOVERABLE_ERRORS as e:
            logger.error("Redis EXPIRE 失败 [%s]: %s", key, e)
            return False

    def ttl(self, key: str) -> int:
        if not self.is_available:
            return -1
        try:
            return self._redis.ttl(self._make_key(key))
        except RECOVERABLE_ERRORS:
            return -1

    def acquire_lock(self, key: str, ttl: int = 10) -> str | None:
        lock_key = self._make_key(f"lock:{key}")
        if not self.is_available:
            return None
        token = uuid.uuid4().hex
        try:
            acquired = self._redis.set(lock_key, token, nx=True, ex=ttl)
            if acquired:
                self._lock_tokens[key] = token
                return token
            return None
        except RECOVERABLE_ERRORS as e:
            logger.error("获取分布式锁失败 [%s]: %s", key, e)
            return None

    def release_lock(self, key: str, token: str) -> bool:
        lock_key = self._make_key(f"lock:{key}")
        if not self.is_available:
            return False
        try:
            result = self._redis.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
            if result:
                self._lock_tokens.pop(key, None)
            return bool(result)
        except RECOVERABLE_ERRORS as e:
            logger.error("释放分布式锁失败 [%s]: %s", key, e)
            return False

    def lock(self, key: str, timeout: int = 10, blocking_timeout: int | None = None) -> bool:
        """Backward-compatible lock API; returns False when Redis unavailable."""
        token = self.acquire_lock(key, ttl=timeout)
        if token is not None:
            return True
        if blocking_timeout:
            start = time.time()
            while time.time() - start < blocking_timeout:
                time.sleep(0.05)
                token = self.acquire_lock(key, ttl=timeout)
                if token is not None:
                    return True
        return False

    def unlock(self, key: str) -> bool:
        token = self._lock_tokens.get(key)
        if not token:
            return False
        return self.release_lock(key, token)

    def clear_pattern(self, pattern: str) -> int:
        if not self.is_available:
            return 0
        try:
            full_pattern = self._make_key(pattern)
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=full_pattern, count=100)
                if keys:
                    deleted += self._redis.delete(*keys)
                if cursor == 0:
                    break
            prefix_stub = self._prefix + pattern.replace("*", "")
            for k in list(self._local_cache.keys()):
                if k.startswith(prefix_stub):
                    del self._local_cache[k]
            return deleted
        except RECOVERABLE_ERRORS as e:
            logger.error("清除模式失败 [%s]: %s", pattern, e)
            return 0

    def _get_local(self, key: str) -> Any | None:
        if key in self._local_cache:
            value, timestamp = self._local_cache[key]
            if time.time() - timestamp < self._local_cache_ttl:
                return value
            del self._local_cache[key]
        return None

    def _set_local(self, key: str, value: Any) -> None:
        if len(self._local_cache) >= self._local_cache_size:
            oldest_key = next(iter(self._local_cache))
            del self._local_cache[oldest_key]
        self._local_cache[key] = (value, time.time())

    def _exists_local(self, key: str) -> bool:
        return self._get_local(key) is not None

    def clear_local_cache(self) -> None:
        self._local_cache.clear()

    @property
    def stats(self) -> dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        return {
            **self._stats,
            "hit_rate": round(hit_rate, 2),
            "local_cache_size": len(self._local_cache),
            "is_available": self.is_available,
        }

    def get_stats(self) -> dict[str, Any]:
        return dict(self.stats)

    def reset_stats(self) -> None:
        for key in self._stats:
            self._stats[key] = 0


def cache_decorator(
    cache_instance: RedisCache,
    ttl: int = DEFAULT_REDIS_TTL,
    key_prefix: str = "",
    skip_args: list[int] | None = None,
):
    skip_args = skip_args or []

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                cache_key_parts = [str(arg) for i, arg in enumerate(args) if i not in skip_args]
                cache_key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key_str = ":".join(cache_key_parts)
                cache_key = (
                    f"{key_prefix}{func.__name__}:"
                    f"{hashlib.sha256(cache_key_str.encode()).hexdigest()}"
                )
                cached = cache_instance.get(cache_key)
                if cached is not None:
                    return cached
                result = func(*args, **kwargs)
                cache_instance.set(cache_key, result, ttl=ttl)
                return result
            except RECOVERABLE_ERRORS as e:
                logger.error("缓存装饰器执行失败 [%s]: %s", func.__name__, e)
                return func(*args, **kwargs)

        return wrapper

    return decorator


def async_cache_decorator(
    cache_instance: RedisCache, ttl: int = DEFAULT_REDIS_TTL, key_prefix: str = ""
):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = (
                f"{key_prefix}{func.__name__}:"
                f"{hashlib.sha256(str(args + tuple(sorted(kwargs.items()))).encode()).hexdigest()}"
            )
            cached = cache_instance.get(cache_key)
            if cached is not None:
                return {"cached": True, "data": cached}
            try:
                result = func(*args, **kwargs)
                cache_instance.set(cache_key, result, ttl=ttl)
                return {"cached": False, "data": result}
            except RECOVERABLE_ERRORS as e:
                logger.error("异步缓存装饰器失败 [%s]: %s", func.__name__, e)
                raise

        return wrapper

    return decorator


_redis_cache_instance: RedisCache | None = None


def get_redis_cache(redis_client=None) -> RedisCache:
    global _redis_cache_instance
    if _redis_cache_instance is None:
        _redis_cache_instance = RedisCache(redis_client)
    return _redis_cache_instance


def init_redis_cache_from_app(app) -> RedisCache | None:
    global _redis_cache_instance
    redis_client = (
        getattr(app.extensions.get("cache"), "_client", None)
        if hasattr(app, "extensions")
        else None
    )
    if redis_client is None:
        try:
            import redis

            from app.utils.deployment import redis_url_from_env

            redis_url = ""
            if hasattr(app, "config"):
                redis_url = (app.config.get("CACHE_REDIS_URL") or "").strip()
            if not redis_url:
                redis_url = redis_url_from_env()
            if not redis_url:
                return None
            redis_client = redis.from_url(redis_url, decode_responses=True)
        except RECOVERABLE_ERRORS as e:
            logger.warning("无法连接 Redis: %s", e)
            return None
    _redis_cache_instance = RedisCache(redis_client)
    logger.info("Redis 缓存初始化完成")
    return _redis_cache_instance
