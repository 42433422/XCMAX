# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.event_store")


class __EventStorePart01MixinPart01Mixin:
    def __init__(
        self,
        mode: _facade().EventStoreMode = _facade().EventStoreMode.MEMORY,
        storage_path: str | None = None,
        max_events: int = 100000,
        max_snapshots_per_stream: int = 3,
        upcaster_registry: _facade().UpcasterRegistry | None = None,
    ):
        self._mode = mode
        self._storage_path = storage_path
        self._max_events = max_events
        self._max_snapshots_per_stream = max_snapshots_per_stream
        self._upcaster_registry = upcaster_registry
        self._events: dict[str, _facade().StoredEvent] = {}
        self._stream_events: dict[str, list[str]] = {}
        self._snapshots: dict[str, list[_facade().Snapshot]] = {}
        self._sequence_counter = 0
        self._append_callbacks: list[_facade().Callable[[_facade().StoredEvent], None]] = []
        self._conn: _facade().sqlite3.Connection | None = None
        self._lock: _facade().threading.RLock = _facade().threading.RLock()
        if mode == _facade().EventStoreMode.SQLITE:
            self._init_sqlite()
        elif mode == _facade().EventStoreMode.JSON_FILE:
            _facade().logger.warning("[EventStore] JSON_FILE 模式尚未实现，将退化为内存存储")
        if self._upcaster_registry is not None:
            self._upcaster_registry.validate_chains()
        _facade().logger.info(
            "[EventStore] 初始化完成 (mode=%s, max_events=%s, max_snapshots=%s)",
            mode.value,
            max_events,
            max_snapshots_per_stream,
        )

    def _init_sqlite(self) -> None:
        """初始化 SQLITE 持久化存储"""
        if not self._storage_path:
            raise ValueError("[EventStore] SQLITE 模式必须提供 storage_path")
        self._conn = _facade().sqlite3.connect(
            self._storage_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = _facade().sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(
            "\n            CREATE TABLE IF NOT EXISTS neuro_events (\n                store_id TEXT PRIMARY KEY,\n                event_type TEXT NOT NULL,\n                event_data TEXT NOT NULL,\n                stream_id TEXT,\n                sequence_number INTEGER NOT NULL,\n                stored_at TEXT NOT NULL,\n                metadata TEXT,\n                is_deleted INTEGER DEFAULT 0\n            )\n            "
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_stream ON neuro_events(stream_id, sequence_number)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON neuro_events(event_type)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_stored_at ON neuro_events(stored_at)"
        )
        self._conn.execute(
            "\n            CREATE TABLE IF NOT EXISTS neuro_snapshots (\n                snapshot_id TEXT PRIMARY KEY,\n                stream_id TEXT NOT NULL,\n                sequence_number INTEGER NOT NULL,\n                state TEXT NOT NULL,\n                created_at TEXT NOT NULL,\n                version INTEGER DEFAULT 1,\n                metadata TEXT\n            )\n            "
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_stream ON neuro_snapshots(stream_id)"
        )
        cursor = self._conn.execute("PRAGMA table_info(neuro_snapshots)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "metadata" not in columns:
            self._conn.execute("ALTER TABLE neuro_snapshots ADD COLUMN metadata TEXT")
        cursor = self._conn.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) AS max_seq FROM neuro_events"
        )
        row = cursor.fetchone()
        if row and row["max_seq"]:
            self._sequence_counter = row["max_seq"]
        _facade().logger.info(
            "[EventStore] SQLITE 模式初始化完成 (path=%s, seq_start=%s)",
            self._storage_path,
            self._sequence_counter,
        )

    def _row_to_stored_event(self, row: _facade().sqlite3.Row) -> _facade().StoredEvent:
        """将数据库行转换为 StoredEvent（自动应用 upcaster 链）"""
        event = _facade().NeuroEvent.from_dict(
            _facade().json.loads(row["event_data"]), preserve_queue_identity=True
        )
        metadata = _facade().json.loads(row["metadata"]) if row["metadata"] else {}
        if self._upcaster_registry is not None:
            schema_version = metadata.get("event_schema_version", 1)
            new_payload, new_version = self._upcaster_registry.upcast(
                event.event_type, event.payload, schema_version
            )
            if new_version != schema_version:
                event.payload = new_payload
                metadata["event_schema_version"] = new_version
        return _facade().StoredEvent(
            store_id=row["store_id"],
            event=event,
            stored_at=_facade().datetime.fromisoformat(row["stored_at"]),
            sequence_number=row["sequence_number"],
            stream_id=row["stream_id"],
            metadata=metadata,
        )

    def _apply_upcasters_to_stored(self, stored: _facade().StoredEvent) -> _facade().StoredEvent:
        """对 MEMORY 模式读取的 StoredEvent 应用 upcaster（返回新对象）"""
        if self._upcaster_registry is None:
            return stored
        schema_version = stored.metadata.get("event_schema_version", 1)
        new_payload, new_version = self._upcaster_registry.upcast(
            stored.event.event_type, stored.event.payload, schema_version
        )
        if new_version == schema_version:
            return stored
        new_metadata = dict(stored.metadata)
        new_metadata["event_schema_version"] = new_version
        new_event = _facade().NeuroEvent(
            event_type=stored.event.event_type,
            payload=new_payload,
            priority=stored.event.priority,
            metadata=stored.event.metadata,
            preserve_queue_identity=True,
        )
        return _facade().StoredEvent(
            store_id=stored.store_id,
            event=new_event,
            stored_at=stored.stored_at,
            sequence_number=stored.sequence_number,
            stream_id=stored.stream_id,
            metadata=new_metadata,
        )

    def _get_stream_version(self, stream_id: str) -> int:
        """获取 stream 当前版本（事件数，0 表示空流）"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
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
            return
        actual = self._get_stream_version(stream_id) if stream_id else 0
        if expected_version == -1:
            if actual != 0:
                raise _facade().WrongExpectedVersionError(stream_id or "", -1, actual)
        elif expected_version >= 0:
            if actual != expected_version:
                raise _facade().WrongExpectedVersionError(stream_id or "", expected_version, actual)
        else:
            raise ValueError(f"[EventStore] 不支持的 expected_version 值: {expected_version}")

    def append(
        self,
        event: _facade().NeuroEvent,
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
        _facade().validate_event_schema(event)
        store_id = f"evt-{_facade().uuid4().hex[:12]}"
        with self._lock:
            self._check_expected_version(stream_id, expected_version)
            self._sequence_counter += 1
            sequence_number = self._sequence_counter
            event_metadata: dict[str, _facade().Any] = {}
            if self._upcaster_registry is not None:
                event_metadata["event_schema_version"] = (
                    self._upcaster_registry.get_current_version(event.event_type)
                )
            stored = _facade().StoredEvent(
                store_id=store_id,
                event=event,
                stored_at=_facade().datetime.now(),
                sequence_number=sequence_number,
                stream_id=stream_id,
                metadata=event_metadata,
            )
            if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
                self._append_sqlite(stored)
            else:
                if len(self._events) >= self._max_events:
                    self._cleanup_oldest()
                self._events[store_id] = stored
                if stream_id:
                    if stream_id not in self._stream_events:
                        self._stream_events[stream_id] = []
                    self._stream_events[stream_id].append(store_id)
        _facade().logger.debug(
            "[EventStore] 事件存储: %s (store_id=%s)", event.event_type, store_id
        )
        for callback in self._append_callbacks:
            try:
                callback(stored)
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.error("[EventStore] 回调失败: %s", e)
        return store_id

    def _append_sqlite(self, stored: _facade().StoredEvent) -> None:
        """SQLITE 模式下插入单条事件（含容量检查）"""
        assert self._conn is not None
        cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM neuro_events WHERE is_deleted = 0")
        row = cursor.fetchone()
        current_count = row["cnt"] if row else 0
        if current_count >= self._max_events:
            self._cleanup_oldest()
        with self._conn:
            self._conn.execute(
                "\n                INSERT INTO neuro_events\n                    (store_id, event_type, event_data, stream_id,\n                     sequence_number, stored_at, metadata, is_deleted)\n                VALUES (?, ?, ?, ?, ?, ?, ?, 0)\n                ",
                (
                    stored.store_id,
                    stored.event.event_type,
                    stored.event.to_json(),
                    stored.stream_id,
                    stored.sequence_number,
                    stored.stored_at.isoformat(),
                    _facade().json.dumps(stored.metadata, ensure_ascii=False)
                    if stored.metadata
                    else None,
                ),
            )

    def append_many(
        self,
        events: list[_facade().NeuroEvent],
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
            _facade().validate_event_schema(event)
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            store_ids: list[str] = []
            with self._lock:
                self._check_expected_version(stream_id, expected_version)
                with self._conn:
                    for event in events:
                        store_id = f"evt-{_facade().uuid4().hex[:12]}"
                        self._sequence_counter += 1
                        event_metadata: dict[str, _facade().Any] = {}
                        if self._upcaster_registry is not None:
                            event_metadata["event_schema_version"] = (
                                self._upcaster_registry.get_current_version(event.event_type)
                            )
                        stored = _facade().StoredEvent(
                            store_id=store_id,
                            event=event,
                            stored_at=_facade().datetime.now(),
                            sequence_number=self._sequence_counter,
                            stream_id=stream_id,
                            metadata=event_metadata,
                        )
                        self._conn.execute(
                            "\n                            INSERT INTO neuro_events\n                                (store_id, event_type, event_data, stream_id,\n                                 sequence_number, stored_at, metadata, is_deleted)\n                            VALUES (?, ?, ?, ?, ?, ?, ?, 0)\n                            ",
                            (
                                stored.store_id,
                                stored.event.event_type,
                                stored.event.to_json(),
                                stored.stream_id,
                                stored.sequence_number,
                                stored.stored_at.isoformat(),
                                _facade().json.dumps(stored.metadata, ensure_ascii=False)
                                if stored.metadata
                                else None,
                            ),
                        )
                        store_ids.append(store_id)
                        _facade().logger.debug(
                            "[EventStore] 事件存储: %s (store_id=%s)", event.event_type, store_id
                        )
                        for callback in self._append_callbacks:
                            try:
                                callback(stored)
                            except _facade().RECOVERABLE_ERRORS as e:
                                _facade().logger.error("[EventStore] 回调失败: %s", e)
            return store_ids
        memory_store_ids: list[str] = []
        for i, event in enumerate(events):
            ev = expected_version if i == 0 else None
            memory_store_ids.append(self.append(event, stream_id, expected_version=ev))
        return memory_store_ids

    def append_with_retry(
        self,
        stream_id: str,
        build_events: _facade().Callable[[list[_facade().StoredEvent]], list[_facade().NeuroEvent]],
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
        last_error: _facade().WrongExpectedVersionError | None = None
        for attempt in range(max_retries + 1):
            current_events = self.get_stream_events(stream_id)
            expected_version = len(current_events)
            new_events = build_events(current_events)
            if not new_events:
                return []
            try:
                return self.append_many(
                    new_events, stream_id=stream_id, expected_version=expected_version
                )
            except _facade().WrongExpectedVersionError as e:
                last_error = e
                if attempt < max_retries:
                    delay = base_delay * 2**attempt
                    _facade().logger.warning(
                        "[EventStore] 乐观并发冲突，%ss 后重试 (attempt=%s/%s, stream=%s)",
                        delay,
                        attempt + 1,
                        max_retries,
                        stream_id,
                    )
                    _facade().time.sleep(delay)
        if isinstance(last_error, BaseException):
            raise last_error
        raise RuntimeError("event append retries exhausted without a captured error")
