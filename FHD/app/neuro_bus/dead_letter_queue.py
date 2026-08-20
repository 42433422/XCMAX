# ruff: noqa: E402, F401
"""
死信队列 (Dead Letter Queue) - Level 4 可靠性机制

处理无法成功处理的事件：
- 重试次数耗尽
- 不可恢复的异常
- 超时事件

提供：
- 死信存储
- 重播机制
- 告警通知
- 手动干预接口
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


# 指数退避重试默认参数
RETRY_BASE_DELAY = 0.5  # 基础退避秒数
RETRY_MAX_DELAY = 30.0  # 最大退避秒数（cap）


class DeadLetterReason(Enum):
    """进入死信队列的原因"""

    RETRY_EXHAUSTED = "retry_exhausted"  # 重试次数耗尽
    UNRECOVERABLE = "unrecoverable"  # 不可恢复异常
    TIMEOUT = "timeout"  # 处理超时
    INVALID_PAYLOAD = "invalid_payload"  # 无效载荷
    HANDLER_NOT_FOUND = "handler_not_found"  # 找不到处理器
    CIRCUIT_BREAKER = "circuit_breaker"  # 熔断器开启


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


class ReplayDeduplicator:
    """
    重播去重器 - 对标 Kafka DLT 幂等键 + 指纹

    用指纹去重：sha256(entry_id + str(replay_count))
    - 内存模式：dict 存已重播指纹（TTL 24h）
    - SQLITE 模式：neuro_dlq_replay_log 表
    """

    # 默认 TTL 24 小时
    DEFAULT_TTL_SECONDS = 86400.0

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        lock: threading.RLock | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ):
        """
        Args:
            conn: SQLITE 连接；None 表示内存模式
            lock: 外部 RLock（与 DeadLetterQueue 共享）
            ttl_seconds: 指纹保留时间（秒）
        """
        self._conn = conn
        self._lock = lock or threading.RLock()
        self._ttl_seconds = ttl_seconds
        # 内存模式: {fingerprint: (entry_id, expires_at_timestamp)}
        self._memory_log: dict[str, tuple[str, float]] = {}
        if conn is not None:
            self._init_sqlite_table(conn)

    def _init_sqlite_table(self, conn: sqlite3.Connection) -> None:
        """初始化 SQLITE 重播日志表"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS neuro_dlq_replay_log (
                fingerprint TEXT PRIMARY KEY,
                entry_id TEXT NOT NULL,
                replayed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_replay_expires ON neuro_dlq_replay_log(expires_at)"
        )

    @staticmethod
    def fingerprint(entry_id: str, replay_count: int) -> str:
        """生成指纹: sha256(entry_id + str(replay_count))"""
        raw = f"{entry_id}:{replay_count}".encode()
        return hashlib.sha256(raw).hexdigest()

    def is_replayed(self, entry_id: str, replay_count: int) -> bool:
        """检查是否已重播过（指纹命中且未过期）"""
        fp = self.fingerprint(entry_id, replay_count)
        now_ts = time.time()

        if self._conn is not None:
            with self._lock:
                now_iso = datetime.fromtimestamp(now_ts).isoformat()
                cur = self._conn.execute(
                    "SELECT 1 FROM neuro_dlq_replay_log WHERE fingerprint = ? AND expires_at > ?",
                    (fp, now_iso),
                )
                return cur.fetchone() is not None

        # 内存模式
        with self._lock:
            record = self._memory_log.get(fp)
            if record is None:
                return False
            _, expires_at = record
            if now_ts >= expires_at:
                del self._memory_log[fp]
                return False
            return True

    def mark_replayed(self, entry_id: str, replay_count: int) -> None:
        """标记为已重播"""
        fp = self.fingerprint(entry_id, replay_count)
        now_ts = time.time()
        expires_at_ts = now_ts + self._ttl_seconds

        if self._conn is not None:
            with self._lock:
                now_iso = datetime.fromtimestamp(now_ts).isoformat()
                expires_iso = datetime.fromtimestamp(expires_at_ts).isoformat()
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO neuro_dlq_replay_log
                    (fingerprint, entry_id, replayed_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (fp, entry_id, now_iso, expires_iso),
                )
            return

        with self._lock:
            self._memory_log[fp] = (entry_id, expires_at_ts)

    def cleanup_expired(self) -> int:
        """清理过期记录，返回清理数量"""
        if self._conn is not None:
            with self._lock:
                now_iso = datetime.now().isoformat()
                cur = self._conn.execute(
                    "DELETE FROM neuro_dlq_replay_log WHERE expires_at <= ?",
                    (now_iso,),
                )
                return cur.rowcount

        now_ts = time.time()
        with self._lock:
            expired = [fp for fp, (_, exp) in self._memory_log.items() if now_ts >= exp]
            for fp in expired:
                del self._memory_log[fp]
            return len(expired)


class AlertSuppressor:
    """
    告警抑制器 - 对标 Kafka DLT 分层告警

    - 按 (reason, event_type) 分组
    - 同组 suppress_window 内只告警一次
    - 支持全局静默
    """

    def __init__(
        self,
        suppress_window: float = 300.0,
        threshold: int = 1,
    ):
        """
        Args:
            suppress_window: 抑制窗口（秒，默认 5 分钟）
            threshold: 触发告警的最小事件数
        """
        self._suppress_window = suppress_window
        self._threshold = threshold
        self._lock = threading.RLock()
        # {group_key: {"last_alert_ts": float, "event_count": int, "first_event_ts": float}}
        self._groups: dict[str, dict[str, Any]] = {}
        # 全局静默截止时间戳
        self._silenced_until: float = 0.0
        # 统计: {group_key: {"suppressed": N, "fired": M, "total": K}}
        self._stats: dict[str, dict[str, int]] = {}

    @staticmethod
    def make_key(reason: DeadLetterReason, event_type: str) -> str:
        """生成分组键"""
        return f"{reason.value}:{event_type}"

    def record_and_check(self, reason: DeadLetterReason, event_type: str) -> tuple[bool, int]:
        """
        记录事件并判断是否应该告警

        Returns:
            (should_alert, count_in_window) - 是否告警, 窗口内同类事件数
        """
        key = self.make_key(reason, event_type)
        now = time.time()

        with self._lock:
            self._stats.setdefault(key, {"suppressed": 0, "fired": 0, "total": 0})
            self._stats[key]["total"] += 1

            group = self._groups.get(key)
            if group is None:
                group = {
                    "last_alert_ts": 0.0,
                    "event_count": 0,
                    "first_event_ts": now,
                }
                self._groups[key] = group

            # 窗口外重置计数
            if now - group["first_event_ts"] > self._suppress_window:
                group["event_count"] = 0
                group["first_event_ts"] = now

            group["event_count"] += 1
            count = group["event_count"]

            # 全局静默检查
            if now < self._silenced_until:
                self._stats[key]["suppressed"] += 1
                return False, count

            # 判断是否应该告警:
            # 1. 达到阈值
            # 2. 窗口内还没告警过 (last_alert_ts 在窗口外或为 0)
            should_alert = False
            if count >= self._threshold:
                if now - group["last_alert_ts"] >= self._suppress_window:
                    should_alert = True
                    group["last_alert_ts"] = now
                    self._stats[key]["fired"] += 1
                else:
                    self._stats[key]["suppressed"] += 1
            else:
                self._stats[key]["suppressed"] += 1

            return should_alert, count

    def silence(self, duration_seconds: float) -> None:
        """全局静默指定时长"""
        with self._lock:
            self._silenced_until = time.time() + duration_seconds

    def get_stats(self) -> dict[str, Any]:
        """获取告警统计"""
        with self._lock:
            now = time.time()
            return {
                "groups": {k: dict(v) for k, v in self._stats.items()},
                "silenced": now < self._silenced_until,
                "silenced_remaining_seconds": max(0.0, self._silenced_until - now),
                "suppress_window": self._suppress_window,
                "threshold": self._threshold,
            }


from app.neuro_bus.dead_letter_queue_deadletterqueue_mixin01 import _DeadLetterQueuePart01Mixin
from app.neuro_bus.dead_letter_queue_deadletterqueue_mixin02 import _DeadLetterQueuePart02Mixin


class DeadLetterQueue(_DeadLetterQueuePart01Mixin, _DeadLetterQueuePart02Mixin):
    """
    死信队列实现

    Level 4 可靠性机制:
    - 存储失败事件
    - 支持重播
    - 提供监控和告警
    """

    # ========== 核心操作 ==========

    # ========== 重播控制 ==========

    # ========== 管理操作 ==========

    # ========== 查询 ==========

    # ========== 回调注册 ==========

    # ========== 重试调度 ==========

    # ========== 内部方法 ==========


# ========== 与 NeuroBus 集成 ==========


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
        self,
        event: NeuroEvent,
        error: Exception,
        retry_count: int,
        handler_name: str | None = None,
    ) -> str:
        """
        处理失败，决定进入死信队列

        Returns:
            死信条目 ID
        """
        # 判断原因
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

    def setup_replay_to_bus(self, bus):
        """设置重播到 NeuroBus"""

        def replay_callback(event: NeuroEvent):
            bus.publish(event)

        self._dlq.on_replay(replay_callback)


# 全局 DLQ 实例
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


# 快捷函数


def enqueue_dead_letter(
    event: NeuroEvent,
    reason: str,
    error_message: str,
    retry_count: int = 0,
) -> str:
    """快捷函数：将事件加入死信队列"""
    dlq = get_dead_letter_queue()

    reason_enum = DeadLetterReason.UNRECOVERABLE
    try:
        reason_enum = DeadLetterReason(reason)
    except ValueError:
        pass

    return dlq.enqueue(
        event=event,
        reason=reason_enum,
        error_message=error_message,
        retry_count=retry_count,
    )


def get_dlq_stats() -> dict[str, Any]:
    """获取死信队列统计"""
    return get_dead_letter_queue().get_stats()
