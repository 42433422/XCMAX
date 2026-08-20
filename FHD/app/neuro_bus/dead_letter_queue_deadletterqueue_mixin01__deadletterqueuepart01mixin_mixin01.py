# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.dead_letter_queue")


class __DeadLetterQueuePart01MixinPart01Mixin:
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
        self._entries: dict[str, _facade().DeadLetterEntry] = {}
        self._max_size = max_size
        self._retention_seconds = retention_hours * 3600
        self._alert_callbacks: list[_facade().Callable[[_facade().DeadLetterEntry], None]] = []
        self._replay_callbacks: list[_facade().Callable[[_facade().NeuroEvent], None]] = []
        self._stats = {"total_entries": 0, "replayed": 0, "expired": 0, "manually_resolved": 0}
        self._conn: _facade().sqlite3.Connection | None = None
        self._lock = _facade().threading.RLock()
        self._storage_path = storage_path
        if storage_path is not None:
            self._init_sqlite(storage_path)
        self._deduplicator = _facade().ReplayDeduplicator(conn=self._conn, lock=self._lock)
        self._alert_suppressor = _facade().AlertSuppressor(
            suppress_window=alert_suppress_window, threshold=alert_threshold
        )
        self._replay_paused = False
        _facade().logger.info(
            "[DeadLetterQueue] 初始化完成 (max_size=%s, retention=%sh, storage=%s, alert_window=%ss, alert_threshold=%s)",
            max_size,
            retention_hours,
            storage_path or "memory",
            alert_suppress_window,
            alert_threshold,
        )

    def _init_sqlite(self, storage_path: str) -> None:
        """初始化 SQLITE 持久化存储"""
        path = _facade().Path(storage_path)
        if path.parent and (not path.parent.exists()):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _facade().sqlite3.connect(
            storage_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = _facade().sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(
            "\n            CREATE TABLE IF NOT EXISTS neuro_dead_letters (\n                entry_id TEXT PRIMARY KEY,\n                event_type TEXT NOT NULL,\n                event_data TEXT NOT NULL,\n                reason TEXT NOT NULL,\n                error_message TEXT NOT NULL,\n                error_stack TEXT,\n                retry_count INTEGER DEFAULT 0,\n                first_failure_time TEXT NOT NULL,\n                last_failure_time TEXT NOT NULL,\n                handler_name TEXT,\n                metadata TEXT,\n                is_resolved INTEGER DEFAULT 0\n            )\n            "
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
        _facade().logger.info("[DeadLetterQueue] SQLITE 持久化已启用: %s", storage_path)

    def _row_to_entry(self, row: _facade().sqlite3.Row) -> _facade().DeadLetterEntry:
        """将 SQLITE 行转换为 DeadLetterEntry"""
        try:
            event_data = _facade().json.loads(row["event_data"])
            event = _facade().NeuroEvent.from_dict(event_data, preserve_queue_identity=True)
        except (_facade().json.JSONDecodeError, KeyError, ValueError) as e:
            _facade().logger.error(
                "[DeadLetterQueue] 反序列化事件失败 entry_id=%s: %s", row["entry_id"], e
            )
            event = _facade().NeuroEvent(event_type="__corrupt__", payload={})
        try:
            metadata = _facade().json.loads(row["metadata"]) if row["metadata"] else {}
        except _facade().json.JSONDecodeError:
            metadata = {}
        return _facade().DeadLetterEntry(
            entry_id=row["entry_id"],
            original_event=event,
            reason=_facade().DeadLetterReason(row["reason"]),
            error_message=row["error_message"],
            error_stack=row["error_stack"],
            retry_count=row["retry_count"],
            first_failure_time=_facade().datetime.fromisoformat(row["first_failure_time"]),
            last_failure_time=_facade().datetime.fromisoformat(row["last_failure_time"]),
            handler_name=row["handler_name"],
            metadata=metadata,
        )

    def enqueue(
        self,
        event: _facade().NeuroEvent,
        reason: _facade().DeadLetterReason,
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
        entry_id = f"dlq-{_facade().uuid4().hex[:12]}"
        now = _facade().datetime.now()
        metadata = {
            "enqueue_time": now.isoformat(),
            "original_event_id": event.metadata.event_id,
            "original_timestamp": event.metadata.timestamp,
            "original_domain": event.metadata.domain,
        }
        entry = _facade().DeadLetterEntry(
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
            if len(self._entries) >= self._max_size:
                self._evict_oldest()
            self._entries[entry_id] = entry
        self._stats["total_entries"] += 1
        _facade().logger.error(
            "[DeadLetterQueue] 事件进入死信队列: %s (reason=%s, entry_id=%s, retries=%s)",
            event.event_type,
            reason.value,
            entry_id,
            retry_count,
        )
        self._trigger_alert(entry)
        return entry_id

    def _enqueue_sqlite(self, entry: _facade().DeadLetterEntry) -> None:
        """SQLITE 模式入队"""
        assert self._conn is not None
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM neuro_dead_letters")
            count = cur.fetchone()[0]
            if count >= self._max_size:
                self._evict_oldest()
            self._conn.execute(
                "\n                INSERT INTO neuro_dead_letters\n                (entry_id, event_type, event_data, reason, error_message, error_stack,\n                 retry_count, first_failure_time, last_failure_time, handler_name,\n                 metadata, is_resolved)\n                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)\n                ",
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
                    _facade().json.dumps(entry.metadata, ensure_ascii=False),
                ),
            )

    def dequeue(self, entry_id: str) -> _facade().DeadLetterEntry | None:
        """取出条目（不移除）"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM neuro_dead_letters WHERE entry_id = ?", (entry_id,)
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
                    "DELETE FROM neuro_dead_letters WHERE entry_id = ?", (entry_id,)
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
            _facade().logger.warning("[DeadLetterQueue] 重播失败：找不到条目 %s", entry_id)
            return (False, "entry_not_found")
        if self._deduplicator.is_replayed(entry_id, entry.retry_count):
            _facade().logger.info(
                "[DeadLetterQueue] 跳过重播（已重播过）: %s (retry_count=%s)",
                entry_id,
                entry.retry_count,
            )
            return (False, "already_replayed")
        _facade().logger.info(
            "[DeadLetterQueue] 重播事件: %s (entry_id=%s)",
            entry.original_event.event_type,
            entry_id,
        )
        for callback in self._replay_callbacks:
            try:
                callback(entry.original_event)
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.error("[DeadLetterQueue] 重播回调失败: %s", e)
        self._deduplicator.mark_replayed(entry_id, entry.retry_count)
        self._stats["replayed"] += 1
        return (True, "")

    def _get_replay_candidates(
        self, event_type: str | None = None, max_age_seconds: float | None = None
    ) -> list[str]:
        """获取待重播的条目 ID 列表（按筛选条件）"""
        to_replay: list[str] = []
        if self._conn is not None:
            with self._lock:
                if event_type is not None and max_age_seconds is not None:
                    cur = self._conn.execute(
                        "\n                        SELECT entry_id, first_failure_time FROM neuro_dead_letters\n                        WHERE event_type = ?\n                        ",
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
        batch_sleep = batch_size / rate_limit_qps if rate_limit_qps > 0 else 0.0
        for i, entry_id in enumerate(to_replay):
            if self._is_replay_paused():
                _facade().logger.info("[DeadLetterQueue] 重播已暂停，停止于 %s/%s", i, total)
                break
            replayed, _ = self.replay(entry_id)
            if replayed:
                count += 1
            if (i + 1) % batch_size == 0 and i + 1 < total:
                if batch_sleep > 0:
                    _facade().time.sleep(batch_sleep)
        _facade().logger.info("[DeadLetterQueue] 批量重播完成: %s/%s 个事件", count, total)
        return count

    def pause_replay(self) -> None:
        """暂停重播（影响 replay_all / replay_with_progress / replay_gradual）"""
        with self._lock:
            self._replay_paused = True
        _facade().logger.info("[DeadLetterQueue] 重播已暂停")

    def resume_replay(self) -> None:
        """恢复重播"""
        with self._lock:
            self._replay_paused = False
        _facade().logger.info("[DeadLetterQueue] 重播已恢复")

    def _is_replay_paused(self) -> bool:
        """检查重播是否已暂停"""
        with self._lock:
            return self._replay_paused
