"""Materialized journal reads and storage statistics, independent of replay."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .event_codec import EventCodec
from .event_journal import EventState
from .event_records import StoredEvent
from .sqlite import SQLiteOwner


class EventQueries:
    def __init__(self, storage: SQLiteOwner, state: EventState, codec: EventCodec, max_events: int):
        self.storage = storage
        self.state = state
        self.codec = codec
        self.max_events = max_events

    def get(self, store_id: str) -> StoredEvent | None:
        if self.storage.connection is not None:
            rows = self.storage.rows(
                "SELECT * FROM neuro_events WHERE store_id = ? AND is_deleted = 0", (store_id,)
            )
            return self.codec.from_row(rows[0]) if rows else None
        with self.storage.lock:
            stored = self.state.events.get(store_id)
        return self.codec.upcast(stored) if stored is not None else None

    def all(
        self, start_time: datetime | None, end_time: datetime | None, event_type: str | None
    ) -> list[StoredEvent]:
        if self.storage.connection is not None:
            sql = "SELECT * FROM neuro_events WHERE is_deleted = 0"
            params: list[object] = []
            for value, clause in (
                (start_time, " AND stored_at >= ?"),
                (end_time, " AND stored_at <= ?"),
            ):
                if value is not None:
                    sql += clause
                    params.append(value.isoformat())
            if event_type is not None:
                sql += " AND event_type = ?"
                params.append(event_type)
            return [
                self.codec.from_row(row)
                for row in self.storage.rows(sql + " ORDER BY sequence_number ASC", params)
            ]
        with self.storage.lock:
            records = sorted(self.state.events.values(), key=lambda stored: stored.sequence_number)
        return [
            self.codec.upcast(stored)
            for stored in records
            if not (start_time and stored.stored_at < start_time)
            and not (end_time and stored.stored_at > end_time)
            and not (event_type and stored.event.event_type != event_type)
        ]

    def stream(self, stream_id: str, from_sequence: int = 0) -> list[StoredEvent]:
        if self.storage.connection is not None:
            rows = self.storage.rows(
                "SELECT * FROM neuro_events WHERE stream_id = ? AND sequence_number >= ? AND is_deleted = 0 ORDER BY sequence_number ASC",
                (stream_id, from_sequence),
            )
            return [self.codec.from_row(row) for row in rows]
        with self.storage.lock:
            records = [
                self.state.events[store_id]
                for store_id in self.state.streams.get(stream_id, [])
                if store_id in self.state.events
                and self.state.events[store_id].sequence_number >= from_sequence
            ]
        return [
            self.codec.upcast(stored)
            for stored in sorted(records, key=lambda entry: entry.sequence_number)
        ]

    def latest(self, limit: int) -> list[StoredEvent]:
        if self.storage.connection is not None:
            return [
                self.codec.from_row(row)
                for row in self.storage.rows(
                    "SELECT * FROM neuro_events WHERE is_deleted = 0 ORDER BY sequence_number DESC LIMIT ?",
                    (limit,),
                )
            ]
        with self.storage.lock:
            records = sorted(
                self.state.events.values(), key=lambda entry: entry.sequence_number, reverse=True
            )[:limit]
        return [self.codec.upcast(stored) for stored in records]

    def stats(self) -> dict[str, Any]:
        with self.storage.lock:
            if self.storage.connection is not None:
                return self.sqlite_stats()
            by_type: dict[str, int] = {}
            for stored in self.state.events.values():
                kind = stored.event.event_type
                by_type[kind] = by_type.get(kind, 0) + 1
            return {
                "total_events": len(self.state.events),
                "max_events": self.max_events,
                "streams": len(self.state.streams),
                "snapshots": sum(len(snapshots) for snapshots in self.state.snapshots.values()),
                "by_event_type": by_type,
                "by_stream": {key: len(ids) for key, ids in self.state.streams.items()},
                "oldest_event": min(
                    stored.stored_at for stored in self.state.events.values()
                ).isoformat()
                if self.state.events
                else None,
                "newest_event": max(
                    stored.stored_at for stored in self.state.events.values()
                ).isoformat()
                if self.state.events
                else None,
            }

    def sqlite_stats(self) -> dict[str, Any]:
        with self.storage.lock:
            aggregate = self.storage.rows(
                "SELECT COUNT(*), COUNT(DISTINCT stream_id), MIN(stored_at), MAX(stored_at) FROM neuro_events WHERE is_deleted = 0"
            )[0]
            by_type = {
                row["event_type"]: row["cnt"]
                for row in self.storage.rows(
                    "SELECT event_type, COUNT(*) AS cnt FROM neuro_events WHERE is_deleted = 0 GROUP BY event_type"
                )
            }
            by_stream = {
                row["stream_id"]: row["cnt"]
                for row in self.storage.rows(
                    "SELECT stream_id, COUNT(*) AS cnt FROM neuro_events WHERE is_deleted = 0 AND stream_id IS NOT NULL GROUP BY stream_id"
                )
            }
            snapshots = self.storage.rows("SELECT COUNT(*) FROM neuro_snapshots")[0][0]
        return {
            "total_events": aggregate[0],
            "max_events": self.max_events,
            "streams": aggregate[1],
            "snapshots": snapshots,
            "by_event_type": by_type,
            "by_stream": by_stream,
            "oldest_event": aggregate[2],
            "newest_event": aggregate[3],
        }
