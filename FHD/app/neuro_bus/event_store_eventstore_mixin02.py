# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.neuro_bus.event_store')

class _EventStorePart02Mixin:

    def replay_stream(self, stream_id: str, use_snapshot: bool=True, callback: _facade().Callable[[_facade().NeuroEvent], None] | None=None) -> dict[str, _facade().Any]:
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
                stored_hash = snapshot.metadata.get('state_hash')
                if stored_hash is not None:
                    actual_hash = self._compute_state_hash(snapshot.state)
                    if stored_hash != actual_hash:
                        _facade().logger.warning('[EventStore] 快照 state_hash 校验失败，丢弃快照全量重放: stream=%s snap_id=%s expected=%s actual=%s', stream_id, snapshot.snapshot_id, stored_hash[:8], actual_hash[:8])
                        snapshot = None
                        snapshot_hash_verified = False
                start_sequence = snapshot.sequence_number + 1 if snapshot else 0
        events = self.get_stream_events(stream_id, from_sequence=start_sequence)
        applied_count = 0
        for stored in events:
            if callback:
                callback(stored.event)
            applied_count += 1
        result: dict[str, _facade().Any] = {'stream_id': stream_id, 'applied_events': applied_count, 'snapshot_used': snapshot is not None, 'snapshot_hash_verified': snapshot_hash_verified}
        if snapshot:
            result['snapshot_sequence'] = snapshot.sequence_number
            result['snapshot_age_seconds'] = (_facade().datetime.now() - snapshot.created_at).total_seconds()
        _facade().logger.info('[EventStore] 流重播完成: %s (applied=%s)', stream_id, applied_count)
        return result

    def get_audit_log(self, stream_id: str | None=None, start_time: _facade().datetime | None=None, end_time: _facade().datetime | None=None) -> list[dict[str, _facade().Any]]:
        """获取审计日志"""
        if stream_id:
            events = self.get_stream_events(stream_id)
        else:
            events = list(self.get_all(start_time, end_time))
        return [{'timestamp': e.stored_at.isoformat(), 'event_type': e.event.event_type, 'event_id': e.event.metadata.event_id, 'source': e.event.metadata.source, 'correlation_id': e.event.metadata.trace_id, 'payload_keys': list(e.event.payload.keys())} for e in events]

    def get_stats(self) -> dict[str, _facade().Any]:
        """获取统计信息"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            return self._get_stats_sqlite()
        by_type: dict[str, int] = {}
        for stored in self._events.values():
            et = stored.event.event_type
            by_type[et] = by_type.get(et, 0) + 1
        by_stream = {stream_id: len(store_ids) for (stream_id, store_ids) in self._stream_events.items()}
        snapshots_count = sum((len(snaps) for snaps in self._snapshots.values()))
        return {'total_events': len(self._events), 'max_events': self._max_events, 'streams': len(self._stream_events), 'snapshots': snapshots_count, 'by_event_type': by_type, 'by_stream': by_stream, 'oldest_event': min((e.stored_at for e in self._events.values())).isoformat() if self._events else None, 'newest_event': max((e.stored_at for e in self._events.values())).isoformat() if self._events else None}

    def _get_stats_sqlite(self) -> dict[str, _facade().Any]:
        """SQLITE 模式统计信息"""
        assert self._conn is not None
        cursor = self._conn.execute('SELECT COUNT(*) AS cnt FROM neuro_events WHERE is_deleted = 0')
        total_events = cursor.fetchone()['cnt']
        cursor = self._conn.execute('\n            SELECT event_type, COUNT(*) AS cnt\n            FROM neuro_events\n            WHERE is_deleted = 0\n            GROUP BY event_type\n            ')
        by_type = {row['event_type']: row['cnt'] for row in cursor.fetchall()}
        cursor = self._conn.execute('\n            SELECT stream_id, COUNT(*) AS cnt\n            FROM neuro_events\n            WHERE is_deleted = 0 AND stream_id IS NOT NULL\n            GROUP BY stream_id\n            ')
        by_stream = {row['stream_id']: row['cnt'] for row in cursor.fetchall()}
        cursor = self._conn.execute('SELECT COUNT(DISTINCT stream_id) AS cnt FROM neuro_events WHERE is_deleted = 0 AND stream_id IS NOT NULL')
        streams_count = cursor.fetchone()['cnt']
        cursor = self._conn.execute('SELECT COUNT(*) AS cnt FROM neuro_snapshots')
        snapshots_count = cursor.fetchone()['cnt']
        cursor = self._conn.execute('SELECT stored_at FROM neuro_events WHERE is_deleted = 0 ORDER BY stored_at ASC LIMIT 1')
        oldest_row = cursor.fetchone()
        oldest_event = oldest_row['stored_at'] if oldest_row else None
        cursor = self._conn.execute('SELECT stored_at FROM neuro_events WHERE is_deleted = 0 ORDER BY stored_at DESC LIMIT 1')
        newest_row = cursor.fetchone()
        newest_event = newest_row['stored_at'] if newest_row else None
        return {'total_events': total_events, 'max_events': self._max_events, 'streams': streams_count, 'snapshots': snapshots_count, 'by_event_type': by_type, 'by_stream': by_stream, 'oldest_event': oldest_event, 'newest_event': newest_event}

    def delete_stream(self, stream_id: str) -> int:
        """删除整个事件流（SQLITE 模式为逻辑删除，保留事件溯源完整性）"""
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            with self._lock:
                with self._conn:
                    cursor = self._conn.execute('\n                        UPDATE neuro_events\n                        SET is_deleted = 1\n                        WHERE stream_id = ? AND is_deleted = 0\n                        ', (stream_id,))
                    count = cursor.rowcount
                    self._conn.execute('DELETE FROM neuro_snapshots WHERE stream_id = ?', (stream_id,))
            _facade().logger.info('[EventStore] 删除流: %s (%s 个事件，逻辑删除)', stream_id, count)
            return count
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
        _facade().logger.info('[EventStore] 删除流: %s (%s 个事件)', stream_id, count)
        return count

    def clear(self):
        """清空所有数据（SQLITE 模式为物理清空，谨慎使用）"""
        with self._lock:
            if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
                with self._conn:
                    self._conn.execute('DELETE FROM neuro_events')
                    self._conn.execute('DELETE FROM neuro_snapshots')
            else:
                self._events.clear()
                self._stream_events.clear()
                self._snapshots.clear()
            self._sequence_counter = 0
        _facade().logger.info('[EventStore] 已清空')

    def on_append(self, callback: _facade().Callable[[_facade().StoredEvent], None]):
        """注册追加回调"""
        self._append_callbacks.append(callback)

    def _cleanup_oldest(self, count: int=1000):
        """
        清理最老的事件

        SQLITE 模式：逻辑删除（is_deleted=1），保留事件溯源完整性
        MEMORY 模式：物理删除
        """
        if self._mode == _facade().EventStoreMode.SQLITE and self._conn is not None:
            with self._conn:
                cursor = self._conn.execute('\n                    UPDATE neuro_events\n                    SET is_deleted = 1\n                    WHERE store_id IN (\n                        SELECT store_id FROM neuro_events\n                        WHERE is_deleted = 0\n                        ORDER BY sequence_number ASC\n                        LIMIT ?\n                    )\n                    ', (count,))
                removed = cursor.rowcount
            _facade().logger.warning('[EventStore] 清理旧事件: %s 个（逻辑删除）', removed)
            return
        sorted_events = sorted(self._events.values(), key=lambda e: e.sequence_number)
        to_remove = sorted_events[:count]
        for stored in to_remove:
            del self._events[stored.store_id]
            if stored.stream_id and stored.stream_id in self._stream_events:
                stream_list = self._stream_events[stored.stream_id]
                if stored.store_id in stream_list:
                    stream_list.remove(stored.store_id)
        _facade().logger.warning('[EventStore] 清理旧事件: %s 个', len(to_remove))
