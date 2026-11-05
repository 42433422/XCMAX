"""Atomic journal writes, optimistic versions and retention of event streams."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from app.neuro_bus.events.events_base import NeuroEvent

from .event_codec import EventCodec
from .event_records import Snapshot, StoredEvent, WrongExpectedVersionError
from .sqlite import SQLiteOwner, StorageRuntime, fetch_rows


@dataclass
class EventState:
    events: dict[str, StoredEvent] = field(default_factory=dict)
    streams: dict[str, list[str]] = field(default_factory=dict)
    snapshots: dict[str, list[Snapshot]] = field(default_factory=dict)
    sequence: int = 0


def initialize_event_store(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS neuro_events (
            store_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            event_data TEXT NOT NULL, stream_id TEXT,
            sequence_number INTEGER NOT NULL, stored_at TEXT NOT NULL,
            metadata TEXT, is_deleted INTEGER DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS idx_events_stream ON neuro_events(stream_id, sequence_number)",
        "CREATE INDEX IF NOT EXISTS idx_events_type ON neuro_events(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_events_stored_at ON neuro_events(stored_at)",
        """CREATE TABLE IF NOT EXISTS neuro_snapshots (
            snapshot_id TEXT PRIMARY KEY, stream_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL, state TEXT NOT NULL,
            created_at TEXT NOT NULL, version INTEGER DEFAULT 1, metadata TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_snapshots_stream ON neuro_snapshots(stream_id)",
    )
    for statement in statements:
        connection.execute(statement).close()
    columns = {row["name"] for row in fetch_rows(connection, "PRAGMA table_info(neuro_snapshots)")}
    if "metadata" not in columns:
        connection.execute("ALTER TABLE neuro_snapshots ADD COLUMN metadata TEXT").close()


class EventJournal:
    def __init__(
        self,
        storage: SQLiteOwner,
        state: EventState,
        codec: EventCodec,
        runtime: StorageRuntime,
        max_events: int,
    ):
        self.storage = storage
        self.state = state
        self.codec = codec
        self.runtime = runtime
        self.max_events = max_events

    def stream_version(self, stream_id: str) -> int:
        if self.storage.connection is not None:
            rows = self.storage.rows(
                "SELECT COUNT(*) FROM neuro_events WHERE stream_id = ? AND is_deleted = 0",
                (stream_id,),
            )
            return int(rows[0][0])
        with self.storage.lock:
            return len(self.state.streams.get(stream_id, []))

    def check_version(self, stream_id: str | None, expected: int | None) -> None:
        if expected is None or expected == -2:
            return
        actual = self.stream_version(stream_id) if stream_id else 0
        if expected == -1:
            if actual != 0:
                raise WrongExpectedVersionError(stream_id or "", expected, actual)
        elif expected >= 0:
            if actual != expected:
                raise WrongExpectedVersionError(stream_id or "", expected, actual)
        else:
            raise ValueError(f"[EventStore] 不支持的 expected_version 值: {expected}")

    def _record(self, event: NeuroEvent, stream_id: str | None) -> StoredEvent:
        metadata = {}
        if self.codec.registry is not None:
            metadata["event_schema_version"] = self.codec.registry.get_current_version(
                event.event_type
            )
        return StoredEvent(
            store_id=f"evt-{self.runtime.new_id()}",
            event=event,
            stored_at=self.runtime.clock().now(),
            sequence_number=0,
            stream_id=stream_id,
            metadata=metadata,
        )

    @staticmethod
    def _insert(
        connection: sqlite3.Connection, stored: StoredEvent, event_json: str, metadata: str | None
    ) -> None:
        connection.execute(
            """INSERT INTO neuro_events
               (store_id, event_type, event_data, stream_id, sequence_number, stored_at, metadata, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                stored.store_id,
                stored.event.event_type,
                event_json,
                stored.stream_id,
                stored.sequence_number,
                stored.stored_at.isoformat(),
                metadata,
            ),
        ).close()

    @staticmethod
    def _serialize(stored: StoredEvent) -> tuple[str, str | None]:
        return (
            stored.event.to_json(),
            json.dumps(stored.metadata, ensure_ascii=False) if stored.metadata else None,
        )

    def append(
        self,
        events: list[NeuroEvent],
        stream_id: str | None,
        expected_version: int | None,
        *,
        check_capacity: bool,
    ) -> list[StoredEvent]:
        records = [self._record(event, stream_id) for event in events]
        if self.storage.connection is not None:
            # Serialization may be expensive or invoke event-specific code.
            # Check the current version only after it finishes, inside the
            # write transaction shared by all instances of this database.
            serialized = [self._serialize(stored) for stored in records]
            with self.storage.lock:
                with self.storage.transaction() as connection:
                    self.check_version(stream_id, expected_version)
                    sequence = int(
                        fetch_rows(
                            connection, "SELECT COALESCE(MAX(sequence_number), 0) FROM neuro_events"
                        )[0][0]
                    )
                    if check_capacity:
                        self._ensure_capacity(connection)
                    for stored, (event_json, metadata) in zip(records, serialized, strict=True):
                        sequence += 1
                        stored.sequence_number = sequence
                        self._insert(connection, stored, event_json, metadata)
                self.state.sequence = sequence
            return records
        with self.storage.lock:
            self.check_version(stream_id, expected_version)
            for stored in records:
                if check_capacity and len(self.state.events) >= self.max_events:
                    self._cleanup_memory(1000)
                self.state.sequence += 1
                stored.sequence_number = self.state.sequence
                self.state.events[stored.store_id] = stored
                if stream_id:
                    self.state.streams.setdefault(stream_id, []).append(stored.store_id)
        return records

    def insert_stored(self, stored: StoredEvent) -> None:
        event_json, metadata = self._serialize(stored)
        with self.storage.transaction() as connection:
            self._ensure_capacity(connection)
            self._insert(connection, stored, event_json, metadata)

    def _ensure_capacity(self, connection: sqlite3.Connection) -> None:
        count = int(
            fetch_rows(connection, "SELECT COUNT(*) FROM neuro_events WHERE is_deleted = 0")[0][0]
        )
        if count >= self.max_events:
            self._cleanup_sqlite(connection, 1000)

    def _cleanup_sqlite(self, connection: sqlite3.Connection, count: int) -> None:
        cursor = connection.execute(
            """UPDATE neuro_events SET is_deleted = 1 WHERE store_id IN (
                   SELECT store_id FROM neuro_events WHERE is_deleted = 0
                   ORDER BY sequence_number ASC LIMIT ?)""",
            (count,),
        )
        removed = cursor.rowcount
        cursor.close()
        self.runtime.log().warning("[EventStore] 清理旧事件: %s 个（逻辑删除）", removed)

    def _cleanup_memory(self, count: int) -> None:
        removed = sorted(self.state.events.values(), key=lambda entry: entry.sequence_number)[
            :count
        ]
        for stored in removed:
            del self.state.events[stored.store_id]
            if stored.stream_id and stored.stream_id in self.state.streams:
                stream = self.state.streams[stored.stream_id]
                if stored.store_id in stream:
                    stream.remove(stored.store_id)
        self.runtime.log().warning("[EventStore] 清理旧事件: %s 个", len(removed))

    def cleanup_oldest(self, count: int) -> None:
        if self.storage.connection is not None:
            with self.storage.transaction() as connection:
                self._cleanup_sqlite(connection, count)
        else:
            with self.storage.lock:
                self._cleanup_memory(count)

    def delete_stream(self, stream_id: str) -> int:
        with self.storage.lock:
            if self.storage.connection is not None:
                with self.storage.transaction() as connection:
                    cursor = connection.execute(
                        "UPDATE neuro_events SET is_deleted = 1 WHERE stream_id = ? AND is_deleted = 0",
                        (stream_id,),
                    )
                    count = cursor.rowcount
                    cursor.close()
                    connection.execute(
                        "DELETE FROM neuro_snapshots WHERE stream_id = ?", (stream_id,)
                    ).close()
            else:
                count = 0
                for store_id in self.state.streams.pop(stream_id, []):
                    if self.state.events.pop(store_id, None) is not None:
                        count += 1
                self.state.snapshots.pop(stream_id, None)
        self.runtime.log().info("[EventStore] 删除流: %s (%s 个事件)", stream_id, count)
        return count

    def clear(self) -> None:
        with self.storage.lock:
            if self.storage.connection is not None:
                with self.storage.transaction() as connection:
                    connection.execute("DELETE FROM neuro_events").close()
                    connection.execute("DELETE FROM neuro_snapshots").close()
            else:
                self.state.events.clear()
                self.state.streams.clear()
                self.state.snapshots.clear()
            self.state.sequence = 0
        self.runtime.log().info("[EventStore] 已清空")
