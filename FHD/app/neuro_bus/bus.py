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
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from typing import TYPE_CHECKING, Any

from app.neuro_bus.bus_primitives import (
    HandlerSubscription,
    PriorityEventQueue,
    _neuro_env_flag,
    _neuro_reliability_wanted,
    _should_trace_event,
    event_partition_key,
)
from app.neuro_bus.bus_primitives import _deployment_is_production as _deployment_is_production
from app.neuro_bus.bus_primitives import _deployment_is_staging as _deployment_is_staging
from app.neuro_bus.bus_primitives import _neuro_trace_sample_rate as _neuro_trace_sample_rate
from app.neuro_bus.bus_subscriptions import NeuroBusSubscriptionsMixin
from app.neuro_bus.delivery_metrics import record_delivery_metric
from app.neuro_bus.events.events_base import NeuroEvent
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

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
        handler_timeout_sec: float = 5.0,
    ):
        self._event_queue = PriorityEventQueue(
            max_size=max_queue_size,
            partition_key=event_partition_key,
            on_evict=self._discard_event,
        )
        self._handlers: dict[str, list[HandlerSubscription]] = defaultdict(list)
        self._domain_handlers: dict[str, dict[str, list[HandlerSubscription]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._global_handlers: list[HandlerSubscription] = []

        # 执行器
        self._worker_threads = max(1, int(worker_threads))
        self._handler_timeout_sec = max(0.001, float(handler_timeout_sec))
        self._executor = ThreadPoolExecutor(
            max_workers=self._worker_threads, thread_name_prefix="neurobus_"
        )
        self._inflight: set[asyncio.Task] = set()
        self._active_partitions: set = set()
        self._sync_futures: set[Future] = set()
        self._handler_timeout_count = 0
        self._loop: asyncio.AbstractEventLoop | None = None

        # 运行状态
        self._running = False
        self._stopping = False
        self._stop_task: asyncio.Task | None = None
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
        if self._stopping:
            raise RuntimeError("NeuroBus is stopping")
        if self._running:
            return

        # 重启安全：一次 stop() 会 shutdown 线程池；若在修复后重新 start()，
        # 需重建执行器，否则事件处理（run_in_executor）会在已关闭的池上抛错。
        # 供健康监控的固定动作 neuro_bus.ensure_running.v1 在重启后真正可运行。
        if any(not future.done() for future in tuple(self._sync_futures)):
            raise RuntimeError("NeuroBus still has stopping synchronous handlers")
        if getattr(self._executor, "_shutdown", False):
            self._executor = ThreadPoolExecutor(
                max_workers=self._worker_threads, thread_name_prefix="neurobus_"
            )

        self._running = True
        self._stop_task = None
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
        """Share one cleanup task; cancellation of a caller cannot interrupt it."""
        if self._running:
            self._stopping = True
            self._shutdown = True
            self._running = False
            self._stop_task = asyncio.create_task(self._finish_stop())
        if self._stop_task is not None:
            await asyncio.shield(self._stop_task)

    async def _finish_stop(self):
        try:
            if self._redis_bridge is not None:
                try:
                    self._redis_bridge.stop()
                except BOUNDARY_ERRORS:
                    logger.exception("Error stopping NeuroBus transport")
            if self._processing_task:
                self._processing_task.cancel()
                await asyncio.gather(self._processing_task, return_exceptions=True)
            for task in tuple(self._inflight):
                task.cancel()
            await asyncio.gather(*self._inflight, return_exceptions=True)
        finally:
            self._inflight.clear()
            self._active_partitions.clear()
            # Threads cannot be killed safely; start() rejects outstanding ones.
            self._executor.shutdown(wait=False, cancel_futures=True)
            while (event := self._event_queue.get()) is not None:
                self._discard_event(event)
            self._stopping = False
            logger.info("NeuroBus stopped")

    def _wake_processor(self) -> None:
        if self._loop is not None and not self._loop.is_closed() and self._event_available:
            self._loop.call_soon_threadsafe(self._event_available.set)

    def _discard_event(self, event: NeuroEvent) -> None:
        self._dropped_count += 1
        record_delivery_metric(self._enable_metrics, "lost")
        if self._rel_dedup is not None:
            self._rel_dedup.remove(event)
        sid = self._trace_by_event_id.pop(event.metadata.event_id, None)
        if sid and self._rel_tracer is not None:
            from app.neuro_bus.tracer import SpanStatus

            self._rel_tracer.end_span(sid, SpanStatus.ERROR)

    async def _process_partition_event(self, event: NeuroEvent) -> None:
        key = event_partition_key(event)
        try:
            await self._dispatch_event(event)
        except BOUNDARY_ERRORS:
            self._error_count += 1
            logger.exception("Error dispatching %s", event)
        finally:
            self._active_partitions.discard(key)
            self._wake_processor()

    async def _processing_loop(self):
        """Admit at most worker_threads events; never queue work in the executor."""
        while not self._shutdown:
            try:
                if self._event_available is None:
                    self._event_available = asyncio.Event()
                self._event_available.clear()
                # Completed tasks remain in this bounded set until their result
                # is observed; exceptions must never become unhandled task noise.
                for task in tuple(self._inflight):
                    if task.done():
                        self._inflight.remove(task)
                        task.result()
                while len(self._inflight) < self._worker_threads:
                    event = self._event_queue.get(self._active_partitions)
                    if event is None:
                        break
                    if event.is_expired():
                        self._discard_event(event)
                        continue
                    self._active_partitions.add(event_partition_key(event))
                    self._inflight.add(asyncio.create_task(self._process_partition_event(event)))
                await self._event_available.wait()
            except asyncio.CancelledError:
                break
            except RECOVERABLE_ERRORS:
                logger.exception("Error in processing loop")
                self._error_count += 1

    async def _dispatch_event(self, event: NeuroEvent):
        """分发事件到处理器"""
        handlers_called = 0
        any_failed = False
        if self._rel_sla_controller is not None:
            self._rel_sla_controller.start_monitoring(event)

        # Keep subscription order within an event. Parallelism is between
        # independent entities, never between writes to one entity.
        subscriptions = [
            *self._handlers.get(event.event_type, ()),
            *self._domain_handlers.get(event.metadata.domain, {}).get(event.event_type, ()),
            *self._global_handlers,
        ]
        completed = False
        try:
            for subscription in subscriptions:
                if subscription.should_handle(event):
                    ok = await self._call_handler(subscription, event)
                    handlers_called += 1
                    any_failed |= not ok
            completed = True
        finally:
            # Cancellation also releases dedup/tracing state before propagating.
            self._finish_event(event, failed=not completed or any_failed)

        if handlers_called == 0:
            logger.debug("No handlers for event: %s", event)

        self._processed_count += 1

    def _finish_event(self, event: NeuroEvent, *, failed: bool) -> None:
        if self._rel_dedup is not None:
            if failed:
                self._rel_dedup.remove(event)
            else:
                self._rel_dedup.mark_processed(event)
        eid = event.metadata.event_id
        if self._rel_sla_controller is not None:
            self._rel_sla_controller.finish_monitoring(eid)
        sid = self._trace_by_event_id.pop(eid, None)
        if sid and self._rel_tracer is not None:
            from app.neuro_bus.tracer import SpanStatus

            self._rel_tracer.end_span(sid, SpanStatus.ERROR if failed else SpanStatus.OK)

    async def _call_handler(self, subscription: HandlerSubscription, event: NeuroEvent) -> bool:
        """调用处理器；返回是否成功（无异常）。"""
        if self._rel_circuit is not None and not self._rel_circuit.can_execute():
            logger.warning("NeuroBus circuit open; skipping handler for %s", event.event_type)
            return False

        sync_future: Future | None = None

        async def _invoke() -> None:
            nonlocal sync_future
            if subscription.is_async:
                await subscription.handler(event)
            else:
                sync_future = self._executor.submit(copy_context().run, subscription.handler, event)
                self._sync_futures.add(sync_future)
                sync_future.add_done_callback(self._sync_futures.discard)
                await asyncio.shield(asyncio.wrap_future(sync_future))

        retry_count = 0
        try:
            async with asyncio.timeout(self._handler_timeout_sec):
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

        except BOUNDARY_ERRORS as e:  # Subscriber/plugin isolation boundary.
            if isinstance(e, TimeoutError):
                self._handler_timeout_count += 1
                # Retain this partition and admission slot until the synchronous
                # side effect ends. Retrying/releasing on timeout would overlap it.
                if sync_future is not None and not sync_future.done():
                    try:
                        await asyncio.shield(asyncio.wrap_future(sync_future))
                    except RECOVERABLE_ERRORS:
                        pass
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
                    record_delivery_metric(self._enable_metrics, "dead_lettered")
                except RECOVERABLE_ERRORS as dlq_exc:
                    logger.exception("NeuroBus DLQ enqueue failed: %s", dlq_exc)
                    record_delivery_metric(self._enable_metrics, "lost")
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
            record_delivery_metric(self._enable_metrics, "lost")
            return False

        if not self._preflight_publish(event):
            record_delivery_metric(self._enable_metrics, "lost")
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
            record_delivery_metric(self._enable_metrics, "published")
            if self._redis_bridge is not None and not event.payload.get("_neuro_remote_ingest"):
                self._redis_bridge.publish_remote(event)
            self._wake_processor()
        else:
            record_delivery_metric(self._enable_metrics, "lost")
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
            record_delivery_metric(self._enable_metrics, "lost")
            return False
        if not self._preflight_publish(event):
            record_delivery_metric(self._enable_metrics, "lost")
            return False
        success = self._event_queue.put(event)
        if success:
            self._published_count += 1
            record_delivery_metric(self._enable_metrics, "published")
            self._wake_processor()
        else:
            self._discard_event(event)
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
