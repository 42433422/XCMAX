import hashlib
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.db.session_cache import ThreadSafeLRUCache
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
# This lifecycle boundary cleans up cancellation and programming errors, then re-raises them.
_SESSION_EXIT_ERRORS: tuple[type[BaseException], ...] = (BaseException,)

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
        from app.utils.performance.redis_cache import get_redis_cache

        cache = get_redis_cache()
        return cache if cache.is_available else None
    except RECOVERABLE_ERRORS:
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
        logger.warning("Slow query detected: %s took %.3fs. %s", query_name, duration, details)


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


def _owned_session_scope(db: Session, *, failure_message: str) -> Iterator[Session]:
    original_error: BaseException | None = None
    try:
        yield db
        db.commit()
    except _SESSION_EXIT_ERRORS as exc:
        original_error = exc
        try:
            # after_commit failures and partial rollbacks must only close.
            if db.is_active:
                db.rollback()
                logger.error("%s", failure_message)
        except _SESSION_EXIT_ERRORS as cleanup_error:
            exc.add_note(f"SQL session rollback failed: {cleanup_error!r}")
        raise
    finally:
        try:
            db.close()
        except _SESSION_EXIT_ERRORS as cleanup_error:
            if original_error is None:
                raise
            original_error.add_note(f"SQL session close failed: {cleanup_error!r}")


def _db_session_scope():
    """共享的 DB 会话生命周期（提交/回滚/关闭）。

    ``get_db`` 与 ``get_db_dependency`` 复用同一实现，避免逻辑重复漂移：
    前者是 ``contextmanager``（``with get_db() as db:``），后者是 FastAPI
    依赖用的裸生成器（``Depends(get_db_dependency)``）。
    """
    yield from _owned_session_scope(SessionLocal(), failure_message="数据库事务失败，已回滚")


get_db = contextmanager(_db_session_scope)


@contextmanager
def get_host_db():
    """宿主基库事务：users/sessions 等，不受 Active-Mod 分库影响。"""
    from app.db import HostSessionLocal

    yield from _owned_session_scope(HostSessionLocal(), failure_message="宿主库事务失败，已回滚")


def get_db_dependency():
    yield from _db_session_scope()
