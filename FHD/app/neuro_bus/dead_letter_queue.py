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


class DeadLetterQueue:
    """
    死信队列实现

    Level 4 可靠性机制:
    - 存储失败事件
    - 支持重播
    - 提供监控和告警
    """

    def __init__(
        self,
        max_size: int = 10000,
        retention_hours: int = 168,
        storage_path: str | None = None,
        alert_suppress_window: float = 300.0,
        alert_threshold: int = 1,
    ):
        """
        Args:
            max_size: 最大条目数
            retention_hours: 保留时间（小时，默认 7 天）
            storage_path: SQLITE 持久化路径；None 表示纯内存模式（默认）
            alert_suppress_window: 告警抑制窗口（秒，默认 5 分钟）
            alert_threshold: 触发告警的最小同类事件数（默认 1）
        """
        self._entries: dict[str, DeadLetterEntry] = {}
        self._max_size = max_size
        self._retention_seconds = retention_hours * 3600
        self._alert_callbacks: list[Callable[[DeadLetterEntry], None]] = []
        self._replay_callbacks: list[Callable[[NeuroEvent], None]] = []
        self._stats = {
            "total_entries": 0,
            "replayed": 0,
            "expired": 0,
            "manually_resolved": 0,
        }

        # SQLITE 持久化初始化
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._storage_path = storage_path
        if storage_path is not None:
            self._init_sqlite(storage_path)

        # 重播去重器（共享 lock 与 conn）
        self._deduplicator = ReplayDeduplicator(conn=self._conn, lock=self._lock)
        # 告警抑制器
        self._alert_suppressor = AlertSuppressor(
            suppress_window=alert_suppress_window,
            threshold=alert_threshold,
        )
        # 重播暂停标志
        self._replay_paused = False

        logger.info(
            "[DeadLetterQueue] 初始化完成 (max_size=%s, retention=%sh, storage=%s, "
            "alert_window=%ss, alert_threshold=%s)",
            max_size,
            retention_hours,
            storage_path or "memory",
            alert_suppress_window,
            alert_threshold,
        )

    def _init_sqlite(self, storage_path: str) -> None:
        """初始化 SQLITE 持久化存储"""
        # 确保目录存在
        path = Path(storage_path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            storage_path,
            check_same_thread=False,
            isolation_level=None,  # 自动提交模式
        )
        # 启用按列名访问（_row_to_entry 依赖 row["col"] 语法）
        self._conn.row_factory = sqlite3.Row
        # 性能与持久性平衡：WAL 提升并发读，FULL 同步保证崩溃安全
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS neuro_dead_letters (
                entry_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL,
                reason TEXT NOT NULL,
                error_message TEXT NOT NULL,
                error_stack TEXT,
                retry_count INTEGER DEFAULT 0,
                first_failure_time TEXT NOT NULL,
                last_failure_time TEXT NOT NULL,
                handler_name TEXT,
                metadata TEXT,
                is_resolved INTEGER DEFAULT 0
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_reason ON neuro_dead_letters(reason)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_event_type ON neuro_dead_letters(event_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_first_failure ON neuro_dead_letters(first_failure_time)"
        )
        logger.info("[DeadLetterQueue] SQLITE 持久化已启用: %s", storage_path)

    def _row_to_entry(self, row: sqlite3.Row) -> DeadLetterEntry:
        """将 SQLITE 行转换为 DeadLetterEntry"""
        try:
            event_data = json.loads(row["event_data"])
            event = NeuroEvent.from_dict(event_data, preserve_queue_identity=True)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error("[DeadLetterQueue] 反序列化事件失败 entry_id=%s: %s", row["entry_id"], e)
            event = NeuroEvent(event_type="__corrupt__", payload={})

        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except json.JSONDecodeError:
            metadata = {}

        return DeadLetterEntry(
            entry_id=row["entry_id"],
            original_event=event,
            reason=DeadLetterReason(row["reason"]),
            error_message=row["error_message"],
            error_stack=row["error_stack"],
            retry_count=row["retry_count"],
            first_failure_time=datetime.fromisoformat(row["first_failure_time"]),
            last_failure_time=datetime.fromisoformat(row["last_failure_time"]),
            handler_name=row["handler_name"],
            metadata=metadata,
        )

    # ========== 核心操作 ==========

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
        entry_id = f"dlq-{uuid4().hex[:12]}"
        now = datetime.now()

        # 死信 envelope 增强：保留原始事件上下文，用于重播时恢复
        metadata = {
            "enqueue_time": now.isoformat(),
            "original_event_id": event.metadata.event_id,
            "original_timestamp": event.metadata.timestamp,
            "original_domain": event.metadata.domain,
        }

        entry = DeadLetterEntry(
            entry_id=entry_id,
            original_event=event,
            reason=reason,
            error_message=error_message,
            error_stack=error_stack,
            retry_count=retry_count,
            first_failure_time=now,
            last_failure_time=now,
            handler_name=handler_name,
            metadata=metadata,
        )

        if self._conn is not None:
            self._enqueue_sqlite(entry)
        else:
            # 容量检查
            if len(self._entries) >= self._max_size:
                self._evict_oldest()
            self._entries[entry_id] = entry

        self._stats["total_entries"] += 1

        logger.error(
            "[DeadLetterQueue] 事件进入死信队列: %s (reason=%s, entry_id=%s, retries=%s)",
            event.event_type,
            reason.value,
            entry_id,
            retry_count,
        )

        # 触发告警
        self._trigger_alert(entry)

        return entry_id

    def _enqueue_sqlite(self, entry: DeadLetterEntry) -> None:
        """SQLITE 模式入队"""
        assert self._conn is not None  # 仅在持久化模式下调用
        with self._lock:
            # 容量检查
            cur = self._conn.execute("SELECT COUNT(*) FROM neuro_dead_letters")
            count = cur.fetchone()[0]
            if count >= self._max_size:
                self._evict_oldest()

            self._conn.execute(
                """
                INSERT INTO neuro_dead_letters
                (entry_id, event_type, event_data, reason, error_message, error_stack,
                 retry_count, first_failure_time, last_failure_time, handler_name,
                 metadata, is_resolved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    entry.entry_id,
                    entry.original_event.event_type,
                    entry.original_event.to_json(),
                    entry.reason.value,
                    entry.error_message,
                    entry.error_stack,
                    entry.retry_count,
                    entry.first_failure_time.isoformat(),
                    entry.last_failure_time.isoformat(),
                    entry.handler_name,
                    json.dumps(entry.metadata, ensure_ascii=False),
                ),
            )

    def dequeue(self, entry_id: str) -> DeadLetterEntry | None:
        """取出条目（不移除）"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM neuro_dead_letters WHERE entry_id = ?",
                    (entry_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_entry(row)
        return self._entries.get(entry_id)

    def remove(self, entry_id: str) -> bool:
        """移除条目"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM neuro_dead_letters WHERE entry_id = ?",
                    (entry_id,),
                )
                return cur.rowcount > 0
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    def replay(self, entry_id: str) -> tuple[bool, str]:
        """
        重播死信事件

        重播前检查指纹是否已重播，已重播的跳过。

        Returns:
            (是否重播, 跳过原因) - 跳过原因为空字符串表示成功重播；
            找不到条目返回 (False, "entry_not_found")；
            已重播过返回 (False, "already_replayed")
        """
        entry = self.dequeue(entry_id)
        if not entry:
            logger.warning("[DeadLetterQueue] 重播失败：找不到条目 %s", entry_id)
            return False, "entry_not_found"

        # 重播去重检查
        if self._deduplicator.is_replayed(entry_id, entry.retry_count):
            logger.info(
                "[DeadLetterQueue] 跳过重播（已重播过）: %s (retry_count=%s)",
                entry_id,
                entry.retry_count,
            )
            return False, "already_replayed"

        logger.info(
            "[DeadLetterQueue] 重播事件: %s (entry_id=%s)",
            entry.original_event.event_type,
            entry_id,
        )

        # 触发重播回调
        for callback in self._replay_callbacks:
            try:
                callback(entry.original_event)
            except RECOVERABLE_ERRORS as e:
                logger.error("[DeadLetterQueue] 重播回调失败: %s", e)

        # 标记为已重播（记录指纹）
        self._deduplicator.mark_replayed(entry_id, entry.retry_count)

        # 更新统计
        self._stats["replayed"] += 1

        # 可选：重播后从队列移除
        # self.remove(entry_id)

        return True, ""

    def _get_replay_candidates(
        self,
        event_type: str | None = None,
        max_age_seconds: float | None = None,
    ) -> list[str]:
        """获取待重播的条目 ID 列表（按筛选条件）"""
        to_replay: list[str] = []

        if self._conn is not None:
            with self._lock:
                if event_type is not None and max_age_seconds is not None:
                    cur = self._conn.execute(
                        """
                        SELECT entry_id, first_failure_time FROM neuro_dead_letters
                        WHERE event_type = ?
                        """,
                        (event_type,),
                    )
                    for row in cur.fetchall():
                        entry = self._row_to_entry(row)
                        if entry.age_seconds <= max_age_seconds:
                            to_replay.append(row["entry_id"])
                elif event_type is not None:
                    cur = self._conn.execute(
                        "SELECT entry_id FROM neuro_dead_letters WHERE event_type = ?",
                        (event_type,),
                    )
                    to_replay = [row["entry_id"] for row in cur.fetchall()]
                elif max_age_seconds is not None:
                    cur = self._conn.execute(
                        "SELECT entry_id, first_failure_time FROM neuro_dead_letters"
                    )
                    for row in cur.fetchall():
                        entry = self._row_to_entry(row)
                        if entry.age_seconds <= max_age_seconds:
                            to_replay.append(row["entry_id"])
                else:
                    cur = self._conn.execute("SELECT entry_id FROM neuro_dead_letters")
                    to_replay = [row["entry_id"] for row in cur.fetchall()]
        else:
            for entry_id, entry in self._entries.items():
                # 筛选条件
                if event_type and entry.original_event.event_type != event_type:
                    continue
                if max_age_seconds and entry.age_seconds > max_age_seconds:
                    continue

                to_replay.append(entry_id)

        return to_replay

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
        to_replay = self._get_replay_candidates(event_type, max_age_seconds)

        count = 0
        total = len(to_replay)
        # 每批之间的 sleep 秒数：batch_size / qps
        batch_sleep = batch_size / rate_limit_qps if rate_limit_qps > 0 else 0.0

        for i, entry_id in enumerate(to_replay):
            # 检查 pause 标志
            if self._is_replay_paused():
                logger.info("[DeadLetterQueue] 重播已暂停，停止于 %s/%s", i, total)
                break

            replayed, _ = self.replay(entry_id)
            if replayed:
                count += 1

            # 批次间 sleep（每 batch_size 条后）
            if (i + 1) % batch_size == 0 and (i + 1) < total:
                if batch_sleep > 0:
                    time.sleep(batch_sleep)

        logger.info("[DeadLetterQueue] 批量重播完成: %s/%s 个事件", count, total)
        return count

    # ========== 重播控制 ==========

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
        to_replay = self._get_replay_candidates(event_type, max_age_seconds)
        total = len(to_replay)
        replayed = 0
        batch_sleep = batch_size / rate_limit_qps if rate_limit_qps > 0 else 0.0

        for i, entry_id in enumerate(to_replay):
            # 检查 pause 标志
            if self._is_replay_paused():
                logger.info("[DeadLetterQueue] 重播已暂停，停止于 %s/%s", i, total)
                return

            success, _ = self.replay(entry_id)
            if success:
                replayed += 1

            yield replayed, total, entry_id

            # 批次间 sleep
            if (i + 1) % batch_size == 0 and (i + 1) < total:
                if batch_sleep > 0:
                    time.sleep(batch_sleep)

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
        if stages is None:
            stages = [0.01, 0.1, 0.5, 1.0]

        to_replay = self._get_replay_candidates(event_type, None)
        total = len(to_replay)

        report: dict[str, Any] = {
            "total": total,
            "stages_executed": [],
            "replayed": 0,
            "paused": False,
            "pause_reason": None,
        }

        if total == 0:
            return report

        replayed = 0
        for stage_idx, fraction in enumerate(stages):
            # 检查 pause 标志
            if self._is_replay_paused():
                report["paused"] = True
                report["pause_reason"] = "manual_pause"
                break

            # 计算本阶段目标位置
            target_count = int(total * fraction)
            batch = to_replay[replayed:target_count]

            # 记录本阶段开始前的死信总数
            stage_dlq_before = self._stats["total_entries"]

            for entry_id in batch:
                if self._is_replay_paused():
                    report["paused"] = True
                    report["pause_reason"] = "manual_pause"
                    break
                success, _ = self.replay(entry_id)
                if success:
                    replayed += 1

            # 本阶段新增死信数
            stage_dlq_after = self._stats["total_entries"]
            new_dlq_count = stage_dlq_after - stage_dlq_before

            report["stages_executed"].append(
                {
                    "stage": stage_idx,
                    "fraction": fraction,
                    "target": len(batch),
                    "replayed": replayed,
                    "new_dlq": new_dlq_count,
                }
            )

            # 检查新增死信阈值
            if new_dlq_count >= error_threshold:
                report["paused"] = True
                report["pause_reason"] = (
                    f"error_threshold_exceeded: {new_dlq_count} >= {error_threshold}"
                )
                self.pause_replay()
                break

            # 阶段间 sleep（最后一个阶段不需要）
            if stage_idx < len(stages) - 1:
                time.sleep(stage_interval)

        report["replayed"] = replayed
        return report

    # ========== 管理操作 ==========

    def resolve_manually(self, entry_id: str, resolution: str, resolved_by: str) -> bool:
        """
        手动解决死信

        用于人工干预后标记为已处理
        """
        entry = self.dequeue(entry_id)
        if not entry:
            return False

        logger.info(
            "[DeadLetterQueue] 手动解决: %s (resolution=%s, by=%s)",
            entry_id,
            resolution,
            resolved_by,
        )

        entry.metadata["resolved"] = True
        entry.metadata["resolution"] = resolution
        entry.metadata["resolved_by"] = resolved_by
        entry.metadata["resolved_at"] = datetime.now().isoformat()

        self._stats["manually_resolved"] += 1

        if self._conn is not None:
            # 标记为已解决并保留记录（is_resolved=1），同时更新 metadata
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE neuro_dead_letters
                    SET is_resolved = 1, metadata = ?
                    WHERE entry_id = ?
                    """,
                    (json.dumps(entry.metadata, ensure_ascii=False), entry_id),
                )
                # 解决后从活动队列移除（与内存模式行为一致）
                self._conn.execute(
                    "DELETE FROM neuro_dead_letters WHERE entry_id = ?",
                    (entry_id,),
                )
        else:
            # 解决后从队列移除
            self.remove(entry_id)

        return True

    def cleanup_expired(self) -> int:
        """清理过期条目"""
        if self._conn is not None:
            with self._lock:
                # 计算截止时间：当前时间减去保留期
                cutoff_dt = datetime.fromtimestamp(
                    datetime.now().timestamp() - self._retention_seconds
                )
                cur = self._conn.execute(
                    """
                    DELETE FROM neuro_dead_letters
                    WHERE first_failure_time < ?
                    """,
                    (cutoff_dt.isoformat(),),
                )
                expired_count = cur.rowcount
            self._stats["expired"] += expired_count
            if expired_count:
                logger.info("[DeadLetterQueue] 清理过期条目: %s 个", expired_count)
            return expired_count

        time.time()
        expired = [
            entry_id
            for entry_id, entry in self._entries.items()
            if entry.age_seconds > self._retention_seconds
        ]

        for entry_id in expired:
            del self._entries[entry_id]

        self._stats["expired"] += len(expired)

        if expired:
            logger.info("[DeadLetterQueue] 清理过期条目: %s 个", len(expired))

        return len(expired)

    # ========== 查询 ==========

    def get_all_entries(self) -> list[DeadLetterEntry]:
        """获取所有条目"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute("SELECT * FROM neuro_dead_letters")
                return [self._row_to_entry(row) for row in cur.fetchall()]
        return list(self._entries.values())

    def get_entries_by_reason(self, reason: DeadLetterReason) -> list[DeadLetterEntry]:
        """按原因筛选"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM neuro_dead_letters WHERE reason = ?",
                    (reason.value,),
                )
                return [self._row_to_entry(row) for row in cur.fetchall()]
        return [e for e in self._entries.values() if e.reason == reason]

    def get_entries_by_event_type(self, event_type: str) -> list[DeadLetterEntry]:
        """按事件类型筛选"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM neuro_dead_letters WHERE event_type = ?",
                    (event_type,),
                )
                return [self._row_to_entry(row) for row in cur.fetchall()]
        return [e for e in self._entries.values() if e.original_event.event_type == event_type]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute("SELECT COUNT(*) FROM neuro_dead_letters")
                current_size = cur.fetchone()[0]

                # 按 reason 分组统计
                cur = self._conn.execute(
                    """
                    SELECT reason, COUNT(*) as cnt
                    FROM neuro_dead_letters
                    GROUP BY reason
                    """
                )
                by_reason = {row["reason"]: row["cnt"] for row in cur.fetchall()}

                # 最老条目年龄
                cur = self._conn.execute("SELECT MIN(first_failure_time) FROM neuro_dead_letters")
                oldest_iso = cur.fetchone()[0]
                if oldest_iso:
                    oldest_age_hours = (
                        datetime.now() - datetime.fromisoformat(oldest_iso)
                    ).total_seconds() / 3600
                else:
                    oldest_age_hours = 0

            return {
                "current_size": current_size,
                "max_size": self._max_size,
                **self._stats,
                "by_reason": by_reason,
                "oldest_entry_age_hours": oldest_age_hours,
            }

        by_reason = {}
        for entry in self._entries.values():
            reason = entry.reason.value
            by_reason[reason] = by_reason.get(reason, 0) + 1

        return {
            "current_size": len(self._entries),
            "max_size": self._max_size,
            **self._stats,
            "by_reason": by_reason,
            "oldest_entry_age_hours": (
                min(e.age_seconds for e in self._entries.values()) / 3600 if self._entries else 0
            ),
        }

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
        retriable_reasons = {
            DeadLetterReason.RETRY_EXHAUSTED,
            DeadLetterReason.TIMEOUT,
        }
        fixable_reasons = {
            DeadLetterReason.INVALID_PAYLOAD,
            DeadLetterReason.HANDLER_NOT_FOUND,
        }
        poison_reasons = {
            DeadLetterReason.UNRECOVERABLE,
            DeadLetterReason.CIRCUIT_BREAKER,
        }

        result: dict[str, list[str]] = {
            "retriable": [],
            "fixable": [],
            "poison": [],
        }

        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute("SELECT entry_id, reason FROM neuro_dead_letters")
                for row in cur.fetchall():
                    reason = DeadLetterReason(row["reason"])
                    if reason in retriable_reasons:
                        result["retriable"].append(row["entry_id"])
                    elif reason in fixable_reasons:
                        result["fixable"].append(row["entry_id"])
                    elif reason in poison_reasons:
                        result["poison"].append(row["entry_id"])
        else:
            with self._lock:
                for entry_id, entry in self._entries.items():
                    if entry.reason in retriable_reasons:
                        result["retriable"].append(entry_id)
                    elif entry.reason in fixable_reasons:
                        result["fixable"].append(entry_id)
                    elif entry.reason in poison_reasons:
                        result["poison"].append(entry_id)

        return result

    # ========== 回调注册 ==========

    def on_alert(self, callback: Callable[[DeadLetterEntry], None]):
        """注册告警回调"""
        self._alert_callbacks.append(callback)

    def on_replay(self, callback: Callable[[NeuroEvent], None]):
        """注册重播回调"""
        self._replay_callbacks.append(callback)

    def _trigger_alert(self, entry: DeadLetterEntry):
        """
        触发告警（含抑制逻辑）

        按 (reason, event_type) 分组，同组 suppress_window 内只告警一次。
        告警内容含"X 条同类失败"。
        """
        should_alert, count = self._alert_suppressor.record_and_check(
            entry.reason, entry.original_event.event_type
        )

        if not should_alert:
            return

        # 在 metadata 中附加同类失败计数（供回调使用）
        entry.metadata["alert_count_in_window"] = count

        for callback in self._alert_callbacks:
            try:
                callback(entry)
            except RECOVERABLE_ERRORS as e:
                logger.error("[DeadLetterQueue] 告警回调失败: %s", e)

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

    # ========== 重试调度 ==========

    def schedule_retry(
        self,
        entry_id: str,
        base: float = RETRY_BASE_DELAY,
        cap: float = RETRY_MAX_DELAY,
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
        entry = self.dequeue(entry_id)
        if entry is None:
            logger.warning("[DeadLetterQueue] schedule_retry 失败：找不到条目 %s", entry_id)
            return None

        # 计算指数退避 + jitter
        exponential = min(base * (2**entry.retry_count), cap)
        jitter_multiplier = 0.5 + random.random() * 0.5  # 0.5 ~ 1.0
        delay = exponential * jitter_multiplier

        new_retry_count = entry.retry_count + 1
        now = datetime.now()

        if self._conn is not None:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE neuro_dead_letters
                    SET retry_count = ?, last_failure_time = ?
                    WHERE entry_id = ?
                    """,
                    (new_retry_count, now.isoformat(), entry_id),
                )
        else:
            entry.retry_count = new_retry_count
            entry.last_failure_time = now

        logger.info(
            "[DeadLetterQueue] 安排重试: entry_id=%s, retry=%s, delay=%.3fs",
            entry_id,
            new_retry_count,
            delay,
        )
        return float(delay)

    # ========== 内部方法 ==========

    def _evict_oldest(self):
        """驱逐最老的条目"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    """
                    SELECT entry_id FROM neuro_dead_letters
                    ORDER BY first_failure_time ASC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row is None:
                    return
                oldest_id = row["entry_id"]
                self._conn.execute(
                    "DELETE FROM neuro_dead_letters WHERE entry_id = ?",
                    (oldest_id,),
                )
                logger.warning("[DeadLetterQueue] 驱逐最老条目: %s", oldest_id)
            return

        if not self._entries:
            return

        oldest = min(self._entries.values(), key=lambda e: e.first_failure_time)
        del self._entries[oldest.entry_id]
        logger.warning("[DeadLetterQueue] 驱逐最老条目: %s", oldest.entry_id)


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
