"""Journal row decoding and copy-on-read schema upgrades."""

from __future__ import annotations

import json
import sqlite3

from app.neuro_bus.events.events_base import NeuroEvent

from .event_records import StoredEvent, UpcasterRegistry
from .sqlite import StorageRuntime


class EventCodec:
    def __init__(self, registry: UpcasterRegistry | None, runtime: StorageRuntime):
        self.registry = registry
        self.runtime = runtime

    def from_row(self, row: sqlite3.Row) -> StoredEvent:
        stored = StoredEvent(
            store_id=row["store_id"],
            event=NeuroEvent.from_dict(json.loads(row["event_data"]), preserve_queue_identity=True),
            stored_at=self.runtime.clock().fromisoformat(row["stored_at"]),
            sequence_number=row["sequence_number"],
            stream_id=row["stream_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
        return self.upcast(stored)

    def upcast(self, stored: StoredEvent) -> StoredEvent:
        if self.registry is None:
            return stored
        version = stored.metadata.get("event_schema_version", 1)
        payload, upgraded = self.registry.upcast(
            stored.event.event_type, stored.event.payload, version
        )
        if upgraded == version:
            return stored
        event = NeuroEvent(
            event_type=stored.event.event_type,
            payload=payload,
            priority=stored.event.priority,
            metadata=stored.event.metadata,
            preserve_queue_identity=True,
        )
        return StoredEvent(
            store_id=stored.store_id,
            event=event,
            stored_at=stored.stored_at,
            sequence_number=stored.sequence_number,
            stream_id=stored.stream_id,
            metadata={**stored.metadata, "event_schema_version": upgraded},
        )
