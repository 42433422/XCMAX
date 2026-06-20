"""
事件存储与重播 - Level 4 可靠性机制

提供：
- 事件持久化存储
- 事件溯源支持
- 快照管理
- 时间旅行（重播）
- 审计日志
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


# ========== 异常定义 ==========


class WrongExpectedVersionError(Exception):
    """乐观并发冲突：expected_version 与实际 stream version 不匹配"""

    def __init__(self, stream_id: str, expected: int, actual: int):
        self.stream_id = stream_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"[EventStore] 乐观并发冲突: stream={stream_id} expected_version={expected} actual_version={actual}"
        )


class InvalidEventError(Exception):
    """事件 schema 校验失败"""


# ========== 事件 Upcaster ==========


class EventUpcaster(ABC):
    """事件 upcaster 抽象基类 - 将事件 payload 从 from_version 升级到 to_version"""

    event_type: str
    from_version: int
    to_version: int

    @abstractmethod
    def upcast(self, payload: dict[str, Any]) -> dict[str, Any]:
        """将 payload 从 from_version 升级到 to_version（必须是纯函数）"""
        ...


class UpcasterRegistry:
    """upcaster 注册表 - 管理 event_type 的版本升级链"""

    def __init__(self) -> None:
        # (event_type, from_version) -> upcaster
        self._upcasters: dict[tuple[str, int], EventUpcaster] = {}
        # event_type -> current_version（最新版本号）
        self._current_versions: dict[str, int] = {}

    def register(self, upcaster: EventUpcaster) -> None:
        """注册一个 upcaster，并更新该 event_type 的当前版本"""
        key = (upcaster.event_type, upcaster.from_version)
        if key in self._upcasters:
            raise ValueError(
                f"[UpcasterRegistry] 重复注册: event_type={upcaster.event_type} from_version={upcaster.from_version}"
            )
        if upcaster.to_version != upcaster.from_version + 1:
            raise ValueError(
                f"[UpcasterRegistry] upcaster 必须连续升级: from={upcaster.from_version} to={upcaster.to_version}"
            )
        self._upcasters[key] = upcaster
        # 更新当前版本（取最大 to_version）
        prev = self._current_versions.get(upcaster.event_type, 1)
        self._current_versions[upcaster.event_type] = max(prev, upcaster.to_version)

    def get_chain(self, event_type: str, from_version: int, to_version: int) -> list[EventUpcaster]:
        """获取从 from_version 到 to_version 的 upcaster 链"""
        chain: list[EventUpcaster] = []
        current = from_version
        while current < to_version:
            upcaster = self._upcasters.get((event_type, current))
            if upcaster is None:
                raise ValueError(
                    f"[UpcasterRegistry] 链断裂: event_type={event_type} 缺少 from_version={current} 的 upcaster"
                )
            chain.append(upcaster)
            current = upcaster.to_version
        return chain

    def upcast(
        self, event_type: str, payload: dict[str, Any], from_version: int
    ) -> tuple[dict[str, Any], int]:
        """
        将 payload 从 from_version 升级到当前版本

        Returns:
            (升级后的 payload, 最终版本号)
        """
        target = self._current_versions.get(event_type, 1)
        if from_version >= target:
            return payload, from_version
        chain = self.get_chain(event_type, from_version, target)
        result = payload
        for upcaster in chain:
            result = upcaster.upcast(result)
        return result, target

    def get_current_version(self, event_type: str) -> int:
        """获取 event_type 的当前 schema 版本"""
        return self._current_versions.get(event_type, 1)

    def validate_chains(self) -> None:
        """校验所有注册的 upcaster 链完整（v1→v2→...→current 无断链）"""
        for event_type, target in self._current_versions.items():
            current = 1
            while current < target:
                if (event_type, current) not in self._upcasters:
                    raise ValueError(
                        f"[UpcasterRegistry] 链断裂: event_type={event_type} 缺少 from_version={current} 的 upcaster"
                    )
                current = self._upcasters[(event_type, current)].to_version


def validate_event_schema(event: NeuroEvent) -> bool:
    """
    校验事件结构

    - event_type 非空
    - payload 是 dict
    - metadata.event_id 非空

    校验失败抛出 InvalidEventError
    """
    if not event.event_type or not isinstance(event.event_type, str):
        raise InvalidEventError(f"event_type 必须是非空字符串，实际: {event.event_type!r}")
    if not isinstance(event.payload, dict):
        raise InvalidEventError(f"payload 必须是 dict，实际类型: {type(event.payload).__name__}")
    if not event.metadata.event_id:
        raise InvalidEventError("metadata.event_id 不能为空")
    return True


class EventStoreMode(Enum):
    """存储模式"""

    MEMORY = "memory"  # 内存存储（仅用于测试）
    JSON_FILE = "json"  # JSON 文件
    SQLITE = "sqlite"  # SQLite 数据库


@dataclass
class StoredEvent:
    """存储的事件记录"""

    store_id: str
    event: NeuroEvent
    stored_at: datetime
    sequence_number: int
    stream_id: str | None = None  # 事件流 ID（用于聚合根）
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "event": {
                "event_id": self.event.metadata.event_id,
                "event_type": self.event.event_type,
                "payload": self.event.payload,
                "timestamp": self.event.metadata.timestamp,
                "source": self.event.metadata.source,
                "correlation_id": self.event.metadata.correlation_id,
                "priority": self.event.priority.value,
            },
            "stored_at": self.stored_at.isoformat(),
            "sequence_number": self.sequence_number,
            "stream_id": self.stream_id,
            "metadata": self.metadata,
        }


@dataclass
class Snapshot:
    """聚合根快照"""

    snapshot_id: str
    stream_id: str
    sequence_number: int
    state: dict[str, Any]
    created_at: datetime
    version: int = 1
    # metadata 用于存储 state_hash 等校验信息
    metadata: dict[str, Any] = field(default_factory=dict)


class EventStore:
    """
    事件存储

    Level 4 可靠性机制:
    - 持久化所有领域事件
    - 支持事件溯源
    - 快照优化加载性能
    - 时间旅行调试
    """

    def __init__(
        self,
        mode: EventStoreMode = EventStoreMode.MEMORY,
        storage_path: str | None = None,
        max_events: int = 100000,
        max_snapshots_per_stream: int = 3,
        upcaster_registry: UpcasterRegistry | None = None,
    ):
        self._mode = mode
        self._storage_path = storage_path
        self._max_events = max_events
        self._max_snapshots_per_stream = max_snapshots_per_stream
        self._upcaster_registry = upcaster_registry

        # 内存存储
        self._events: dict[str, StoredEvent] = {}
        self._stream_events: dict[str, list[str]] = {}  # stream_id -> [store_id]
        # 多版本快照：stream_id -> [Snapshot]（按 created_at 升序，末尾为最新）
        self._snapshots: dict[str, list[Snapshot]] = {}

        # 序列号生成
        self._sequence_counter = 0

        # 回调
        self._append_callbacks: list[Callable[[StoredEvent], None]] = []

        # SQLITE 持久化资源
        self._conn: sqlite3.Connection | None = None
        self._lock: threading.RLock = threading.RLock()

        if mode == EventStoreMode.SQLITE:
            self._init_sqlite()
        elif mode == EventStoreMode.JSON_FILE:
            logger.warning("[EventStore] JSON_FILE 模式尚未实现，将退化为内存存储")

        # 启动时校验 upcaster 链完整
        if self._upcaster_registry is not None:
            self._upcaster_registry.validate_chains()

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

        # check_same_thread=False：NeuroBus 异步可能跨线程访问
        self._conn = sqlite3.connect(
            self._storage_path,
            check_same_thread=False,
            isolation_level=None,  # 自动提交模式，事务由 with conn 显式控制
        )
        self._conn.row_factory = sqlite3.Row

        # 事务安全配置
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")

        # 创建事件表
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS neuro_events (
                store_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL,
                stream_id TEXT,
                sequence_number INTEGER NOT NULL,
                stored_at TEXT NOT NULL,
                metadata TEXT,
                is_deleted INTEGER DEFAULT 0
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_stream ON neuro_events(stream_id, sequence_number)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON neuro_events(event_type)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_stored_at ON neuro_events(stored_at)"
        )

        # 创建快照表
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS neuro_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                stream_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                metadata TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_stream ON neuro_snapshots(stream_id)"
        )

        # 兼容旧表：若 metadata 列不存在则添加
        cursor = self._conn.execute("PRAGMA table_info(neuro_snapshots)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "metadata" not in columns:
            self._conn.execute("ALTER TABLE neuro_snapshots ADD COLUMN metadata TEXT")

        # 恢复序列号计数器（基于已有最大值）
        cursor = self._conn.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) AS max_seq FROM neuro_events"
        )
        row = cursor.fetchone()
        if row and row["max_seq"]:
            self._sequence_counter = row["max_seq"]

        logger.info(
            "[EventStore] SQLITE 模式初始化完成 (path=%s, seq_start=%s)",
            self._storage_path,
            self._sequence_counter,
        )

    def _row_to_stored_event(self, row: sqlite3.Row) -> StoredEvent:
        """将数据库行转换为 StoredEvent（自动应用 upcaster 链）"""
        event = NeuroEvent.from_dict(json.loads(row["event_data"]), preserve_queue_identity=True)
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        # 应用 upcaster：将 payload 升级到当前 schema 版本
        if self._upcaster_registry is not None:
            schema_version = metadata.get("event_schema_version", 1)
            new_payload, new_version = self._upcaster_registry.upcast(
                event.event_type, event.payload, schema_version
            )
            if new_version != schema_version:
                event.payload = new_payload
                metadata["event_schema_version"] = new_version

        return StoredEvent(
            store_id=row["store_id"],
            event=event,
            stored_at=datetime.fromisoformat(row["stored_at"]),
            sequence_number=row["sequence_number"],
            stream_id=row["stream_id"],
            metadata=metadata,
        )

    def _apply_upcasters_to_stored(self, stored: StoredEvent) -> StoredEvent:
        """对 MEMORY 模式读取的 StoredEvent 应用 upcaster（返回新对象）"""
        if self._upcaster_registry is None:
            return stored
        schema_version = stored.metadata.get("event_schema_version", 1)
        new_payload, new_version = self._upcaster_registry.upcast(
            stored.event.event_type, stored.event.payload, schema_version
        )
        if new_version == schema_version:
            return stored
        # 复制并更新（不修改原对象）
        new_metadata = dict(stored.metadata)
        new_metadata["event_schema_version"] = new_version
        new_event = NeuroEvent(
            event_type=stored.event.event_type,
            payload=new_payload,
            priority=stored.event.priority,
            metadata=stored.event.metadata,
            preserve_queue_identity=True,
        )
        return StoredEvent(
            store_id=stored.store_id,
            event=new_event,
            stored_at=stored.stored_at,
            sequence_number=stored.sequence_number,
            stream_id=stored.stream_id,
            metadata=new_metadata,
        )

    def _get_stream_version(self, stream_id: str) -> int:
        """获取 stream 当前版本（事件数，0 表示空流）"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM neuro_events WHERE stream_id = ? AND is_deleted = 0",
                (stream_id,),
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0
        return len(self._stream_events.get(stream_id, []))

    def _check_expected_version(self, stream_id: str | None, expected_version: int | None) -> None:
        """乐观并发检查"""
        if expected_version is None or expected_version == -2:
            # None：无检查（向后兼容）；-2：stream 存在与否皆可
            return

        actual = self._get_stream_version(stream_id) if stream_id else 0

        if expected_version == -1:
            # stream 必须不存在（创建）
            if actual != 0:
                raise WrongExpectedVersionError(stream_id or "", -1, actual)
        elif expected_version >= 0:
            # stream 当前 version 必须为 N
            if actual != expected_version:
                raise WrongExpectedVersionError(stream_id or "", expected_version, actual)
        else:
            raise ValueError(f"[EventStore] 不支持的 expected_version 值: {expected_version}")

    # ========== 存储操作 ==========

    def append(
        self,
        event: NeuroEvent,
        stream_id: str | None = None,
        expected_version: int | None = None,
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
        # schema 校验
        validate_event_schema(event)

        store_id = f"evt-{uuid4().hex[:12]}"

        with self._lock:
            # 乐观并发检查
            self._check_expected_version(stream_id, expected_version)

            self._sequence_counter += 1
            sequence_number = self._sequence_counter

            # 记录 schema 版本到 metadata
            event_metadata: dict[str, Any] = {}
            if self._upcaster_registry is not None:
                event_metadata["event_schema_version"] = (
                    self._upcaster_registry.get_current_version(event.event_type)
                )

            stored = StoredEvent(
                store_id=store_id,
                event=event,
                stored_at=datetime.now(),
                sequence_number=sequence_number,
                stream_id=stream_id,
                metadata=event_metadata,
            )

            if self._mode == EventStoreMode.SQLITE and self._conn is not None:
                self._append_sqlite(stored)
            else:
                # MEMORY 模式（或 JSON_FILE 退化）
                # 容量检查
                if len(self._events) >= self._max_events:
                    self._cleanup_oldest()

                # 存储
                self._events[store_id] = stored

                # 按流索引
                if stream_id:
                    if stream_id not in self._stream_events:
                        self._stream_events[stream_id] = []
                    self._stream_events[stream_id].append(store_id)

        logger.debug("[EventStore] 事件存储: %s (store_id=%s)", event.event_type, store_id)

        # 触发回调（锁外执行，避免回调内再次 append 导致死锁）
        for callback in self._append_callbacks:
            try:
                callback(stored)
            except RECOVERABLE_ERRORS as e:
                logger.error("[EventStore] 回调失败: %s", e)

        return store_id

    def _append_sqlite(self, stored: StoredEvent) -> None:
        """SQLITE 模式下插入单条事件（含容量检查）"""
        assert self._conn is not None

        # 容量检查（基于未删除事件计数）
        cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM neuro_events WHERE is_deleted = 0")
        row = cursor.fetchone()
        current_count = row["cnt"] if row else 0

        if current_count >= self._max_events:
            self._cleanup_oldest()

        # 插入事件（事务包裹）
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO neuro_events
                    (store_id, event_type, event_data, stream_id,
                     sequence_number, stored_at, metadata, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    stored.store_id,
                    stored.event.event_type,
                    stored.event.to_json(),
                    stored.stream_id,
                    stored.sequence_number,
                    stored.stored_at.isoformat(),
                    json.dumps(stored.metadata, ensure_ascii=False) if stored.metadata else None,
                ),
            )

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

        # schema 校验
        for event in events:
            validate_event_schema(event)

        # SQLITE 模式：用单个事务包裹所有 append，保证原子性
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            store_ids: list[str] = []
            with self._lock:
                # 乐观并发检查（在事务开始前）
                self._check_expected_version(stream_id, expected_version)

                with self._conn:
                    for event in events:
                        store_id = f"evt-{uuid4().hex[:12]}"
                        self._sequence_counter += 1

                        # 记录 schema 版本
                        event_metadata: dict[str, Any] = {}
                        if self._upcaster_registry is not None:
                            event_metadata["event_schema_version"] = (
                                self._upcaster_registry.get_current_version(event.event_type)
                            )

                        stored = StoredEvent(
                            store_id=store_id,
                            event=event,
                            stored_at=datetime.now(),
                            sequence_number=self._sequence_counter,
                            stream_id=stream_id,
                            metadata=event_metadata,
                        )
                        self._conn.execute(
                            """
                            INSERT INTO neuro_events
                                (store_id, event_type, event_data, stream_id,
                                 sequence_number, stored_at, metadata, is_deleted)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                            """,
                            (
                                stored.store_id,
                                stored.event.event_type,
                                stored.event.to_json(),
                                stored.stream_id,
                                stored.sequence_number,
                                stored.stored_at.isoformat(),
                                json.dumps(stored.metadata, ensure_ascii=False)
                                if stored.metadata
                                else None,
                            ),
                        )
                        store_ids.append(store_id)

                        logger.debug(
                            "[EventStore] 事件存储: %s (store_id=%s)",
                            event.event_type,
                            store_id,
                        )

                        # 触发回调
                        for callback in self._append_callbacks:
                            try:
                                callback(stored)
                            except RECOVERABLE_ERRORS as e:
                                logger.error("[EventStore] 回调失败: %s", e)

            return store_ids

        # MEMORY 模式：逐条 append（首条带 expected_version，后续无检查）
        store_ids: list[str] = []
        for i, event in enumerate(events):
            ev = expected_version if i == 0 else None
            store_ids.append(self.append(event, stream_id, expected_version=ev))
        return store_ids

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
        last_error: WrongExpectedVersionError | None = None
        for attempt in range(max_retries + 1):
            # 重新 load 当前流状态
            current_events = self.get_stream_events(stream_id)
            expected_version = len(current_events)

            # reapply：让调用方基于当前状态计算新事件
            new_events = build_events(current_events)
            if not new_events:
                return []

            try:
                return self.append_many(
                    new_events, stream_id=stream_id, expected_version=expected_version
                )
            except WrongExpectedVersionError as e:
                last_error = e
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "[EventStore] 乐观并发冲突，%ss 后重试 (attempt=%s/%s, stream=%s)",
                        delay,
                        attempt + 1,
                        max_retries,
                        stream_id,
                    )
                    time.sleep(delay)

        # 重试耗尽
        raise last_error  # type: ignore[misc]

    # ========== 查询操作 ==========

    def get(self, store_id: str) -> StoredEvent | None:
        """获取单个事件"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "SELECT * FROM neuro_events WHERE store_id = ? AND is_deleted = 0",
                (store_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_stored_event(row)
        stored = self._events.get(store_id)
        if stored is None:
            return None
        return self._apply_upcasters_to_stored(stored)

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
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            # 动态构建 SQL 查询
            query = "SELECT * FROM neuro_events WHERE is_deleted = 0"
            params: list[Any] = []

            if start_time is not None:
                query += " AND stored_at >= ?"
                params.append(start_time.isoformat())
            if end_time is not None:
                query += " AND stored_at <= ?"
                params.append(end_time.isoformat())
            if event_type is not None:
                query += " AND event_type = ?"
                params.append(event_type)

            query += " ORDER BY sequence_number ASC"

            cursor = self._conn.execute(query, params)
            for row in cursor:
                yield self._row_to_stored_event(row)
            return

        # MEMORY 模式
        for stored in sorted(self._events.values(), key=lambda e: e.sequence_number):
            # 时间筛选
            if start_time and stored.stored_at < start_time:
                continue
            if end_time and stored.stored_at > end_time:
                continue

            # 类型筛选
            if event_type and stored.event.event_type != event_type:
                continue

            yield self._apply_upcasters_to_stored(stored)

    def get_stream_events(
        self,
        stream_id: str,
        from_sequence: int = 0,
    ) -> list[StoredEvent]:
        """
        获取事件流中的所有事件

        用于事件溯源加载聚合根
        """
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM neuro_events
                WHERE stream_id = ? AND sequence_number >= ? AND is_deleted = 0
                ORDER BY sequence_number ASC
                """,
                (stream_id, from_sequence),
            )
            return [self._row_to_stored_event(row) for row in cursor.fetchall()]

        # MEMORY 模式
        store_ids = self._stream_events.get(stream_id, [])
        events = []

        for store_id in store_ids:
            stored = self._events.get(store_id)
            if stored and stored.sequence_number >= from_sequence:
                events.append(self._apply_upcasters_to_stored(stored))

        return sorted(events, key=lambda e: e.sequence_number)

    def get_latest(self, limit: int = 100) -> list[StoredEvent]:
        """获取最新的事件"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM neuro_events
                WHERE is_deleted = 0
                ORDER BY sequence_number DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_stored_event(row) for row in cursor.fetchall()]

        # MEMORY 模式
        sorted_events = sorted(self._events.values(), key=lambda e: e.sequence_number, reverse=True)
        return [self._apply_upcasters_to_stored(s) for s in sorted_events[:limit]]

    # ========== 快照管理 ==========

    @staticmethod
    def _compute_state_hash(state: dict[str, Any]) -> str:
        """计算 state 的 sha256 hash（用于校验快照完整性）"""
        return hashlib.sha256(
            json.dumps(state, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def save_snapshot(
        self,
        stream_id: str,
        state: dict[str, Any],
        sequence_number: int,
    ) -> str:
        """
        保存聚合根快照

        - 保留最近 max_snapshots_per_stream 个快照
        - 计算 state_hash 存入 metadata 用于校验
        """
        snapshot_id = f"snap-{uuid4().hex[:12]}"
        state_hash = self._compute_state_hash(state)

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            stream_id=stream_id,
            sequence_number=sequence_number,
            state=state,
            created_at=datetime.now(),
            metadata={"state_hash": state_hash},
        )

        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            with self._lock:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO neuro_snapshots
                            (snapshot_id, stream_id, sequence_number,
                             state, created_at, version, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot.snapshot_id,
                            snapshot.stream_id,
                            snapshot.sequence_number,
                            json.dumps(snapshot.state, ensure_ascii=False),
                            snapshot.created_at.isoformat(),
                            snapshot.version,
                            json.dumps(snapshot.metadata, ensure_ascii=False),
                        ),
                    )
                    # 清理旧快照，只保留最近 max_snapshots_per_stream 个
                    self._conn.execute(
                        """
                        DELETE FROM neuro_snapshots
                        WHERE snapshot_id IN (
                            SELECT snapshot_id FROM (
                                SELECT snapshot_id,
                                       ROW_NUMBER() OVER (
                                           ORDER BY created_at DESC
                                       ) AS rn
                                FROM neuro_snapshots
                                WHERE stream_id = ?
                            ) WHERE rn > ?
                        )
                        """,
                        (stream_id, self._max_snapshots_per_stream),
                    )
        else:
            # MEMORY 模式
            with self._lock:
                snapshots_list = self._snapshots.setdefault(stream_id, [])
                snapshots_list.append(snapshot)
                # 保留最近 N 个（按 created_at 升序，末尾为最新）
                if len(snapshots_list) > self._max_snapshots_per_stream:
                    self._snapshots[stream_id] = snapshots_list[-self._max_snapshots_per_stream :]

        logger.debug(
            "[EventStore] 快照保存: %s (seq=%s, snap_id=%s, hash=%s)",
            stream_id,
            sequence_number,
            snapshot_id,
            state_hash[:8],
        )

        return snapshot_id

    def _row_to_snapshot(self, row: sqlite3.Row) -> Snapshot:
        """将数据库行转换为 Snapshot"""
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        return Snapshot(
            snapshot_id=row["snapshot_id"],
            stream_id=row["stream_id"],
            sequence_number=row["sequence_number"],
            state=json.loads(row["state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            version=row["version"],
            metadata=metadata,
        )

    def get_snapshot(self, stream_id: str) -> Snapshot | None:
        """获取最新快照"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM neuro_snapshots
                WHERE stream_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (stream_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_snapshot(row)
        # MEMORY 模式
        snapshots_list = self._snapshots.get(stream_id, [])
        if not snapshots_list:
            return None
        return snapshots_list[-1]

    def get_snapshot_history(self, stream_id: str, limit: int = 3) -> list[Snapshot]:
        """获取历史快照列表（按 created_at 降序，最新在前）"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM neuro_snapshots
                WHERE stream_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (stream_id, limit),
            )
            return [self._row_to_snapshot(row) for row in cursor.fetchall()]
        # MEMORY 模式
        snapshots_list = self._snapshots.get(stream_id, [])
        return list(reversed(snapshots_list))[:limit]

    def get_snapshot_at_version(self, stream_id: str, version: int) -> Snapshot | None:
        """获取指定 sequence_number 版本的快照"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM neuro_snapshots
                WHERE stream_id = ? AND sequence_number = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (stream_id, version),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_snapshot(row)
        # MEMORY 模式
        snapshots_list = self._snapshots.get(stream_id, [])
        for snap in reversed(snapshots_list):
            if snap.sequence_number == version:
                return snap
        return None

    def get_events_after_snapshot(self, stream_id: str) -> list[StoredEvent]:
        """获取快照后的事件（用于恢复聚合根）"""
        snapshot = self.get_snapshot(stream_id)
        if not snapshot:
            # 没有快照，返回所有事件
            return self.get_stream_events(stream_id)

        # 返回快照之后的事件
        return self.get_stream_events(stream_id, from_sequence=snapshot.sequence_number + 1)

    # ========== 重播机制 ==========

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
        count = 0

        if stream_id:
            # 重播特定流
            events = self.get_stream_events(stream_id)
        else:
            # 重播所有事件
            events = list(self.get_all(start_time, end_time))

        for stored in events:
            # 类型筛选
            if event_types and stored.event.event_type not in event_types:
                continue

            # 执行重播
            if callback:
                try:
                    callback(stored.event)
                    count += 1
                except RECOVERABLE_ERRORS as e:
                    logger.error("[EventStore] 重播失败: %s", e)
            else:
                # 默认：只记录
                logger.info(
                    "[EventStore] 重播: %s (store_id=%s)", stored.event.event_type, stored.store_id
                )
                count += 1

        logger.info("[EventStore] 重播完成: %s 个事件", count)
        return count

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
        snapshot = None
        start_sequence = 0
        snapshot_hash_verified = True

        if use_snapshot:
            snapshot = self.get_snapshot(stream_id)
            if snapshot:
                # 校验 state_hash
                stored_hash = snapshot.metadata.get("state_hash")
                if stored_hash is not None:
                    actual_hash = self._compute_state_hash(snapshot.state)
                    if stored_hash != actual_hash:
                        logger.warning(
                            "[EventStore] 快照 state_hash 校验失败，丢弃快照全量重放: "
                            "stream=%s snap_id=%s expected=%s actual=%s",
                            stream_id,
                            snapshot.snapshot_id,
                            stored_hash[:8],
                            actual_hash[:8],
                        )
                        snapshot = None
                        snapshot_hash_verified = False
                start_sequence = snapshot.sequence_number + 1 if snapshot else 0

        events = self.get_stream_events(stream_id, from_sequence=start_sequence)

        applied_count = 0
        for stored in events:
            if callback:
                callback(stored.event)
            applied_count += 1

        result: dict[str, Any] = {
            "stream_id": stream_id,
            "applied_events": applied_count,
            "snapshot_used": snapshot is not None,
            "snapshot_hash_verified": snapshot_hash_verified,
        }

        if snapshot:
            result["snapshot_sequence"] = snapshot.sequence_number
            result["snapshot_age_seconds"] = (datetime.now() - snapshot.created_at).total_seconds()

        logger.info("[EventStore] 流重播完成: %s (applied=%s)", stream_id, applied_count)

        return result

    # ========== 审计 ==========

    def get_audit_log(
        self,
        stream_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取审计日志"""
        if stream_id:
            events = self.get_stream_events(stream_id)
        else:
            events = list(self.get_all(start_time, end_time))

        return [
            {
                "timestamp": e.stored_at.isoformat(),
                "event_type": e.event.event_type,
                "event_id": e.event.metadata.event_id,
                "source": e.event.metadata.source,
                "correlation_id": e.event.metadata.trace_id,
                "payload_keys": list(e.event.payload.keys()),
            }
            for e in events
        ]

    # ========== 统计 ==========

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            return self._get_stats_sqlite()

        # MEMORY 模式
        by_type = {}
        for stored in self._events.values():
            et = stored.event.event_type
            by_type[et] = by_type.get(et, 0) + 1

        by_stream = {
            stream_id: len(store_ids) for stream_id, store_ids in self._stream_events.items()
        }

        # 快照总数（多版本）
        snapshots_count = sum(len(snaps) for snaps in self._snapshots.values())

        return {
            "total_events": len(self._events),
            "max_events": self._max_events,
            "streams": len(self._stream_events),
            "snapshots": snapshots_count,
            "by_event_type": by_type,
            "by_stream": by_stream,
            "oldest_event": (
                min(e.stored_at for e in self._events.values()).isoformat()
                if self._events
                else None
            ),
            "newest_event": (
                max(e.stored_at for e in self._events.values()).isoformat()
                if self._events
                else None
            ),
        }

    def _get_stats_sqlite(self) -> dict[str, Any]:
        """SQLITE 模式统计信息"""
        assert self._conn is not None

        # 总事件数（未删除）
        cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM neuro_events WHERE is_deleted = 0")
        total_events = cursor.fetchone()["cnt"]

        # 按事件类型分组
        cursor = self._conn.execute(
            """
            SELECT event_type, COUNT(*) AS cnt
            FROM neuro_events
            WHERE is_deleted = 0
            GROUP BY event_type
            """
        )
        by_type = {row["event_type"]: row["cnt"] for row in cursor.fetchall()}

        # 按流分组
        cursor = self._conn.execute(
            """
            SELECT stream_id, COUNT(*) AS cnt
            FROM neuro_events
            WHERE is_deleted = 0 AND stream_id IS NOT NULL
            GROUP BY stream_id
            """
        )
        by_stream = {row["stream_id"]: row["cnt"] for row in cursor.fetchall()}

        # 流数（去重）
        cursor = self._conn.execute(
            "SELECT COUNT(DISTINCT stream_id) AS cnt FROM neuro_events WHERE is_deleted = 0 AND stream_id IS NOT NULL"
        )
        streams_count = cursor.fetchone()["cnt"]

        # 快照数
        cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM neuro_snapshots")
        snapshots_count = cursor.fetchone()["cnt"]

        # 最早/最新事件
        cursor = self._conn.execute(
            "SELECT stored_at FROM neuro_events WHERE is_deleted = 0 ORDER BY stored_at ASC LIMIT 1"
        )
        oldest_row = cursor.fetchone()
        oldest_event = oldest_row["stored_at"] if oldest_row else None

        cursor = self._conn.execute(
            "SELECT stored_at FROM neuro_events WHERE is_deleted = 0 ORDER BY stored_at DESC LIMIT 1"
        )
        newest_row = cursor.fetchone()
        newest_event = newest_row["stored_at"] if newest_row else None

        return {
            "total_events": total_events,
            "max_events": self._max_events,
            "streams": streams_count,
            "snapshots": snapshots_count,
            "by_event_type": by_type,
            "by_stream": by_stream,
            "oldest_event": oldest_event,
            "newest_event": newest_event,
        }

    # ========== 管理 ==========

    def delete_stream(self, stream_id: str) -> int:
        """删除整个事件流（SQLITE 模式为逻辑删除，保留事件溯源完整性）"""
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            with self._lock:
                with self._conn:
                    # 逻辑删除事件（不破坏事件溯源）
                    cursor = self._conn.execute(
                        """
                        UPDATE neuro_events
                        SET is_deleted = 1
                        WHERE stream_id = ? AND is_deleted = 0
                        """,
                        (stream_id,),
                    )
                    count = cursor.rowcount

                    # 物理删除快照（快照可重建，且不参与事件溯源）
                    self._conn.execute(
                        "DELETE FROM neuro_snapshots WHERE stream_id = ?",
                        (stream_id,),
                    )

            logger.info("[EventStore] 删除流: %s (%s 个事件，逻辑删除)", stream_id, count)
            return count

        # MEMORY 模式：物理删除
        store_ids = self._stream_events.get(stream_id, [])
        count = 0

        for store_id in store_ids:
            if store_id in self._events:
                del self._events[store_id]
                count += 1

        if stream_id in self._stream_events:
            del self._stream_events[stream_id]

        if stream_id in self._snapshots:
            del self._snapshots[stream_id]

        logger.info("[EventStore] 删除流: %s (%s 个事件)", stream_id, count)
        return count

    def clear(self):
        """清空所有数据（SQLITE 模式为物理清空，谨慎使用）"""
        with self._lock:
            if self._mode == EventStoreMode.SQLITE and self._conn is not None:
                with self._conn:
                    self._conn.execute("DELETE FROM neuro_events")
                    self._conn.execute("DELETE FROM neuro_snapshots")
            else:
                # MEMORY 模式
                self._events.clear()
                self._stream_events.clear()
                self._snapshots.clear()

            self._sequence_counter = 0
        logger.info("[EventStore] 已清空")

    def on_append(self, callback: Callable[[StoredEvent], None]):
        """注册追加回调"""
        self._append_callbacks.append(callback)

    def _cleanup_oldest(self, count: int = 1000):
        """
        清理最老的事件

        SQLITE 模式：逻辑删除（is_deleted=1），保留事件溯源完整性
        MEMORY 模式：物理删除
        """
        if self._mode == EventStoreMode.SQLITE and self._conn is not None:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    UPDATE neuro_events
                    SET is_deleted = 1
                    WHERE store_id IN (
                        SELECT store_id FROM neuro_events
                        WHERE is_deleted = 0
                        ORDER BY sequence_number ASC
                        LIMIT ?
                    )
                    """,
                    (count,),
                )
                removed = cursor.rowcount
            logger.warning("[EventStore] 清理旧事件: %s 个（逻辑删除）", removed)
            return

        # MEMORY 模式：物理删除
        sorted_events = sorted(self._events.values(), key=lambda e: e.sequence_number)
        to_remove = sorted_events[:count]

        for stored in to_remove:
            del self._events[stored.store_id]

            # 从流索引中移除
            if stored.stream_id and stored.stream_id in self._stream_events:
                stream_list = self._stream_events[stored.stream_id]
                if stored.store_id in stream_list:
                    stream_list.remove(stored.store_id)

        logger.warning("[EventStore] 清理旧事件: %s 个", len(to_remove))


# ========== 全局实例 ==========

_event_store_instance: EventStore | None = None


def get_event_store() -> EventStore:
    """获取全局事件存储实例"""
    global _event_store_instance
    if _event_store_instance is None:
        _event_store_instance = EventStore()
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
