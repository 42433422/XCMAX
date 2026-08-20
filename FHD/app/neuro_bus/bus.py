"""
NeuroBus - 神经总线核心实现

提供高性能的异步事件总线，支持：
- 发布/订阅模式
- 优先级队列（5级优先级）
- 同步/异步处理器
- 事件持久化与回放
- 领域隔离
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from app.neuro_bus.bus_primitives import (
    HandlerSubscription,
    PriorityEventQueue,
    _neuro_env_flag,
    _neuro_reliability_wanted,
    _should_trace_event,
)
from app.neuro_bus.bus_primitives import (
    _deployment_is_production as _deployment_is_production,
)
from app.neuro_bus.bus_primitives import (
    _deployment_is_staging as _deployment_is_staging,
)
from app.neuro_bus.bus_primitives import (
    _neuro_trace_sample_rate as _neuro_trace_sample_rate,
)
from app.neuro_bus.bus_subscriptions import NeuroBusSubscriptionsMixin
from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.neuro_bus.transports.redis_pubsub import RedisPubSubBridge
    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge


class NeuroBus(NeuroBusSubscriptionsMixin):
    """
    神经总线 - 高性能事件总线实现

    特性：
    - 多优先级事件队列
    - 同步/异步处理器支持
    - 领域隔离
    - 事件过滤
    - 处理器统计
    """

    def __init__(
        self,
        max_queue_size: int = 10000,
        worker_threads: int = 4,
        enable_metrics: bool = True,
    ):
        self._event_queue = PriorityEventQueue(max_size=max_queue_size)
        self._handlers: dict[str, list[HandlerSubscription]] = defaultdict(list)
        self._domain_handlers: dict[str, dict[str, list[HandlerSubscription]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._global_handlers: list[HandlerSubscription] = []

        # 执行器
        self._worker_threads = worker_threads
        self._executor = ThreadPoolExecutor(
            max_workers=worker_threads, thread_name_prefix="neurobus_"
        )
        self._loop: asyncio.AbstractEventLoop | None = None

        # 运行状态
        self._running = False
        self._shutdown = False
        self._processing_task: asyncio.Task | None = None

        # 统计
        self._enable_metrics = enable_metrics
        self._published_count = 0
        self._processed_count = 0
        self._error_count = 0
        self._dropped_count = 0
        # Event to signal new items in the queue; created when start() runs on the event loop.
        self._event_available: asyncio.Event | None = None

        # 事件持久化（可选）
        self._event_buffer: list[dict[str, Any]] = []
        self._enable_persistence = False

        # 可选可靠性层：未设环境变量时，FHD_ENV=staging/production 默认开启（生产安全优先）。
        # 显式设置 env 时以变量为准；开发环境默认关闭。详见 .env.example。
        self._rel_dedup = None
        self._rel_rate = None
        self._rel_circuit = None
        self._rel_lifeline = None
        self._rel_tracer = None
        self._rel_sla_log = _neuro_reliability_wanted(
            "XCAGI_NEURO_BUS_SLA_LOG", staging_default=False
        )
        self._rel_sla_controller = None
        if self._rel_sla_log:
            from app.neuro_bus.sla_controller import SLAController

            self._rel_sla_controller = SLAController()
        self._rel_retry = _neuro_reliability_wanted("XCAGI_NEURO_BUS_RETRY", staging_default=False)
        self._rel_retry_handler = None
        if self._rel_retry:
            from app.neuro_bus.retry_handler import get_retry_handler

            self._rel_retry_handler = get_retry_handler()
        self._trace_by_event_id: dict[str, str] = {}
        if _neuro_reliability_wanted("XCAGI_NEURO_BUS_DEDUP", staging_default=True):
            from app.neuro_bus.deduplicator import EventDeduplicator

            self._rel_dedup = EventDeduplicator()
        if _neuro_reliability_wanted("XCAGI_NEURO_BUS_RATE_LIMIT", staging_default=False):
            from app.neuro_bus.rate_limiter import NeuroRateLimiter

            self._rel_rate = NeuroRateLimiter()
        if _neuro_reliability_wanted("XCAGI_NEURO_BUS_CIRCUIT", staging_default=True):
            from app.neuro_bus.circuit_breaker import CircuitBreaker

            self._rel_circuit = CircuitBreaker("neuro_dispatch")
        if _neuro_reliability_wanted("XCAGI_NEURO_BUS_LIFELINE", staging_default=False):
            from app.neuro_bus.lifeline import Lifeline

            self._rel_lifeline = Lifeline()
        if _neuro_reliability_wanted("XCAGI_NEURO_BUS_TRACE", staging_default=False):
            from app.neuro_bus.tracer import NeuroTracer

            self._rel_tracer = NeuroTracer()

        # handler 异常时自动写入全局 DLQ（与 initializer 中 DLQ 实例一致）
        self._dlq_integration = None
        if _neuro_reliability_wanted("XCAGI_NEURO_BUS_DLQ_AUTO", staging_default=False):
            from app.neuro_bus.dead_letter_queue import (
                NeuroBusDLQIntegration,
                get_dead_letter_queue,
            )

            self._dlq_integration = NeuroBusDLQIntegration(get_dead_letter_queue())

        self._redis_bridge: RedisStreamsBridge | RedisPubSubBridge | None = None
        if os.environ.get("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "").strip().lower() == "streams":
            from app.neuro_bus.transports.redis_pubsub import _resolve_redis_url
            from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

            url = _resolve_redis_url()
            if url:
                try:
                    import redis

                    redis_client = redis.from_url(url, decode_responses=False)
                    self._redis_bridge = RedisStreamsBridge(bus=self, redis_client=redis_client)
                    logger.info("NeuroBus transport: redis_streams")
                except RECOVERABLE_ERRORS as exc:
                    logger.error("NeuroBus Redis Streams init failed: %s", exc)
            else:
                logger.warning("NeuroBus Redis Streams: no REDIS URL configured")
        elif _neuro_env_flag("XCAGI_NEURO_BUS_REDIS_PUBSUB"):
            from app.neuro_bus.transports.redis_pubsub import RedisPubSubBridge

            self._redis_bridge = RedisPubSubBridge(self)
            logger.info("NeuroBus transport: redis_pubsub")

        logger.info("NeuroBus initialized")

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """启动总线"""
        if self._running:
            return

        # 重启安全：一次 stop() 会 shutdown 线程池；若在修复后重新 start()，
        # 需重建执行器，否则事件处理（run_in_executor）会在已关闭的池上抛错。
        # 供健康监控的固定动作 neuro_bus.ensure_running.v1 在重启后真正可运行。
        if getattr(self._executor, "_shutdown", False):
            self._executor = ThreadPoolExecutor(
                max_workers=self._worker_threads, thread_name_prefix="neurobus_"
            )

        self._running = True
        self._shutdown = False
        self._loop = asyncio.get_running_loop()
        # create an Event bound to the running loop to avoid loop-less creation errors
        self._event_available = asyncio.Event()

        # 启动事件处理循环
        self._processing_task = asyncio.create_task(self._processing_loop())

        if self._redis_bridge is not None:
            self._redis_bridge.start()

        logger.info("NeuroBus started")

    async def stop(self):
        """停止总线"""
        if not self._running:
            return

        self._shutdown = True
        self._running = False

        if self._redis_bridge is not None:
            self._redis_bridge.stop()

        # 取消处理任务
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        # 关闭线程池
        self._executor.shutdown(wait=True)
        # Wake processing loop if waiting on the event
        if getattr(self, "_event_available", None):
            try:
                self._event_available.set()
            except RECOVERABLE_ERRORS:
                pass

        logger.info("NeuroBus stopped")

    async def _processing_loop(self):
        """事件处理主循环"""
        while not self._shutdown:
            try:
                # 获取事件
                event = self._event_queue.get()

                if event is None:
                    # 队列为空：优先等待由 publish() 设置的 Event，避免忙轮询
                    ev = getattr(self, "_event_available", None)
                    if ev is not None:
                        # clear then wait with a timeout to periodically check _shutdown
                        ev.clear()
                        try:
                            await asyncio.wait_for(ev.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                    else:
                        # fallback: tiny sleep if no event available
                        await asyncio.sleep(0.001)
                    continue

                # 检查超时
                if event.is_expired():
                    logger.warning("Event expired: %s", event)
                    self._dropped_count += 1
                    continue

                # 分发事件
                await self._dispatch_event(event)

            except asyncio.CancelledError:
                break
            except RECOVERABLE_ERRORS as e:
                logger.exception("Error in processing loop: %s", e)
                self._error_count += 1

    async def _dispatch_event(self, event: NeuroEvent):
        """分发事件到处理器"""
        handlers_called = 0
        any_failed = False
        if self._rel_sla_controller is not None:
            self._rel_sla_controller.start_monitoring(event)

        # 1. 特定类型处理器
        event_type = event.event_type
        if event_type in self._handlers:
            for subscription in self._handlers[event_type]:
                if subscription.should_handle(event):
                    ok = await self._call_handler(subscription, event)
                    handlers_called += 1
                    if not ok:
                        any_failed = True

        # 2. 领域特定处理器
        domain = event.metadata.domain
        if domain and domain in self._domain_handlers:
            domain_handlers = self._domain_handlers[domain]
            if event_type in domain_handlers:
                for subscription in domain_handlers[event_type]:
                    if subscription.should_handle(event):
                        ok = await self._call_handler(subscription, event)
                        handlers_called += 1
                        if not ok:
                            any_failed = True

        # 3. 全局处理器（监听所有事件）
        for subscription in self._global_handlers:
            if subscription.should_handle(event):
                ok = await self._call_handler(subscription, event)
                handlers_called += 1
                if not ok:
                    any_failed = True

        if handlers_called == 0:
            logger.debug("No handlers for event: %s", event)

        self._processed_count += 1

        if self._rel_dedup is not None:
            if any_failed:
                self._rel_dedup.remove(event)
            else:
                self._rel_dedup.mark_processed(event)

        eid = event.metadata.event_id
        if self._rel_sla_controller is not None:
            self._rel_sla_controller.finish_monitoring(eid)
        sid = self._trace_by_event_id.pop(eid, None)
        if sid and self._rel_tracer is not None:
            from app.neuro_bus.tracer import SpanStatus

            self._rel_tracer.end_span(sid, SpanStatus.ERROR if any_failed else SpanStatus.OK)

    async def _call_handler(self, subscription: HandlerSubscription, event: NeuroEvent) -> bool:
        """调用处理器；返回是否成功（无异常）。"""
        if self._rel_circuit is not None and not self._rel_circuit.can_execute():
            logger.warning("NeuroBus circuit open; skipping handler for %s", event.event_type)
            return False

        async def _invoke() -> None:
            if subscription.is_async:
                await subscription.handler(event)
            else:
                await asyncio.get_running_loop().run_in_executor(
                    self._executor, subscription.handler, event
                )

        retry_count = 0
        try:
            if self._rel_retry_handler is not None:
                domain = event.metadata.domain or "default"
                retry_handler = self._rel_retry_handler.get_handler(domain)
                try:
                    await retry_handler.execute(
                        _invoke,
                        operation_name=getattr(subscription.handler, "__name__", "handler"),
                    )
                except RECOVERABLE_ERRORS:
                    retry_count = retry_handler._config.max_retries  # noqa: SLF001
                    raise
            else:
                await _invoke()
            subscription.record_call(success=True)
            if self._rel_circuit is not None:
                self._rel_circuit.record_success()

        except RECOVERABLE_ERRORS as e:
            logger.exception("Handler error for event %s: %s", event, e)
            subscription.record_call(success=False)
            self._error_count += 1
            if self._rel_circuit is not None:
                self._rel_circuit.record_failure()
            if self._dlq_integration is not None:
                try:
                    self._dlq_integration.handle_failure(
                        event,
                        e,
                        retry_count=retry_count,
                        handler_name=getattr(subscription.handler, "__name__", None),
                    )
                except RECOVERABLE_ERRORS as dlq_exc:
                    logger.exception("NeuroBus DLQ enqueue failed: %s", dlq_exc)
            return False
        return True

    def _preflight_publish(self, event: NeuroEvent) -> bool:
        if self._rel_dedup is not None:
            if not self._rel_dedup.mark_processing(event):
                return False
        if self._rel_rate is not None:
            if not self._rel_rate.check_rate(event):
                if self._rel_dedup is not None:
                    self._rel_dedup.remove(event)
                return False
        if self._rel_lifeline is not None:
            qd = self._event_queue.size()
            if not self._rel_lifeline.should_process(event, qd):
                if self._rel_dedup is not None:
                    self._rel_dedup.remove(event)
                return False
        return True

    def publish(self, event: NeuroEvent) -> bool:
        """
        发布事件

        Returns:
            是否成功加入队列
        """
        if not self._running or self._shutdown:
            logger.warning("Cannot publish: NeuroBus not running")
            return False

        if not self._preflight_publish(event):
            return False

        # 持久化（如果启用）
        if self._enable_persistence:
            self._event_buffer.append(event.to_dict())

        span_id = None
        if self._rel_tracer is not None and _should_trace_event():
            sp = self._rel_tracer.start_span(
                f"neuro.publish:{event.event_type}",
                tags={
                    "event_type": event.event_type,
                    "event_id": event.metadata.event_id,
                },
            )
            span_id = sp.span_id
            self._trace_by_event_id[event.metadata.event_id] = span_id

        success = self._event_queue.put(event)
        if success:
            self._published_count += 1
            if self._redis_bridge is not None and not event.payload.get("_neuro_remote_ingest"):
                self._redis_bridge.publish_remote(event)
            # wake processing loop if it's waiting
            ev = getattr(self, "_event_available", None)
            if ev is not None:
                try:
                    ev.set()
                except RECOVERABLE_ERRORS:
                    # ignore any loop-related errors
                    pass
        else:
            if self._rel_dedup is not None:
                self._rel_dedup.remove(event)
            if span_id is not None and self._rel_tracer is not None:
                from app.neuro_bus.tracer import SpanStatus

                self._rel_tracer.end_span(span_id, SpanStatus.ERROR)
                self._trace_by_event_id.pop(event.metadata.event_id, None)

        return success

    def ingest_remote_event(self, event: NeuroEvent) -> bool:
        """跨进程 Redis 订阅 ingest — 不再向外广播。"""
        if not self._running or self._shutdown:
            return False
        if not self._preflight_publish(event):
            return False
        success = self._event_queue.put(event)
        if success:
            self._published_count += 1
            ev = getattr(self, "_event_available", None)
            if ev is not None:
                try:
                    ev.set()
                except RECOVERABLE_ERRORS:
                    pass
        return success


# 全局 NeuroBus 实例
_neuro_bus: NeuroBus | None = None
_neuro_bus_lock = threading.Lock()


def get_neuro_bus() -> NeuroBus:
    global _neuro_bus
    if _neuro_bus is None:
        with _neuro_bus_lock:
            if _neuro_bus is None:
                _neuro_bus = NeuroBus()
    return _neuro_bus


def set_neuro_bus(bus: NeuroBus):
    """设置全局 NeuroBus 实例"""
    global _neuro_bus
    _neuro_bus = bus
