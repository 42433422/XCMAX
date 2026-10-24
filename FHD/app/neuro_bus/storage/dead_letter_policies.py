"""Replay fingerprint retention and grouped alert policy, with explicit clocks."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from typing import TYPE_CHECKING, Any, TypedDict

from .sqlite import StorageRuntime

if TYPE_CHECKING:
    from app.neuro_bus.dead_letter_queue import DeadLetterEntry, DeadLetterReason


class AlertWindow(TypedDict):
    last_alert_ts: float
    event_count: int
    first_event_ts: float


class ReplayLedger:
    """
    重播去重器 - 对标 Kafka DLT 幂等键 + 指纹

    用指纹去重：sha256(entry_id + str(replay_count))
    - 内存模式：dict 存已重播指纹（TTL 24h）
    - SQLITE 模式：neuro_dlq_replay_log 表
    """

    DEFAULT_TTL_SECONDS = 86400.0

    def __init__(
        self,
        runtime: StorageRuntime,
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
        self._runtime = runtime
        self._conn = conn
        self._lock = lock or threading.RLock()
        self._ttl_seconds = ttl_seconds
        self._memory_log: dict[str, tuple[str, float]] = {}
        if conn is not None:
            self._init_sqlite_table(conn)

    def _init_sqlite_table(self, conn: sqlite3.Connection) -> None:
        """初始化 SQLITE 重播日志表"""
        conn.execute(
            """CREATE TABLE IF NOT EXISTS neuro_dlq_replay_log (
                   fingerprint TEXT PRIMARY KEY, entry_id TEXT NOT NULL,
                   replayed_at TEXT NOT NULL, expires_at TEXT NOT NULL)"""
        ).close()
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_replay_expires ON neuro_dlq_replay_log(expires_at)"
        ).close()

    @staticmethod
    def fingerprint(entry_id: str, replay_count: int) -> str:
        """生成指纹: sha256(entry_id + str(replay_count))"""
        raw = f"{entry_id}:{replay_count}".encode()
        return hashlib.sha256(raw).hexdigest()

    def is_replayed(self, entry_id: str, replay_count: int) -> bool:
        """检查是否已重播过（指纹命中且未过期）"""
        fp = self.fingerprint(entry_id, replay_count)
        now_ts = self._runtime.now_seconds()
        if self._conn is not None:
            with self._lock:
                now_iso = self._runtime.clock().fromtimestamp(now_ts).isoformat()
                with closing(
                    self._conn.execute(
                        "SELECT 1 FROM neuro_dlq_replay_log WHERE fingerprint = ? AND expires_at > ?",
                        (fp, now_iso),
                    )
                ) as cursor:
                    return cursor.fetchone() is not None
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
        now_ts = self._runtime.now_seconds()
        expires_at_ts = now_ts + self._ttl_seconds
        if self._conn is not None:
            with self._lock:
                now_iso = self._runtime.clock().fromtimestamp(now_ts).isoformat()
                expires_iso = self._runtime.clock().fromtimestamp(expires_at_ts).isoformat()
                self._conn.execute(
                    """INSERT OR REPLACE INTO neuro_dlq_replay_log
                       (fingerprint, entry_id, replayed_at, expires_at) VALUES (?, ?, ?, ?)""",
                    (fp, entry_id, now_iso, expires_iso),
                ).close()
            return
        with self._lock:
            self._memory_log[fp] = (entry_id, expires_at_ts)

    def cleanup_expired(self) -> int:
        """清理过期记录，返回清理数量"""
        if self._conn is not None:
            with self._lock:
                now_iso = self._runtime.clock().now().isoformat()
                with closing(
                    self._conn.execute(
                        "DELETE FROM neuro_dlq_replay_log WHERE expires_at <= ?", (now_iso,)
                    )
                ) as cursor:
                    return cursor.rowcount
        now_ts = self._runtime.now_seconds()
        with self._lock:
            expired = [fp for fp, (_, exp) in self._memory_log.items() if now_ts >= exp]
            for fp in expired:
                del self._memory_log[fp]
            return len(expired)


class GroupedAlerts:
    """
    告警抑制器 - 对标 Kafka DLT 分层告警

    - 按 (reason, event_type) 分组
    - 同组 suppress_window 内只告警一次
    - 支持全局静默
    """

    def __init__(
        self, runtime: StorageRuntime, suppress_window: float = 300.0, threshold: int = 1
    ) -> None:
        """
        Args:
            suppress_window: 抑制窗口（秒，默认 5 分钟）
            threshold: 触发告警的最小事件数
        """
        self._runtime = runtime
        self._suppress_window = suppress_window
        self._threshold = threshold
        self._lock = threading.RLock()
        self._groups: dict[str, AlertWindow] = {}
        self._silenced_until: float = 0.0
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
        now = self._runtime.now_seconds()
        with self._lock:
            self._stats.setdefault(key, {"suppressed": 0, "fired": 0, "total": 0})
            self._stats[key]["total"] += 1
            group = self._groups.get(key)
            if group is None:
                group = {"last_alert_ts": 0.0, "event_count": 0, "first_event_ts": now}
                self._groups[key] = group
            if now - group["first_event_ts"] > self._suppress_window:
                group["event_count"] = 0
                group["first_event_ts"] = now
            group["event_count"] += 1
            count = group["event_count"]
            if now < self._silenced_until:
                self._stats[key]["suppressed"] += 1
                return (False, count)
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
            return (should_alert, count)

    def silence(self, duration_seconds: float) -> None:
        """全局静默指定时长"""
        with self._lock:
            self._silenced_until = self._runtime.now_seconds() + duration_seconds

    def get_stats(self) -> dict[str, Any]:
        """获取告警统计"""
        with self._lock:
            now = self._runtime.now_seconds()
            return {
                "groups": {k: dict(v) for k, v in self._stats.items()},
                "silenced": now < self._silenced_until,
                "silenced_remaining_seconds": max(0.0, self._silenced_until - now),
                "suppress_window": self._suppress_window,
                "threshold": self._threshold,
            }


class AlertDelivery:
    def __init__(
        self,
        suppressor: GroupedAlerts,
        callbacks: list[Callable[[DeadLetterEntry], None]],
        runtime: StorageRuntime,
    ):
        self.suppressor = suppressor
        self.callbacks = callbacks
        self.runtime = runtime

    def trigger(self, entry: DeadLetterEntry) -> None:
        should_alert, count = self.suppressor.record_and_check(
            entry.reason, entry.original_event.event_type
        )
        if not should_alert:
            return
        entry.metadata["alert_count_in_window"] = count
        for callback in self.callbacks:
            try:
                callback(entry)
            except self.runtime.errors() as error:
                self.runtime.log().error("[DeadLetterQueue] 告警回调失败: %s", error)
