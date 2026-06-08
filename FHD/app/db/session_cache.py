"""Thread-safe LRU cache with TTL for DB query results (spec P0-1)."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class ThreadSafeLRUCache:
    """OrderedDict LRU with TTL and threading.Lock protection."""

    def __init__(self, max_size: int = 128, ttl_seconds: float = 300.0) -> None:
        self._max_size = max(1, max_size)
        self._ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if time.time() - ts > self._ttl_seconds:
                del self._data[key]
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            now = time.time()
            expired = [k for k, (ts, _) in self._data.items() if now - ts > self._ttl_seconds]
            for k in expired:
                del self._data[k]
            if key in self._data:
                del self._data[key]
            while len(self._data) >= self._max_size:
                self._data.popitem(last=False)
                self._evictions += 1
            self._data[key] = (now, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "size": len(self._data),
            }
