import hashlib
import logging
import os
import time
from contextlib import contextmanager
from functools import wraps

from app.db import SessionLocal
from app.db.session_cache import ThreadSafeLRUCache
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)

_query_cache = ThreadSafeLRUCache(max_size=128, ttl_seconds=300.0)
_CACHE_MAX_SIZE = 128
_CACHE_TTL_SECONDS = 300


def _make_cache_key(query_func_name: str, *args, **kwargs) -> str:
    key_str = f"{query_func_name}:{repr(args)}:{repr(sorted(kwargs.items()))}"
    return hashlib.sha256(key_str.encode()).hexdigest()


def make_cache_key(query_func_name: str, *args, **kwargs) -> str:
    """Public alias for tests and callers."""
    return _make_cache_key(query_func_name, *args, **kwargs)


def _redis_cache_backend():
    if os.environ.get("XCAGI_QUERY_CACHE_BACKEND", "memory").strip().lower() != "redis":
        return None
    try:
        from app.utils.redis_cache import get_redis_cache

        cache = get_redis_cache()
        return cache if cache.is_available else None
    except OPERATIONAL_ERRORS:
        return None


def get_cached_query(cache_key: str):
    redis_cache = _redis_cache_backend()
    if redis_cache is not None:
        val = redis_cache.get(f"query:{cache_key}")
        if val is not None:
            return val
    return _query_cache.get(cache_key)


def set_cached_query(cache_key: str, value, ttl: int = _CACHE_TTL_SECONDS):
    _query_cache.set(cache_key, value)
    redis_cache = _redis_cache_backend()
    if redis_cache is not None:
        redis_cache.set(f"query:{cache_key}", value, ttl=ttl)


def clear_query_cache():
    _query_cache.clear()
    redis_cache = _redis_cache_backend()
    if redis_cache is not None:
        redis_cache.clear_pattern("query:*")
    logger.info("Query cache cleared")


def _log_slow_query(query_name: str, duration: float, details: str = ""):
    if duration >= 1.0:
        logger.warning(f"Slow query detected: {query_name} took {duration:.3f}s. {details}")


class _QueryTimer:
    def __init__(self, query_name: str):
        self.query_name = query_name
        self.start_time: float = 0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        _log_slow_query(self.query_name, duration)
        return False


def timed_query(query_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with _QueryTimer(query_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except OPERATIONAL_ERRORS as e:
        db.rollback()
        logger.error(f"数据库事务失败，已回滚: {e}")
        raise
    finally:
        db.close()


def get_db_dependency():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except OPERATIONAL_ERRORS as e:
        db.rollback()
        logger.error(f"数据库事务失败，已回滚: {e}")
        raise
    finally:
        db.close()
