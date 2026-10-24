"""Public event-store API composed from journal, snapshots and replay components."""

from __future__ import annotations

import hashlib as hashlib
import json as json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .storage.event_codec import EventCodec
from .storage.event_journal import EventJournal, EventState, initialize_event_store
from .storage.event_queries import EventQueries
from .storage.event_records import (
    EventStoreMode as EventStoreMode,
)
from .storage.event_records import (
    EventUpcaster as EventUpcaster,
)
from .storage.event_records import (
    InvalidEventError as InvalidEventError,
)
from .storage.event_records import (
    Snapshot as Snapshot,
)
from .storage.event_records import (
    StoredEvent as StoredEvent,
)
from .storage.event_records import (
    UpcasterRegistry as UpcasterRegistry,
)
from .storage.event_records import (
    WrongExpectedVersionError as WrongExpectedVersionError,
)
from .storage.event_records import (
    validate_event_schema as validate_event_schema,
)
from .storage.event_recovery import EventRecovery
from .storage.event_snapshots import EventSnapshots, state_hash
from .storage.sqlite import SQLiteOwner, StorageRuntime

logger = logging.getLogger(__name__)


class EventStore:
    """Persistent event streams with optimistic concurrency, snapshots and replay."""

    def __init__(
        self,
        mode: EventStoreMode = EventStoreMode.MEMORY,
        storage_path: str | None = None,
        max_events: int = 100000,
        max_snapshots_per_stream: int = 3,
        upcaster_registry: UpcasterRegistry | None = None,
    ) -> None:
        self._mode = mode
        self._storage_path = storage_path
        self._max_events = max_events
        self._max_snapshots_per_stream = max_snapshots_per_stream
        self._upcaster_registry = upcaster_registry
        self._state = EventState()
        self._events = self._state.events
        self._stream_events = self._state.streams
        self._snapshots = self._state.snapshots
        self._append_callbacks: list[Callable[[StoredEvent], None]] = []
        self._lock = threading.RLock()
        self._storage = SQLiteOwner(self._lock)
        self._runtime = StorageRuntime(
            lambda: datetime,
            lambda: uuid4().hex[:12],
            lambda: logger,
            lambda: RECOVERABLE_ERRORS,
            lambda seconds: time.sleep(seconds),
            lambda: time.time(),
        )
        if upcaster_registry is not None:
            upcaster_registry.validate_chains()
        if mode == EventStoreMode.SQLITE:
            self._init_sqlite()
        elif mode == EventStoreMode.JSON_FILE:
            logger.warning("[EventStore] JSON_FILE 模式尚未实现，将退化为内存存储")
        self._codec = EventCodec(upcaster_registry, self._runtime)
        self._journal = EventJournal(
            self._storage, self._state, self._codec, self._runtime, max_events
        )
        self._queries = EventQueries(self._storage, self._state, self._codec, max_events)
        self._snapshot_store = EventSnapshots(
            self._storage,
            self._snapshots,
            self._runtime,
            max_snapshots_per_stream,
            lambda state: self._compute_state_hash(state),
        )
        self._recovery = EventRecovery(
            lambda stream_id, from_sequence=0: self.get_stream_events(stream_id, from_sequence),
            lambda start_time=None, end_time=None, event_type=None: self.get_all(
                start_time, end_time, event_type
            ),
            lambda stream_id: self.get_snapshot(stream_id),
            lambda events, stream_id=None, expected_version=None: self.append_many(
                events, stream_id, expected_version
            ),
            lambda state: self._compute_state_hash(state),
            self._runtime,
        )
        logger.info(
            "[EventStore] 初始化完成 (mode=%s, max_events=%s, max_snapshots=%s)",
            mode.value,
            max_events,
            max_snapshots_per_stream,
        )

    def _init_sqlite(self) -> None:
        """初始化 SQLITE 持久化存储"""
        if not self._storage_path:
            raise ValueError("[EventStore] SQLITE 模式必须提供 storage_path")
        initialized = False
        try:
            self._storage.open(self._storage_path, initialize_event_store)
            self._sequence_counter = int(
                self._storage.rows("SELECT COALESCE(MAX(sequence_number), 0) FROM neuro_events")[0][
                    0
                ]
            )
            initialized = True
        finally:
            if not initialized:
                self._storage.close()
        logger.info(
            "[EventStore] SQLITE 模式初始化完成 (path=%s, seq_start=%s)",
            self._storage_path,
            self._sequence_counter,
        )

    def _row_to_stored_event(self, row: sqlite3.Row) -> StoredEvent:
        """将数据库行转换为 StoredEvent（自动应用 upcaster 链）"""
        return self._codec.from_row(row)

    def _apply_upcasters_to_stored(self, stored: StoredEvent) -> StoredEvent:
        """对 MEMORY 模式读取的 StoredEvent 应用 upcaster（返回新对象）"""
        return self._codec.upcast(stored)

    def _get_stream_version(self, stream_id: str) -> int:
        """获取 stream 当前版本（事件数，0 表示空流）"""
        return self._journal.stream_version(stream_id)

    def _check_expected_version(self, stream_id: str | None, expected_version: int | None) -> None:
        """乐观并发检查"""
        self._journal.check_version(stream_id, expected_version)

    def append(
        self, event: NeuroEvent, stream_id: str | None = None, expected_version: int | None = None
    ) -> str:
        """
        存储事件

        Args:
            event: 事件
            stream_id: 事件流 ID
            expected_version: 乐观并发控制
                - None：无检查（向后兼容）
                - -1：stream 必须不存在（创建）
                - -2：stream 存在与否皆可
                - N(>=0)：stream 当前 version 必须为 N

        Returns:
            存储 ID
        """
        validate_event_schema(event)
        stored = self._journal.append([event], stream_id, expected_version, check_capacity=True)[0]
        self._notify_appends([stored])
        return stored.store_id

    def _append_sqlite(self, stored: StoredEvent) -> None:
        """SQLITE 模式下插入单条事件（含容量检查）"""
        self._journal.insert_stored(stored)

    def append_many(
        self,
        events: list[NeuroEvent],
        stream_id: str | None = None,
        expected_version: int | None = None,
    ) -> list[str]:
        """
        批量存储事件

        Args:
            events: 事件列表
            stream_id: 事件流 ID
            expected_version: 乐观并发控制（语义同 append）
        """
        if not events:
            return []
        for event in events:
            validate_event_schema(event)
        if self._conn is None:
            return [
                self.append(
                    event, stream_id, expected_version=expected_version if index == 0 else None
                )
                for index, event in enumerate(events)
            ]
        records = self._journal.append(events, stream_id, expected_version, check_capacity=False)
        self._notify_appends(records)
        return [record.store_id for record in records]

    def append_with_retry(
        self,
        stream_id: str,
        build_events: Callable[[list[StoredEvent]], list[NeuroEvent]],
        max_retries: int = 3,
        base_delay: float = 0.01,
    ) -> list[str]:
        """
        乐观并发重试追加

        冲突时重新 load → reapply → 再 append，指数退避。

        Args:
            stream_id: 事件流 ID
            build_events: 回调函数，接收当前流事件列表，返回新事件列表
            max_retries: 最大重试次数
            base_delay: 基础退避延迟（秒），实际延迟 = base_delay * 2^attempt

        Returns:
            存储 ID 列表

        Raises:
            WrongExpectedVersionError: 重试耗尽仍冲突
        """
        return self._recovery.append_with_retry(stream_id, build_events, max_retries, base_delay)

    def get(self, store_id: str) -> StoredEvent | None:
        """获取单个事件"""
        return self._queries.get(store_id)

    def get_all(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        event_type: str | None = None,
    ) -> Iterator[StoredEvent]:
        """
        获取事件流

        支持时间范围和事件类型筛选
        """
        yield from self._queries.all(start_time, end_time, event_type)

    def get_stream_events(self, stream_id: str, from_sequence: int = 0) -> list[StoredEvent]:
        """
        获取事件流中的所有事件

        用于事件溯源加载聚合根
        """
        return self._queries.stream(stream_id, from_sequence)

    def get_latest(self, limit: int = 100) -> list[StoredEvent]:
        """获取最新的事件"""
        return self._queries.latest(limit)

    @staticmethod
    def _compute_state_hash(state: dict[str, Any]) -> str:
        """计算 state 的 sha256 hash（用于校验快照完整性）"""
        return state_hash(state)

    def save_snapshot(self, stream_id: str, state: dict[str, Any], sequence_number: int) -> str:
        """
        保存聚合根快照

        - 保留最近 max_snapshots_per_stream 个快照
        - 计算 state_hash 存入 metadata 用于校验
        """
        return self._snapshot_store.save(stream_id, state, sequence_number)

    def _row_to_snapshot(self, row: sqlite3.Row) -> Snapshot:
        """将数据库行转换为 Snapshot"""
        return self._snapshot_store.from_row(row)

    def get_snapshot(self, stream_id: str) -> Snapshot | None:
        """获取最新快照"""
        return self._snapshot_store.latest(stream_id)

    def get_snapshot_history(self, stream_id: str, limit: int = 3) -> list[Snapshot]:
        """获取历史快照列表（按 created_at 降序，最新在前）"""
        return self._snapshot_store.history(stream_id, limit)

    def get_snapshot_at_version(self, stream_id: str, version: int) -> Snapshot | None:
        """获取指定 sequence_number 版本的快照"""
        return self._snapshot_store.at_version(stream_id, version)

    def get_events_after_snapshot(self, stream_id: str) -> list[StoredEvent]:
        """获取快照后的事件（用于恢复聚合根）"""
        return self._recovery.get_events_after_snapshot(stream_id)

    def replay(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        event_types: list[str] | None = None,
        stream_id: str | None = None,
        callback: Callable[[NeuroEvent], None] | None = None,
    ) -> int:
        """
        重播事件

        支持：
        - 时间范围筛选
        - 事件类型筛选
        - 特定流重播

        Returns:
            重播的事件数量
        """
        return self._recovery.replay(start_time, end_time, event_types, stream_id, callback)

    def replay_stream(
        self,
        stream_id: str,
        use_snapshot: bool = True,
        callback: Callable[[NeuroEvent], None] | None = None,
    ) -> dict[str, Any]:
        """
        重播事件流（用于恢复聚合根）

        - 启用快照时校验 state_hash，不一致则丢弃快照全量重放
        - 返回结果包含 snapshot_hash_verified 字段

        Returns:
            恢复的状态和元数据
        """
        return self._recovery.replay_stream(stream_id, use_snapshot, callback)

    def get_audit_log(
        self,
        stream_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取审计日志"""
        return self._recovery.get_audit_log(stream_id, start_time, end_time)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._queries.stats()

    def _get_stats_sqlite(self) -> dict[str, Any]:
        """SQLITE 模式统计信息"""
        return self._queries.sqlite_stats()

    def delete_stream(self, stream_id: str) -> int:
        """删除整个事件流（SQLITE 模式为逻辑删除，保留事件溯源完整性）"""
        return self._journal.delete_stream(stream_id)

    def clear(self) -> None:
        """清空所有数据（SQLITE 模式为物理清空，谨慎使用）"""
        self._journal.clear()

    def on_append(self, callback: Callable[[StoredEvent], None]) -> None:
        """注册追加回调"""
        self._append_callbacks.append(callback)

    def _cleanup_oldest(self, count: int = 1000) -> None:
        """
        清理最老的事件

        SQLITE 模式：逻辑删除（is_deleted=1），保留事件溯源完整性
        MEMORY 模式：物理删除
        """
        self._journal.cleanup_oldest(count)

    @property
    def _conn(self) -> sqlite3.Connection | None:
        return self._storage.connection

    @property
    def _sequence_counter(self) -> int:
        return self._state.sequence

    @_sequence_counter.setter
    def _sequence_counter(self, value: int) -> None:
        self._state.sequence = value

    def _notify_appends(self, records: list[StoredEvent]) -> None:
        for stored in records:
            logger.debug(
                "[EventStore] 事件存储: %s (store_id=%s)", stored.event.event_type, stored.store_id
            )
            for callback in self._append_callbacks:
                try:
                    callback(stored)
                except RECOVERABLE_ERRORS as error:
                    logger.error("[EventStore] 回调失败: %s", error)

    def close(self) -> None:
        """Release the owned SQLite connection; subsequent SQLite operations fail."""
        self._storage.close()


_event_store_instance: EventStore | None = None


def get_event_store(mode: EventStoreMode | None = None) -> EventStore:
    """获取全局事件存储实例"""
    global _event_store_instance
    if _event_store_instance is None:
        _event_store_instance = EventStore(mode=mode or EventStoreMode.MEMORY)
    elif mode is not None and _event_store_instance._mode != mode:
        _event_store_instance = EventStore(mode=mode)
    return _event_store_instance


def store_event(event: NeuroEvent, stream_id: str | None = None) -> str:
    """快捷函数：存储事件"""
    return get_event_store().append(event, stream_id)


def replay_events(**kwargs) -> int:
    """快捷函数：重播事件"""
    return get_event_store().replay(**kwargs)


def get_event_stats() -> dict[str, Any]:
    """快捷函数：获取统计"""
    return get_event_store().get_stats()
