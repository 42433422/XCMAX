"""NeuroBus interface and enhanced in-memory implementation.

Aligned with FHD's NeuroBus reliability layer:
- Priority-aware dispatch (CRITICAL > HIGH > NORMAL > LOW > BACKGROUND)
- Handler statistics (call count, error count, error rate)
- Circuit breaker integration (per-domain)
- Dead-letter queue integration
- Event deduplication with TTL eviction
- Handler filter support
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from enum import IntEnum
from typing import Any

from .events import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Any]
AsyncEventHandler = Callable[[DomainEvent], Any]


class EventPriority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class HandlerSubscription:
    __slots__ = (
        "event_name",
        "handler",
        "priority",
        "filter_fn",
        "call_count",
        "error_count",
        "created_at",
    )

    def __init__(
        self,
        event_name: str,
        handler: EventHandler,
        priority: int = 0,
        filter_fn: Callable[[DomainEvent], bool] | None = None,
    ):
        self.event_name = event_name
        self.handler = handler
        self.priority = priority
        self.filter_fn = filter_fn
        self.call_count = 0
        self.error_count = 0
        self.created_at = time.time()

    def should_handle(self, event: DomainEvent) -> bool:
        if self.filter_fn:
            return self.filter_fn(event)
        return True

    def record_call(self, success: bool = True) -> None:
        self.call_count += 1
        if not success:
            self.error_count += 1

    @property
    def error_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time: float | None = None
        self._lock = threading.RLock()

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if (
                    self._last_failure_time
                    and (time.time() - self._last_failure_time) >= self._recovery_timeout
                ):
                    self._state = "half_open"
                    logger.info("Circuit [%s] transitioning to half_open", self.name)
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == "half_open":
                self._state = "closed"
                self._failure_count = 0
                logger.info("Circuit [%s] resetting to closed", self.name)

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == "half_open":
                self._state = "open"
                logger.warning("Circuit [%s] failure in half_open, opening", self.name)
            elif self._state == "closed" and self._failure_count >= self._failure_threshold:
                self._state = "open"
                logger.warning(
                    "Circuit [%s] open due to %d failures", self.name, self._failure_count
                )

    @property
    def state(self) -> str:
        return self._state

    def reset(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failure_count = 0
            self._last_failure_time = None


class DeduplicationCache:
    def __init__(self, ttl_seconds: float = 300.0, max_size: int = 10000):
        self._cache: dict[str, float] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._lock = threading.Lock()

    def mark_processing(self, key: str) -> bool:
        with self._lock:
            self._evict_expired()
            if key in self._cache:
                return False
            if len(self._cache) >= self._max_size:
                oldest = min(self._cache, key=self._cache.get)
                del self._cache[oldest]
            self._cache[key] = time.time()
            return True

    def mark_processed(self, key: str) -> None:
        pass

    def remove(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, t in self._cache.items() if (now - t) > self._ttl]
        for k in expired:
            del self._cache[k]


class NeuroBus:
    def subscribe(
        self,
        event_name: str,
        handler: EventHandler,
        *,
        priority: int = 0,
        filter_fn: Callable[[DomainEvent], bool] | None = None,
    ) -> HandlerSubscription:
        raise NotImplementedError

    def publish(self, event: DomainEvent) -> bool:
        raise NotImplementedError

    def get_stats(self) -> dict[str, Any]:
        raise NotImplementedError


def _env_flag(name: str, default: bool = False) -> bool:
    return (
        os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
        if os.environ.get(name)
        else default
    )


class InMemoryNeuroBus(NeuroBus):
    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerSubscription]] = defaultdict(list)
        self._global_handlers: list[HandlerSubscription] = []
        self._seen: set[str] = set()

        self._published_count = 0
        self._processed_count = 0
        self._error_count = 0
        self._dropped_count = 0
        self._lock = threading.RLock()

        self._dedup: DeduplicationCache | None = None
        if _env_flag("MODSTORE_BUS_DEDUP", default=True):
            self._dedup = DeduplicationCache()

        self._circuit: CircuitBreaker | None = None
        if _env_flag("MODSTORE_BUS_CIRCUIT", default=True):
            self._circuit = CircuitBreaker("modstore_neurobus")

        self._dlq_callback: Callable[[DomainEvent, Exception, str | None], None] | None = None

    def set_dlq_callback(
        self, callback: Callable[[DomainEvent, Exception, str | None], None]
    ) -> None:
        self._dlq_callback = callback

    def subscribe(
        self,
        event_name: str,
        handler: EventHandler,
        *,
        priority: int = 0,
        filter_fn: Callable[[DomainEvent], bool] | None = None,
    ) -> HandlerSubscription:
        sub = HandlerSubscription(event_name, handler, priority=priority, filter_fn=filter_fn)
        with self._lock:
            if event_name == "*":
                self._global_handlers.append(sub)
            else:
                self._handlers[event_name].append(sub)
                self._handlers[event_name].sort(key=lambda s: s.priority)
        return sub

    def publish(self, event: DomainEvent) -> bool:
        with self._lock:
            if event.idempotency_key in self._seen:
                logger.debug("skip duplicate event: %s", event.idempotency_key)
                return False

            if self._dedup is not None:
                if not self._dedup.mark_processing(event.idempotency_key):
                    logger.debug("dedup blocked event: %s", event.idempotency_key)
                    return False

            if self._circuit is not None and not self._circuit.can_execute():
                logger.warning("circuit open; dropping event: %s", event.event_name)
                self._dropped_count += 1
                return False

            self._seen.add(event.idempotency_key)
            self._published_count += 1

        handlers_called = 0
        any_failed = False

        for sub in [*self._handlers.get(event.event_name, []), *self._global_handlers]:
            if not sub.should_handle(event):
                continue
            handlers_called += 1
            try:
                sub.handler(event)
                sub.record_call(success=True)
                if self._circuit is not None:
                    self._circuit.record_success()
            except Exception as exc:
                sub.record_call(success=False)
                any_failed = True
                self._error_count += 1
                if self._circuit is not None:
                    self._circuit.record_failure()
                logger.exception(
                    "event handler failed: %s handler=%s",
                    event.event_name,
                    getattr(sub.handler, "__name__", "?"),
                )
                if self._dlq_callback is not None:
                    try:
                        self._dlq_callback(event, exc, getattr(sub.handler, "__name__", None))
                    except Exception:
                        logger.exception("DLQ callback failed for event: %s", event.event_name)

        if any_failed and self._dedup is not None:
            self._dedup.remove(event.idempotency_key)
        elif not any_failed and self._dedup is not None:
            self._dedup.mark_processed(event.idempotency_key)

        self._processed_count += 1
        return True

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            handler_stats = {}
            for name, subs in self._handlers.items():
                handler_stats[name] = [
                    {
                        "handler": getattr(s.handler, "__name__", "?"),
                        "calls": s.call_count,
                        "errors": s.error_count,
                        "error_rate": round(s.error_rate, 4),
                    }
                    for s in subs
                ]
            return {
                "published": self._published_count,
                "processed": self._processed_count,
                "errors": self._error_count,
                "dropped": self._dropped_count,
                "handlers": sum(len(v) for v in self._handlers.values()),
                "global_handlers": len(self._global_handlers),
                "dedup_enabled": self._dedup is not None,
                "circuit_breaker_state": self._circuit.state if self._circuit else "disabled",
                "handler_details": handler_stats,
            }
