"""Public dead-letter API with explicit persistence, retry and replay components."""

from __future__ import annotations

import asyncio
import hashlib as hashlib
import json as json
import logging
import random
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path as Path
from typing import Any, Protocol
from uuid import uuid4

from app.neuro_bus.events.events_base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .storage.dead_letter_management import DeadLetterManagement
from .storage.dead_letter_policies import AlertDelivery, GroupedAlerts, ReplayLedger
from .storage.dead_letter_replay import ReplayDelivery, ReplaySchedule, ReplaySchedulePorts
from .storage.dead_letter_repository import (
    DeadLetterRepository,
    DeadLetterState,
    initialize_dead_letters,
)
from .storage.replay_claim import ReplayClaim
from .storage.sqlite import SQLiteOwner, StorageRuntime

logger = logging.getLogger(__name__)
RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 30.0


def _runtime() -> StorageRuntime:
    return StorageRuntime(
        lambda: datetime,
        lambda: uuid4().hex[:12],
        lambda: logger,
        lambda: RECOVERABLE_ERRORS,
        lambda seconds: time.sleep(seconds),
        lambda: time.time(),
    )


class DeadLetterReason(Enum):
    """进入死信队列的原因"""

    RETRY_EXHAUSTED = "retry_exhausted"
    UNRECOVERABLE = "unrecoverable"
    TIMEOUT = "timeout"
    INVALID_PAYLOAD = "invalid_payload"
    HANDLER_NOT_FOUND = "handler_not_found"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class DeadLetterEntry:
    """死信条目"""

    entry_id: str
    original_event: NeuroEvent
    reason: DeadLetterReason
    error_message: str
    error_stack: str | None
    retry_count: int
    first_failure_time: datetime
    last_failure_time: datetime
    handler_name: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        """条目年龄（秒）"""
        return (datetime.now() - self.first_failure_time).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """序列化"""
        return {
            "entry_id": self.entry_id,
            "original_event": {
                "event_id": self.original_event.metadata.event_id,
                "event_type": self.original_event.event_type,
                "payload": self.original_event.payload,
                "timestamp": self.original_event.metadata.timestamp,
            },
            "reason": self.reason.value,
            "error_message": self.error_message,
            "error_stack": self.error_stack,
            "retry_count": self.retry_count,
            "first_failure_time": self.first_failure_time.isoformat(),
            "last_failure_time": self.last_failure_time.isoformat(),
            "handler_name": self.handler_name,
            "metadata": self.metadata,
            "age_seconds": self.age_seconds,
        }


class ReplayDeduplicator(ReplayLedger):
    """Public fingerprint ledger; a supplied connection remains caller-owned."""

    DEFAULT_TTL_SECONDS = 86400.0

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        lock: threading.RLock | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        """
        Args:
            conn: SQLITE 连接；None 表示内存模式
            lock: 外部 RLock（与 DeadLetterQueue 共享）
            ttl_seconds: 指纹保留时间（秒）
        """
        super().__init__(_runtime(), conn, lock, ttl_seconds)


class AlertSuppressor(GroupedAlerts):
    """Public alert policy with the existing patchable wall clock."""

    def __init__(self, suppress_window: float = 300.0, threshold: int = 1) -> None:
        """
        Args:
            suppress_window: 抑制窗口（秒，默认 5 分钟）
            threshold: 触发告警的最小事件数
        """
        super().__init__(_runtime(), suppress_window, threshold)

    @staticmethod
    def make_key(reason: DeadLetterReason, event_type: str) -> str:
        """生成分组键。"""
        return GroupedAlerts.make_key(reason, event_type)

    def record_and_check(self, reason: DeadLetterReason, event_type: str) -> tuple[bool, int]:
        """记录事件并返回是否告警及窗口内同类事件数。"""
        return super().record_and_check(reason, event_type)


class DeadLetterQueue:
    """Failed event persistence, supervised replay and grouped alert delivery."""

    def __init__(
        self,
        max_size: int = 10000,
        retention_hours: int = 168,
        storage_path: str | None = None,
        alert_suppress_window: float = 300.0,
        alert_threshold: int = 1,
    ) -> None:
        """
        Args:
            max_size: 最大条目数
            retention_hours: 保留时间（小时，默认 7 天）
            storage_path: SQLITE 持久化路径；None 表示纯内存模式（默认）
            alert_suppress_window: 告警抑制窗口（秒，默认 5 分钟）
            alert_threshold: 触发告警的最小同类事件数（默认 1）
        """
        self._max_size = max_size
        self._retention_seconds = retention_hours * 3600
        self._storage_path = storage_path
        self._lock = threading.RLock()
        self._storage = SQLiteOwner(self._lock)
        self._state = DeadLetterState()
        self._entries = self._state.entries
        self._stats = self._state.stats
        self._alert_callbacks: list[Callable[[DeadLetterEntry], None]] = []
        self._replay_callbacks: list[Callable[[NeuroEvent], None]] = []
        self._replay_paused = False
        self._runtime = _runtime()
        initialized = False
        try:
            if storage_path is not None:
                self._init_sqlite(storage_path)
            self._deduplicator = ReplayDeduplicator(conn=self._conn, lock=self._lock)
            self._alert_suppressor = AlertSuppressor(
                suppress_window=alert_suppress_window, threshold=alert_threshold
            )
            self._repository = DeadLetterRepository(
                self._storage,
                self._state,
                self._runtime,
                max_size,
                DeadLetterEntry,
                DeadLetterReason,
            )
            self._management = DeadLetterManagement(
                self._repository, self._retention_seconds, lambda: random.random()
            )
            self._alerts = AlertDelivery(
                self._alert_suppressor, self._alert_callbacks, self._runtime
            )
            self._delivery = ReplayDelivery(
                ReplayClaim(storage_path),
                lambda entry_id: self.dequeue(entry_id),
                self._deduplicator,
                self._replay_callbacks,
                self._stats,
                self._lock,
                self._runtime,
            )
            self._schedule = ReplaySchedule(
                ReplaySchedulePorts(
                    lambda event_type=None, max_age_seconds=None: self._get_replay_candidates(
                        event_type, max_age_seconds
                    ),
                    lambda entry_id: self.replay(entry_id),
                    lambda: self._is_replay_paused(),
                    lambda: self.pause_replay(),
                    lambda: self._stats["total_entries"],
                ),
                self._runtime,
            )
            initialized = True
        finally:
            if not initialized:
                self._storage.close()
        logger.info(
            "[DeadLetterQueue] 初始化完成 (max_size=%s, retention=%sh, storage=%s, alert_window=%ss, alert_threshold=%s)",
            max_size,
            retention_hours,
            storage_path or "memory",
            alert_suppress_window,
            alert_threshold,
        )

    def _init_sqlite(self, storage_path: str) -> None:
        """初始化 SQLITE 持久化存储"""
        self._storage.open(storage_path, initialize_dead_letters, create_parent=True)
        logger.info("[DeadLetterQueue] SQLITE 持久化已启用: %s", storage_path)

    def _row_to_entry(self, row: sqlite3.Row) -> DeadLetterEntry:
        """将 SQLITE 行转换为 DeadLetterEntry"""
        return self._repository.from_row(row)

    def enqueue(
        self,
        event: NeuroEvent,
        reason: DeadLetterReason,
        error_message: str,
        retry_count: int,
        handler_name: str | None = None,
        error_stack: str | None = None,
    ) -> str:
        """
        将事件加入死信队列

        Returns:
            死信条目 ID
        """
        entry = self._repository.prepare(
            event, reason, error_message, retry_count, handler_name, error_stack
        )
        if self._conn is not None:
            self._enqueue_sqlite(entry)
        else:
            self._repository.insert(entry)
        with self._lock:
            self._stats["total_entries"] += 1
        logger.error(
            "[DeadLetterQueue] 事件进入死信队列: %s (reason=%s, entry_id=%s, retries=%s)",
            event.event_type,
            reason.value,
            entry.entry_id,
            retry_count,
        )
        self._trigger_alert(entry)
        return entry.entry_id

    def _enqueue_sqlite(self, entry: DeadLetterEntry) -> None:
        """SQLITE 模式入队"""
        self._repository.insert(entry)

    def dequeue(self, entry_id: str) -> DeadLetterEntry | None:
        """取出条目（不移除）"""
        return self._repository.get(entry_id)

    def remove(self, entry_id: str) -> bool:
        """移除条目"""
        return self._repository.remove(entry_id)

    def replay(self, entry_id: str) -> tuple[bool, str]:
        """
        重播死信事件

        重播前检查指纹是否已重播，已重播的跳过。

        Returns:
            (是否重播, 跳过原因) - 跳过原因为空字符串表示成功重播；
            找不到条目返回 (False, "entry_not_found")；
            已重播过返回 (False, "already_replayed")；
        当前存在同库回放返回 (False, "replay_in_progress")
        """
        return self._delivery.replay(entry_id)

    def _get_replay_candidates(
        self, event_type: str | None = None, max_age_seconds: float | None = None
    ) -> list[str]:
        """获取待重播的条目 ID 列表（按筛选条件）"""
        return self._repository.replay_candidates(event_type, max_age_seconds)

    def replay_all(
        self,
        event_type: str | None = None,
        max_age_seconds: float | None = None,
        rate_limit_qps: float = 100.0,
        batch_size: int = 100,
    ) -> int:
        """
        批量重播（分批 + 限流）

        Args:
            event_type: 筛选特定事件类型
            max_age_seconds: 最大年龄筛选
            rate_limit_qps: 重播速率上限（QPS），默认 100
            batch_size: 每批重播数量，批间 sleep

        Returns:
            重播数量
        """
        return self._schedule.all(event_type, max_age_seconds, rate_limit_qps, batch_size)

    def pause_replay(self) -> None:
        """暂停重播（影响 replay_all / replay_with_progress / replay_gradual）"""
        with self._lock:
            self._replay_paused = True
        logger.info("[DeadLetterQueue] 重播已暂停")

    def resume_replay(self) -> None:
        """恢复重播"""
        with self._lock:
            self._replay_paused = False
        logger.info("[DeadLetterQueue] 重播已恢复")

    def _is_replay_paused(self) -> bool:
        """检查重播是否已暂停"""
        with self._lock:
            return self._replay_paused

    def replay_with_progress(
        self,
        event_type: str | None = None,
        max_age_seconds: float | None = None,
        rate_limit_qps: float = 100.0,
        batch_size: int = 100,
    ) -> Iterator[tuple[int, int, str]]:
        """
        带进度的重播（生成器）

        支持中途取消（pause_replay 后迭代器会在下一个条目前停止）。

        Args:
            event_type: 筛选特定事件类型
            max_age_seconds: 最大年龄筛选
            rate_limit_qps: 重播速率上限（QPS）
            batch_size: 每批重播数量，批间 sleep

        Yields:
            (replayed_count, total_count, current_entry_id)
        """
        yield from self._schedule.with_progress(
            event_type, max_age_seconds, rate_limit_qps, batch_size
        )

    def replay_gradual(
        self,
        event_type: str | None = None,
        stages: list[float] | None = None,
        stage_interval: float = 5.0,
        error_threshold: int = 5,
    ) -> dict[str, Any]:
        """
        灰度重播（分阶段：1% → 10% → 50% → 100%）

        每阶段后检查新增死信数，超阈值自动暂停。

        Args:
            event_type: 筛选特定事件类型
            stages: 灰度阶段列表（默认 [0.01, 0.1, 0.5, 1.0]）
            stage_interval: 阶段间隔秒数
            error_threshold: 新增死信数阈值，超过则自动暂停

        Returns:
            执行报告 dict，含 total / stages_executed / replayed / paused / pause_reason
        """
        return self._schedule.gradual(event_type, stages, stage_interval, error_threshold)

    def resolve_manually(self, entry_id: str, resolution: str, resolved_by: str) -> bool:
        """
        手动解决死信

        用于人工干预后标记为已处理
        """
        return self._management.resolve(entry_id, resolution, resolved_by)

    def cleanup_expired(self) -> int:
        """清理过期条目"""
        return self._management.cleanup_expired()

    def get_all_entries(self) -> list[DeadLetterEntry]:
        """获取所有条目"""
        return self._repository.entries()

    def get_entries_by_reason(self, reason: DeadLetterReason) -> list[DeadLetterEntry]:
        """按原因筛选"""
        return self._repository.entries(reason=reason)

    def get_entries_by_event_type(self, event_type: str) -> list[DeadLetterEntry]:
        """按事件类型筛选"""
        return self._repository.entries(event_type=event_type)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._management.stats()

    def triage_entries(self) -> dict[str, list[str]]:
        """
        死信自动分类（对标 Kafka DLT triage）

        按 reason 分类：
        - retriable: RETRY_EXHAUSTED, TIMEOUT（可重试）
        - fixable: INVALID_PAYLOAD, HANDLER_NOT_FOUND（需修复后重播）
        - poison: UNRECOVERABLE, CIRCUIT_BREAKER（毒药消息，不宜重播）

        Returns:
            {"retriable": [...], "fixable": [...], "poison": [...]}
        """
        return self._management.triage()

    def on_alert(self, callback: Callable[[DeadLetterEntry], None]) -> None:
        """注册告警回调"""
        self._alert_callbacks.append(callback)

    def on_replay(self, callback: Callable[[NeuroEvent], None]) -> None:
        """注册重播回调"""
        self._replay_callbacks.append(callback)

    def _trigger_alert(self, entry: DeadLetterEntry) -> None:
        """
        触发告警（含抑制逻辑）

        按 (reason, event_type) 分组，同组 suppress_window 内只告警一次。
        告警内容含"X 条同类失败"。
        """
        self._alerts.trigger(entry)

    def silence_alerts(self, duration_seconds: float) -> None:
        """
        手动静默告警指定时长

        Args:
            duration_seconds: 静默秒数
        """
        self._alert_suppressor.silence(duration_seconds)
        logger.info("[DeadLetterQueue] 告警已静默 %s 秒", duration_seconds)

    def get_alert_stats(self) -> dict[str, Any]:
        """
        获取告警统计（按组分类）

        Returns:
            统计字典，含各组的 fired/suppressed/total 计数、
            是否处于静默状态、抑制窗口和阈值
        """
        return self._alert_suppressor.get_stats()

    def schedule_retry(
        self, entry_id: str, base: float = RETRY_BASE_DELAY, cap: float = RETRY_MAX_DELAY
    ) -> float | None:
        """
        计算并安排下一次重试的退避时间（Non-blocking retry，参考 Kafka DLT 设计）

        - 退避公式：delay = min(base * (2 ** retry_count), cap) * (0.5 + random() * 0.5)
        - jitter 范围 ±25%（实际为 0.5x ~ 1.0x 的乘数）
        - 更新 last_failure_time 和 retry_count
        - 调用方负责按返回的 delay 秒数调度实际重试

        Args:
            entry_id: 死信条目 ID
            base: 基础退避秒数（默认 0.5s）
            cap: 最大退避秒数（默认 30s）

        Returns:
            退避秒数；若条目不存在返回 None
        """
        return self._management.schedule_retry(entry_id, base, cap)

    def _evict_oldest(self) -> None:
        """驱逐最老的条目"""
        self._repository.evict_oldest()

    @property
    def _conn(self) -> sqlite3.Connection | None:
        return self._storage.connection

    def close(self) -> None:
        """Release the owned SQLite connection; subsequent SQLite operations fail."""
        self._storage.close()


class EventPublisher(Protocol):
    def publish(self, event: NeuroEvent) -> bool: ...


class NeuroBusDLQIntegration:
    """
    NeuroBus 与死信队列的集成

    自动将处理失败的事件转入 DLQ
    """

    def __init__(self, dlq: DeadLetterQueue | None = None):
        self._dlq = dlq or DeadLetterQueue()
        self._max_retries = 3

    @property
    def dlq(self) -> DeadLetterQueue:
        return self._dlq

    def handle_failure(
        self, event: NeuroEvent, error: Exception, retry_count: int, handler_name: str | None = None
    ) -> str:
        """
        处理失败，决定进入死信队列

        Returns:
            死信条目 ID
        """
        if retry_count >= self._max_retries:
            reason = DeadLetterReason.RETRY_EXHAUSTED
        elif isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            reason = DeadLetterReason.TIMEOUT
        elif isinstance(error, ValueError):
            reason = DeadLetterReason.INVALID_PAYLOAD
        else:
            reason = DeadLetterReason.UNRECOVERABLE
        import traceback

        error_stack = traceback.format_exc()
        return self._dlq.enqueue(
            event=event,
            reason=reason,
            error_message=str(error),
            retry_count=retry_count,
            handler_name=handler_name,
            error_stack=error_stack,
        )

    def setup_replay_to_bus(self, bus: EventPublisher) -> None:
        """设置重播到 NeuroBus"""

        def replay_callback(event: NeuroEvent) -> None:
            bus.publish(event)

        self._dlq.on_replay(replay_callback)


_dlq_instance: DeadLetterQueue | None = None


def get_dead_letter_queue(storage_path: str | None = None) -> DeadLetterQueue:
    """
    获取全局死信队列实例

    Args:
        storage_path: 可选 SQLITE 持久化路径；仅在首次创建实例时生效。
            若实例已存在则忽略该参数（保持向后兼容）。

    Returns:
        全局 DeadLetterQueue 实例
    """
    global _dlq_instance
    if _dlq_instance is None:
        _dlq_instance = DeadLetterQueue(storage_path=storage_path)
    return _dlq_instance


def enqueue_dead_letter(
    event: NeuroEvent, reason: str, error_message: str, retry_count: int = 0
) -> str:
    """快捷函数：将事件加入死信队列"""
    dlq = get_dead_letter_queue()
    reason_enum = DeadLetterReason.UNRECOVERABLE
    try:
        reason_enum = DeadLetterReason(reason)
    except ValueError:
        pass
    return dlq.enqueue(
        event=event, reason=reason_enum, error_message=error_message, retry_count=retry_count
    )


def get_dlq_stats() -> dict[str, Any]:
    """获取死信队列统计"""
    return get_dead_letter_queue().get_stats()
