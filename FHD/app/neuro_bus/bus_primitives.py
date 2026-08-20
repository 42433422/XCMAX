"""Configuration helpers and queue primitives for NeuroBus."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from heapq import heappop, heappush
from typing import cast

from app.neuro_bus.events.base import AsyncEventHandler, EventHandler, NeuroEvent

logger = logging.getLogger(__name__)


def _neuro_env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _deployment_is_staging() -> bool:
    """k8s/CI：设置 FHD_ENV=staging；与本仓库 staging 部署约定一致。"""
    return os.environ.get("FHD_ENV", "").strip().lower() == "staging"


def _deployment_is_production() -> bool:
    """k8s/CI：设置 FHD_ENV=production；生产环境安全优先，可靠性机制默认全开。"""
    return os.environ.get("FHD_ENV", "").strip().lower() == "production"


def _neuro_trace_sample_rate() -> float:
    """生产 trace 采样率，避免洪泛。XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE 默认 0.1。"""
    raw = os.environ.get("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "0.1").strip()
    try:
        rate = float(raw)
    except ValueError:
        rate = 0.1
    return max(0.0, min(1.0, rate))


def _should_trace_event() -> bool:
    """未启用 tracer 时忽略；启用后按采样率决定是否记录 span。"""
    rate = _neuro_trace_sample_rate()
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    import random

    return random.random() < rate


def _neuro_reliability_wanted(
    env_name: str, *, staging_default: bool, production_default: bool = True
) -> bool:
    """
    可靠性层开关：显式设置环境变量时以变量为准；未设置时在 staging/production
    采用默认值（生产安全优先，production_default 默认 True）。
    """
    raw = os.environ.get(env_name)
    if raw is not None and str(raw).strip() != "":
        return _neuro_env_flag(env_name)
    if _deployment_is_staging():
        return staging_default
    if _deployment_is_production():
        return production_default
    return False


class HandlerSubscription:
    """处理器订阅信息"""

    def __init__(
        self,
        event_type: str,
        handler: EventHandler | AsyncEventHandler,
        priority: int = 0,
        is_async: bool = True,
        filter_fn: Callable[[NeuroEvent], bool] | None = None,
    ):
        self.event_type = event_type
        self.handler = handler
        self.priority = priority
        self.is_async = is_async
        self.filter_fn = filter_fn
        self.created_at = time.time()
        self.call_count = 0
        self.error_count = 0

    def should_handle(self, event: NeuroEvent) -> bool:
        """检查是否应该处理该事件"""
        if self.filter_fn:
            return self.filter_fn(event)
        return True

    def record_call(self, success: bool = True):
        """记录调用统计"""
        self.call_count += 1
        if not success:
            self.error_count += 1

    @property
    def error_rate(self) -> float:
        """计算错误率"""
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count


class PriorityEventQueue:
    """
    优先级事件队列

    使用堆实现的高效优先级队列
    """

    def __init__(self, max_size: int = 10000):
        self._queue: list[tuple] = []  # (priority, timestamp, event_id, event)
        self._event_ids: set[str] = set()
        self._max_size = max_size
        self._lock = threading.RLock()
        self._dropped_count = 0

    def put(self, event: NeuroEvent) -> bool:
        """
        放入事件

        Returns:
            是否成功放入（队列满时丢弃低优先级事件）
        """
        with self._lock:
            # 同一 event_id 已在队列中则无法入队；自动 remint 避免静默丢件导致上游阻塞
            for attempt in range(4):
                if event.metadata.event_id not in self._event_ids:
                    break
                if attempt == 3:
                    logger.error(
                        "NeuroBus: event_id %s still conflicts after remint; dropping",
                        event.metadata.event_id,
                    )
                    self._dropped_count += 1
                    return False
                logger.warning(
                    "NeuroBus: duplicate event_id %s in queue; reminting (attempt %s)",
                    event.metadata.event_id,
                    attempt + 1,
                )
                event.remint_queue_identity()

            # 队列满时处理
            if len(self._queue) >= self._max_size:
                # 如果新事件优先级比队列中最低的高，则替换
                if self._queue and event.priority.value < self._queue[0][0]:
                    _, _, _, old_event = heappop(self._queue)
                    self._event_ids.discard(old_event.metadata.event_id)
                    self._dropped_count += 1
                    logger.warning("Dropped low priority event due to queue full: %s", old_event)
                else:
                    self._dropped_count += 1
                    logger.warning("Queue full, dropping event: %s", event)
                    return False

            # 放入队列 (优先级数值小的在前)
            heappush(
                self._queue,
                (event.priority.value, event.metadata.timestamp, event.metadata.event_id, event),
            )
            self._event_ids.add(event.metadata.event_id)
            return True

    def get(self) -> NeuroEvent | None:
        """取出最高优先级事件"""
        with self._lock:
            if not self._queue:
                return None
            _, _, event_id, event = heappop(self._queue)
            self._event_ids.discard(event_id)
            return cast("NeuroEvent | None", event)

    def peek(self) -> NeuroEvent | None:
        """查看最高优先级事件（不取出）"""
        with self._lock:
            if not self._queue:
                return None
            return cast("NeuroEvent | None", self._queue[0][3])

    def size(self) -> int:
        """队列大小"""
        with self._lock:
            return len(self._queue)

    def clear(self):
        """清空队列"""
        with self._lock:
            self._queue.clear()
            self._event_ids.clear()
