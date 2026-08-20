"""Subscription registration and diagnostics mixin for NeuroBus."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, cast

from app.neuro_bus.bus_primitives import (
    HandlerSubscription,
    PriorityEventQueue,
    _neuro_trace_sample_rate,
)
from app.neuro_bus.events.base import AsyncEventHandler, EventHandler, NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class NeuroBusSubscriptionsMixin:
    _handlers: dict[str, list[HandlerSubscription]]
    _domain_handlers: dict[str, dict[str, list[HandlerSubscription]]]
    _global_handlers: list[HandlerSubscription]
    _event_queue: PriorityEventQueue
    _published_count: int
    _processed_count: int
    _error_count: int
    _dropped_count: int
    _running: bool
    _rel_dedup: Any
    _rel_rate: Any
    _rel_circuit: Any
    _rel_lifeline: Any
    _rel_tracer: Any
    _rel_sla_log: bool
    _rel_sla_controller: Any
    _rel_retry_handler: Any
    _dlq_integration: Any
    _redis_bridge: Any

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler | AsyncEventHandler,
        priority: int = 0,
        is_async: bool = True,
        filter_fn: Callable[[NeuroEvent], bool] | None = None,
    ) -> HandlerSubscription:
        """
        订阅特定类型事件

        Args:
            event_type: 事件类型
            handler: 处理器函数
            priority: 处理器优先级（数值小的先执行）
            is_async: 是否为异步处理器
            filter_fn: 可选的过滤函数

        Returns:
            订阅对象
        """
        subscription = HandlerSubscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            is_async=is_async,
            filter_fn=filter_fn,
        )

        self._handlers[event_type].append(subscription)

        # 按优先级排序
        self._handlers[event_type].sort(key=lambda s: s.priority)

        logger.debug("Subscribed to %s: %s", event_type, handler.__name__)
        return subscription

    def subscribe_event(
        self,
        event_type: str,
        handler: EventHandler | AsyncEventHandler,
        priority: int = 0,
        is_async: bool = True,
        filter_fn: Callable[[NeuroEvent], bool] | None = None,
        domain: str | None = None,
    ) -> HandlerSubscription:
        """订阅事件；指定 domain 时路由到领域处理器。"""
        if domain:
            return self.subscribe_to_domain(domain, event_type, handler, priority, is_async)
        return self.subscribe(event_type, handler, priority, is_async, filter_fn)

    def subscribe_global(
        self,
        handler: EventHandler | AsyncEventHandler,
        filter_fn: Callable[[NeuroEvent], bool] | None = None,
    ) -> HandlerSubscription:
        """订阅所有事件（subscribe_all 别名）。"""
        return self.subscribe_all(handler, filter_fn)

    def subscribe_to_domain(
        self,
        domain: str,
        event_type: str,
        handler: EventHandler | AsyncEventHandler,
        priority: int = 0,
        is_async: bool = True,
    ) -> HandlerSubscription:
        """订阅特定领域的事件"""
        subscription = HandlerSubscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            is_async=is_async,
        )

        self._domain_handlers[domain][event_type].append(subscription)
        self._domain_handlers[domain][event_type].sort(key=lambda s: s.priority)

        logger.debug("Subscribed to %s.%s: %s", domain, event_type, handler.__name__)
        return subscription

    def subscribe_all(
        self,
        handler: EventHandler | AsyncEventHandler,
        filter_fn: Callable[[NeuroEvent], bool] | None = None,
    ) -> HandlerSubscription:
        """订阅所有事件（全局处理器）"""
        subscription = HandlerSubscription(
            event_type="*",
            handler=handler,
            filter_fn=filter_fn,
        )

        self._global_handlers.append(subscription)
        logger.debug("Global subscription: %s", handler.__name__)
        return subscription

    def unsubscribe(self, subscription: HandlerSubscription) -> bool:
        """取消订阅"""
        if subscription.event_type in self._handlers:
            if subscription in self._handlers[subscription.event_type]:
                self._handlers[subscription.event_type].remove(subscription)
                return True
        return False

    def get_stats(self) -> dict[str, Any]:
        """获取总线统计信息"""
        return {
            "published": self._published_count,
            "processed": self._processed_count,
            "errors": self._error_count,
            "dropped": self._dropped_count,
            "queue_size": self._event_queue.size(),
            "handlers": sum(len(h) for h in self._handlers.values()),
            "global_handlers": len(self._global_handlers),
            "running": self._running,
            "reliability": self.get_reliability_status(),
        }

    def get_reliability_status(self) -> dict[str, Any]:
        """总线级可靠性层是否启用（与 /api/neurobus 诊断一致）。"""
        out: dict[str, Any] = {
            "fhd_env": os.environ.get("FHD_ENV", ""),
            "dedup": self._rel_dedup is not None,
            "rate_limit": self._rel_rate is not None,
            "circuit_breaker": self._rel_circuit is not None,
            "lifeline": self._rel_lifeline is not None,
            "tracer": self._rel_tracer is not None,
            "sla_log": self._rel_sla_log,
            "sla_controller": self._rel_sla_controller is not None,
            "retry": self._rel_retry_handler is not None,
            "dlq_auto": self._dlq_integration is not None,
            "redis_pubsub": self._redis_bridge is not None,
            "trace_sample_rate": (
                _neuro_trace_sample_rate() if self._rel_tracer is not None else None
            ),
        }
        if self._rel_circuit is not None:
            try:
                out["circuit_open"] = not self._rel_circuit.can_execute()
            except RECOVERABLE_ERRORS:
                out["circuit_open"] = None
        return out

    def summarize_subscriptions(self) -> dict[str, Any]:
        """Startup diagnostics: handler counts per event type (flat + per-domain)."""
        flat = {k: len(v) for k, v in sorted(self._handlers.items())}
        domain_nested: dict[str, dict[str, int]] = {}
        for d, evs in self._domain_handlers.items():
            domain_nested[d] = {e: len(subs) for e, subs in sorted(evs.items())}
        return {
            "flat_event_handlers": flat,
            "domain_handlers": domain_nested,
            "global_handlers": len(self._global_handlers),
        }

    @property
    def registered_domains(self) -> list[str]:
        """已注册神经域名称（来自 DomainRegistry，供启动日志与健康检查）。"""
        try:
            from app.neuro_bus.domains.base import get_domain_registry

            return cast("list[str]", get_domain_registry().list_domains())
        except RECOVERABLE_ERRORS:
            return []
