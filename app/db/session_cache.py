from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


class ThreadSafeLRUCache:
    def __init__(self, max_size: int = 128, ttl_seconds: float = 300.0):
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            inserted_at, value = entry
            if time.time() - inserted_at > self._ttl_seconds:
                del self._cache[key]
                self._misses += 1
                self._evictions += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = (time.time(), value)
                return
            if len(self._cache) >= self._max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                self._evictions += 1
                logger.debug("LRU evicted key: %s", evicted_key)
            self._cache[key] = (time.time(), value)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
        logger.info("Query cache cleared")

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def make_key(self, func_name: str, *args, **kwargs) -> str:
        key_parts = [func_name, repr(args), repr(sorted(kwargs.items()))]
        return "|".join(key_parts)


# Desktop SQLite write guard (T28: co-located with session/db helpers; was sqlite_write_guard.py)
_write_lock = threading.Lock()


@contextmanager
def sqlite_write_guard():
    """串行化桌面环境下的批量写（Excel 导入等）。"""
    from app.desktop_runtime.paths import is_desktop_mode

    if not is_desktop_mode():
        yield
        return
    with _write_lock:
        yield


__all__ = ["ThreadSafeLRUCache", "sqlite_write_guard"]
