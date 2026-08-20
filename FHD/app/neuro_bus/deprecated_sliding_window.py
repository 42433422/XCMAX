"""Backward-compatible rate-limiter implementations kept outside the core path."""

from __future__ import annotations

import time
import warnings
from threading import RLock


class SlidingWindowCounter:
    """Deprecated sliding-window counter retained for external callers."""

    def __init__(self, window_size: float = 1.0):
        warnings.warn(
            "SlidingWindowCounter is deprecated and memory-inefficient; use TokenBucket instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._window_size = window_size
        self._timestamps: list[float] = []
        self._lock = RLock()

    def add(self) -> int:
        """Add a request and return the number still inside the window."""
        now = time.time()
        with self._lock:
            cutoff = now - self._window_size
            self._timestamps = [timestamp for timestamp in self._timestamps if timestamp > cutoff]
            self._timestamps.append(now)
            return len(self._timestamps)

    def count(self) -> int:
        """Return the number of requests still inside the window."""
        now = time.time()
        with self._lock:
            cutoff = now - self._window_size
            self._timestamps = [timestamp for timestamp in self._timestamps if timestamp > cutoff]
            return len(self._timestamps)

    def reset(self) -> None:
        """Reset the counter."""
        with self._lock:
            self._timestamps.clear()
