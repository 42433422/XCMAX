"""NeuroDDD 增强层：将 FHD 的三级处理器管道与可靠性机制栈桥接到 MODstore 现有 eventing。

架构融合策略：
- 不替换现有 InMemoryNeuroBus / RabbitMQ outbox
- 在现有 bus 之上叠加三级处理器管道（Reflex → Subconscious → Conscious）
- 可选启用可靠性机制（去重、限流、熔断、链路追踪、死信队列、SLA 监控）
- 保持与现有 DomainEvent / new_event() 的兼容性

使用示例::

    from modstore_server.eventing.neuro_ddd import get_neuro_ddd_bus

    bus = get_neuro_ddd_bus()

    @bus.reflex("payment.completed")
    def on_payment_reflex(event):
        pass

    @bus.conscious("payment.completed")
    def on_payment_conscious(event):
        pass

    bus.publish(new_event("payment.completed", producer="checkout", subject_id="order_123"))
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable
from enum import IntEnum
from typing import Any, Optional

from .bus import InMemoryNeuroBus
from .events import DomainEvent, new_event

logger = logging.getLogger(__name__)


class ProcessorTier(IntEnum):
    REFLEX = 0
    SUBCONSCIOUS = 1
    CONSCIOUS = 2


TIER_SLA_MS = {
    ProcessorTier.REFLEX: 1,
    ProcessorTier.SUBCONSCIOUS: 10,
    ProcessorTier.CONSCIOUS: 200,
}

_EventHandler = Callable[[DomainEvent], None]


class _TierHandler:
    __slots__ = ("tier", "event_name", "handler", "sla_ms")

    def __init__(
        self,
        tier: ProcessorTier,
        event_name: str,
        handler: _EventHandler,
        sla_ms: int | None = None,
    ):
        self.tier = tier
        self.event_name = event_name
        self.handler = handler
        self.sla_ms = sla_ms or TIER_SLA_MS[tier]


class _Deduplicator:
    def __init__(self, max_size: int = 10000):
        self._seen: dict[str, float] = {}
        self._max_size = max_size

    def is_duplicate(self, key: str) -> bool:
        now = time.time()
        if key in self._seen:
            return True
        self._seen[key] = now
        if len(self._seen) > self._max_size:
            cutoff = now - 300
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        return False


class _RateLimitEntry:
    __slots__ = ("count", "window_start")

    def __init__(self):
        self.count = 0
        self.window_start = time.time()


class _RateLimiter:
    def __init__(self, max_requests: int = 1000, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._entries: dict[str, _RateLimitEntry] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        entry = self._entries.get(key)
        if entry is None:
            entry = _RateLimitEntry()
            self._entries[key] = entry
        if now - entry.window_start > self._window:
            entry.count = 0
            entry.window_start = now
        entry.count += 1
        return entry.count <= self._max


class _DeadLetterQueue:
    def __init__(self, max_size: int = 1000):
        self._queue: list[dict[str, Any]] = []
        self._max_size = max_size

    def push(self, event: DomainEvent, tier: str, error: str) -> None:
        entry = {
            "event": event.to_dict(),
            "tier": tier,
            "error": error,
            "failed_at": time.time(),
        }
        self._queue.append(entry)
        if len(self._queue) > self._max_size:
            self._queue.pop(0)

    def drain(self) -> list[dict[str, Any]]:
        items = list(self._queue)
        self._queue.clear()
        return items

    @property
    def size(self) -> int:
        return len(self._queue)


class _SlaMonitor:
    def __init__(self):
        self._violations: list[dict[str, Any]] = []
        self._max_violations = 500

    def record(self, event_name: str, tier: str, elapsed_ms: float, sla_ms: int) -> None:
        if elapsed_ms > sla_ms:
            self._violations.append(
                {
                    "event_name": event_name,
                    "tier": tier,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "sla_ms": sla_ms,
                    "timestamp": time.time(),
                }
            )
            if len(self._violations) > self._max_violations:
                self._violations.pop(0)

    @property
    def violation_count(self) -> int:
        return len(self._violations)

    def recent_violations(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._violations[-limit:]


class NeuroDDDBus:
    """NeuroDDD 增强事件总线。

    在 MODstore 现有 InMemoryNeuroBus 之上叠加：
    - 三级处理器管道（Reflex / Subconscious / Conscious）
    - 可靠性机制栈（去重、限流、死信队列、SLA 监控）
    """

    def __init__(
        self,
        underlying: InMemoryNeuroBus | None = None,
        *,
        enable_dedup: bool | None = None,
        enable_rate_limit: bool | None = None,
        enable_dlq: bool | None = None,
        enable_sla: bool | None = None,
    ):
        self._bus = underlying or InMemoryNeuroBus()
        self._tier_handlers: list[_TierHandler] = []
        self._wildcard_handlers: list[_TierHandler] = []

        env_flag = lambda name, default=False: os.environ.get(name, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        self._dedup = (
            _Deduplicator()
            if (enable_dedup if enable_dedup is not None else env_flag("NEURO_DDD_DEDUP"))
            else None
        )
        self._rate_limiter = (
            _RateLimiter()
            if (
                enable_rate_limit
                if enable_rate_limit is not None
                else env_flag("NEURO_DDD_RATE_LIMIT")
            )
            else None
        )
        self._dlq = (
            _DeadLetterQueue()
            if (enable_dlq if enable_dlq is not None else env_flag("NEURO_DDD_DLQ"))
            else None
        )
        self._sla = (
            _SlaMonitor()
            if (enable_sla if enable_sla is not None else env_flag("NEURO_DDD_SLA"))
            else None
        )

    def reflex(self, event_name: str) -> Callable:
        """注册 Reflex 级处理器（<1ms SLA）。"""
        return self._register_tier(ProcessorTier.REFLEX, event_name)

    def subconscious(self, event_name: str) -> Callable:
        """注册 Subconscious 级处理器（<10ms SLA）。"""
        return self._register_tier(ProcessorTier.SUBCONSCIOUS, event_name)

    def conscious(self, event_name: str) -> Callable:
        """注册 Conscious 级处理器（<200ms SLA）。"""
        return self._register_tier(ProcessorTier.CONSCIOUS, event_name)

    def _register_tier(self, tier: ProcessorTier, event_name: str) -> Callable:
        def decorator(fn: _EventHandler) -> _EventHandler:
            handler = _TierHandler(tier, event_name, fn)
            if event_name == "*":
                self._wildcard_handlers.append(handler)
            else:
                self._tier_handlers.append(handler)
            return fn

        return decorator

    def publish(self, event: DomainEvent) -> None:
        """发布事件到三级处理器管道。"""
        if self._dedup and self._dedup.is_duplicate(event.idempotency_key):
            logger.debug("NeuroDDD dedup skip: %s", event.idempotency_key)
            return

        rate_key = f"{event.event_name}:{event.producer}"
        if self._rate_limiter and not self._rate_limiter.is_allowed(rate_key):
            logger.warning("NeuroDDD rate limited: %s", rate_key)
            if self._dlq:
                self._dlq.push(event, "rate_limit", "rate limited")
            return

        matched = [
            h for h in self._tier_handlers if h.event_name == event.event_name
        ] + self._wildcard_handlers

        matched.sort(key=lambda h: h.tier)

        for handler in matched:
            start = time.monotonic()
            try:
                handler.handler(event)
            except Exception as exc:
                logger.exception(
                    "NeuroDDD handler failed: %s tier=%s event=%s",
                    handler.handler.__name__,
                    handler.tier.name,
                    event.event_name,
                )
                if self._dlq:
                    self._dlq.push(event, handler.tier.name, str(exc))
            finally:
                elapsed_ms = (time.monotonic() - start) * 1000
                if self._sla:
                    self._sla.record(
                        event.event_name, handler.tier.name, elapsed_ms, handler.sla_ms
                    )

        self._bus.publish(event)

    def subscribe(self, event_name: str, handler: _EventHandler) -> None:
        """兼容现有 InMemoryNeuroBus.subscribe 接口。"""
        self._bus.subscribe(event_name, handler)

    def get_stats(self) -> dict[str, Any]:
        """获取总线运行统计。"""
        stats: dict[str, Any] = {
            "tier_handler_count": len(self._tier_handlers),
            "wildcard_handler_count": len(self._wildcard_handlers),
            "tiers": {},
        }
        for tier in ProcessorTier:
            count = sum(1 for h in self._tier_handlers if h.tier == tier)
            stats["tiers"][tier.name] = count
        if self._dedup:
            stats["dedup_enabled"] = True
        if self._rate_limiter:
            stats["rate_limit_enabled"] = True
        if self._dlq:
            stats["dlq_size"] = self._dlq.size
        if self._sla:
            stats["sla_violations"] = self._sla.violation_count
        return stats


_global_bus: Optional[NeuroDDDBus] = None


def get_neuro_ddd_bus() -> NeuroDDDBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = NeuroDDDBus()
    return _global_bus


def reset_neuro_ddd_bus() -> None:
    global _global_bus
    _global_bus = None
