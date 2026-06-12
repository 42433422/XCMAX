"""Distributed limit on concurrent AI chat SSE streams per pod (Tier C)."""

from __future__ import annotations

import logging
import os
import threading

from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)

_local_slots = threading.Semaphore(
    int(os.environ.get("XCAGI_CHAT_STREAM_MAX_PER_POD", "50"))
)


def acquire_chat_stream_slot() -> bool:
    max_per = int(os.environ.get("XCAGI_CHAT_STREAM_MAX_PER_POD", "50"))
    if max_per <= 0:
        return True
    try:
        from app.utils.redis_cache import get_redis_cache

        cache = get_redis_cache()
        if cache.is_available:
            key = "chat_stream:active"
            count = cache.incr(key, 1, ttl=300)
            if count > max_per * int(os.environ.get("XCAGI_CHAT_STREAM_POD_COUNT", "3")):
                cache.incr(key, -1, ttl=300)
                return False
            return True
    except OPERATIONAL_ERRORS as exc:
        logger.debug("Redis chat stream slot unavailable, falling back to local: %s", exc)
    return _local_slots.acquire(blocking=False)


def release_chat_stream_slot() -> None:
    try:
        from app.utils.redis_cache import get_redis_cache

        cache = get_redis_cache()
        if cache.is_available:
            cache.incr("chat_stream:active", -1, ttl=300)
            return
    except OPERATIONAL_ERRORS as exc:
        logger.debug("Redis chat stream release skipped: %s", exc)
    try:
        _local_slots.release()
    except ValueError:
        pass
