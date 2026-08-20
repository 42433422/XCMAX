# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.event_store")


class __EventStorePart01MixinPart02Mixin:
    def get(self, store_id: str) -> _facade().StoredEvent | None:
        """获取单个事件"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "SELECT * FROM neuro_events WHERE store_id = ? AND is_deleted = 0", (store_id,)
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
        start_time: _facade().datetime | None = None,
        end_time: _facade().datetime | None = None,
        event_type: str | None = None,
    ) -> _facade().Iterator[_facade().StoredEvent]:
        """
        获取事件流

        支持时间范围和事件类型筛选
        """
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            query = "SELECT * FROM neuro_events WHERE is_deleted = 0"
            params: list[_facade().Any] = []
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
        for stored in sorted(self._events.values(), key=lambda e: e.sequence_number):
            if start_time and stored.stored_at < start_time:
                continue
            if end_time and stored.stored_at > end_time:
                continue
            if event_type and stored.event.event_type != event_type:
                continue
            yield self._apply_upcasters_to_stored(stored)

    def get_stream_events(
        self, stream_id: str, from_sequence: int = 0
    ) -> list[_facade().StoredEvent]:
        """
        获取事件流中的所有事件

        用于事件溯源加载聚合根
        """
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "\n                SELECT * FROM neuro_events\n                WHERE stream_id = ? AND sequence_number >= ? AND is_deleted = 0\n                ORDER BY sequence_number ASC\n                ",
                (stream_id, from_sequence),
            )
            return [self._row_to_stored_event(row) for row in cursor.fetchall()]
        store_ids = self._stream_events.get(stream_id, [])
        events = []
        for store_id in store_ids:
            stored = self._events.get(store_id)
            if stored and stored.sequence_number >= from_sequence:
                events.append(self._apply_upcasters_to_stored(stored))
        return sorted(events, key=lambda e: e.sequence_number)

    def get_latest(self, limit: int = 100) -> list[_facade().StoredEvent]:
        """获取最新的事件"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "\n                SELECT * FROM neuro_events\n                WHERE is_deleted = 0\n                ORDER BY sequence_number DESC\n                LIMIT ?\n                ",
                (limit,),
            )
            return [self._row_to_stored_event(row) for row in cursor.fetchall()]
        sorted_events = sorted(self._events.values(), key=lambda e: e.sequence_number, reverse=True)
        return [self._apply_upcasters_to_stored(s) for s in sorted_events[:limit]]

    @staticmethod
    def _compute_state_hash(state: dict[str, _facade().Any]) -> str:
        """计算 state 的 sha256 hash（用于校验快照完整性）"""
        return (
            _facade()
            .hashlib.sha256(
                _facade().json.dumps(state, sort_keys=True, ensure_ascii=False).encode()
            )
            .hexdigest()
        )

    def save_snapshot(
        self, stream_id: str, state: dict[str, _facade().Any], sequence_number: int
    ) -> str:
        """
        保存聚合根快照

        - 保留最近 max_snapshots_per_stream 个快照
        - 计算 state_hash 存入 metadata 用于校验
        """
        snapshot_id = f"snap-{_facade().uuid4().hex[:12]}"
        state_hash = self._compute_state_hash(state)
        snapshot = _facade().Snapshot(
            snapshot_id=snapshot_id,
            stream_id=stream_id,
            sequence_number=sequence_number,
            state=state,
            created_at=_facade().datetime.now(),
            metadata={"state_hash": state_hash},
        )
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            with self._lock:
                with self._conn:
                    self._conn.execute(
                        "\n                        INSERT INTO neuro_snapshots\n                            (snapshot_id, stream_id, sequence_number,\n                             state, created_at, version, metadata)\n                        VALUES (?, ?, ?, ?, ?, ?, ?)\n                        ",
                        (
                            snapshot.snapshot_id,
                            snapshot.stream_id,
                            snapshot.sequence_number,
                            _facade().json.dumps(snapshot.state, ensure_ascii=False),
                            snapshot.created_at.isoformat(),
                            snapshot.version,
                            _facade().json.dumps(snapshot.metadata, ensure_ascii=False),
                        ),
                    )
                    self._conn.execute(
                        "\n                        DELETE FROM neuro_snapshots\n                        WHERE snapshot_id IN (\n                            SELECT snapshot_id FROM (\n                                SELECT snapshot_id,\n                                       ROW_NUMBER() OVER (\n                                           ORDER BY created_at DESC\n                                       ) AS rn\n                                FROM neuro_snapshots\n                                WHERE stream_id = ?\n                            ) WHERE rn > ?\n                        )\n                        ",
                        (stream_id, self._max_snapshots_per_stream),
                    )
        else:
            with self._lock:
                snapshots_list = self._snapshots.setdefault(stream_id, [])
                snapshots_list.append(snapshot)
                if len(snapshots_list) > self._max_snapshots_per_stream:
                    self._snapshots[stream_id] = snapshots_list[-self._max_snapshots_per_stream :]
        _facade().logger.debug(
            "[EventStore] 快照保存: %s (seq=%s, snap_id=%s, hash=%s)",
            stream_id,
            sequence_number,
            snapshot_id,
            state_hash[:8],
        )
        return snapshot_id

    def _row_to_snapshot(self, row: _facade().sqlite3.Row) -> _facade().Snapshot:
        """将数据库行转换为 Snapshot"""
        metadata = _facade().json.loads(row["metadata"]) if row["metadata"] else {}
        return _facade().Snapshot(
            snapshot_id=row["snapshot_id"],
            stream_id=row["stream_id"],
            sequence_number=row["sequence_number"],
            state=_facade().json.loads(row["state"]),
            created_at=_facade().datetime.fromisoformat(row["created_at"]),
            version=row["version"],
            metadata=metadata,
        )

    def get_snapshot(self, stream_id: str) -> _facade().Snapshot | None:
        """获取最新快照"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "\n                SELECT * FROM neuro_snapshots\n                WHERE stream_id = ?\n                ORDER BY created_at DESC\n                LIMIT 1\n                ",
                (stream_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_snapshot(row)
        snapshots_list = self._snapshots.get(stream_id, [])
        if not snapshots_list:
            return None
        return snapshots_list[-1]

    def get_snapshot_history(self, stream_id: str, limit: int = 3) -> list[_facade().Snapshot]:
        """获取历史快照列表（按 created_at 降序，最新在前）"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "\n                SELECT * FROM neuro_snapshots\n                WHERE stream_id = ?\n                ORDER BY created_at DESC\n                LIMIT ?\n                ",
                (stream_id, limit),
            )
            return [self._row_to_snapshot(row) for row in cursor.fetchall()]
        snapshots_list = self._snapshots.get(stream_id, [])
        return list(reversed(snapshots_list))[:limit]

    def get_snapshot_at_version(self, stream_id: str, version: int) -> _facade().Snapshot | None:
        """获取指定 sequence_number 版本的快照"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            cursor = self._conn.execute(
                "\n                SELECT * FROM neuro_snapshots\n                WHERE stream_id = ? AND sequence_number = ?\n                ORDER BY created_at DESC\n                LIMIT 1\n                ",
                (stream_id, version),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_snapshot(row)
        snapshots_list = self._snapshots.get(stream_id, [])
        for snap in reversed(snapshots_list):
            if snap.sequence_number == version:
                return snap
        return None

    def get_events_after_snapshot(self, stream_id: str) -> list[_facade().StoredEvent]:
        """获取快照后的事件（用于恢复聚合根）"""
        snapshot = self.get_snapshot(stream_id)
        if not snapshot:
            return self.get_stream_events(stream_id)
        return self.get_stream_events(stream_id, from_sequence=snapshot.sequence_number + 1)

    def replay(
        self,
        start_time: _facade().datetime | None = None,
        end_time: _facade().datetime | None = None,
        event_types: list[str] | None = None,
        stream_id: str | None = None,
        callback: _facade().Callable[[_facade().NeuroEvent], None] | None = None,
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
            events = self.get_stream_events(stream_id)
        else:
            events = list(self.get_all(start_time, end_time))
        for stored in events:
            if event_types and stored.event.event_type not in event_types:
                continue
            if callback:
                try:
                    callback(stored.event)
                    count += 1
                except _facade().RECOVERABLE_ERRORS as e:
                    _facade().logger.error("[EventStore] 重播失败: %s", e)
            else:
                _facade().logger.info(
                    "[EventStore] 重播: %s (store_id=%s)", stored.event.event_type, stored.store_id
                )
                count += 1
        _facade().logger.info("[EventStore] 重播完成: %s 个事件", count)
        return count
