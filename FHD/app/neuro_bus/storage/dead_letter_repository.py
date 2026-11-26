"""Dead-letter persistence, row decoding, filtering and capacity retention."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.neuro_bus.events.events_base import NeuroEvent

from .sqlite import SQLiteOwner, StorageRuntime, fetch_rows

if TYPE_CHECKING:
    from app.neuro_bus.dead_letter_queue import DeadLetterEntry, DeadLetterReason


@dataclass
class DeadLetterState:
    entries: dict[str, DeadLetterEntry] = field(default_factory=dict)
    stats: dict[str, int] = field(
        default_factory=lambda: {
            "total_entries": 0,
            "replayed": 0,
            "expired": 0,
            "manually_resolved": 0,
        }
    )


def initialize_dead_letters(connection: sqlite3.Connection) -> None:
    for statement in (
        """CREATE TABLE IF NOT EXISTS neuro_dead_letters (
               entry_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, event_data TEXT NOT NULL,
               reason TEXT NOT NULL, error_message TEXT NOT NULL, error_stack TEXT,
               retry_count INTEGER DEFAULT 0, first_failure_time TEXT NOT NULL,
               last_failure_time TEXT NOT NULL, handler_name TEXT, metadata TEXT,
               is_resolved INTEGER DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS idx_dlq_reason ON neuro_dead_letters(reason)",
        "CREATE INDEX IF NOT EXISTS idx_dlq_event_type ON neuro_dead_letters(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_dlq_first_failure ON neuro_dead_letters(first_failure_time)",
        "CREATE INDEX IF NOT EXISTS idx_dlq_state_age ON neuro_dead_letters(is_resolved, first_failure_time)",
        """CREATE TABLE IF NOT EXISTS neuro_dlq_audit (
               audit_id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL,
               action TEXT NOT NULL, recorded_at TEXT NOT NULL, event_type TEXT,
               reason TEXT, retry_count INTEGER, details TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_dlq_audit_entry ON neuro_dlq_audit(entry_id, audit_id)",
    ):
        connection.execute(statement).close()


def record_audit(
    connection: sqlite3.Connection, entry_id: str, action: str, details: str | None = None
) -> None:
    """Write lifecycle evidence in the caller's mutation transaction."""
    connection.execute(
        """INSERT INTO neuro_dlq_audit
           (entry_id, action, recorded_at, event_type, reason, retry_count, details)
           SELECT entry_id, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                  event_type, reason, retry_count, ?
           FROM neuro_dead_letters WHERE entry_id = ?""",
        (action, details, entry_id),
    ).close()


class DeadLetterRepository:
    def __init__(
        self,
        storage: SQLiteOwner,
        state: DeadLetterState,
        runtime: StorageRuntime,
        max_size: int,
        entry_type: type[DeadLetterEntry],
        reason_type: type[DeadLetterReason],
    ):
        self.storage = storage
        self.state = state
        self.runtime = runtime
        self.max_size = max_size
        self.entry_type = entry_type
        self.reason_type = reason_type

    def from_row(self, row: sqlite3.Row) -> DeadLetterEntry:
        try:
            event = NeuroEvent.from_dict(
                json.loads(row["event_data"]), preserve_queue_identity=True
            )
        except (json.JSONDecodeError, KeyError, ValueError) as error:
            self.runtime.log().error(
                "[DeadLetterQueue] 反序列化事件失败 entry_id=%s: %s", row["entry_id"], error
            )
            event = NeuroEvent(event_type="__corrupt__", payload={})
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except json.JSONDecodeError:
            metadata = {}
        return self.entry_type(
            entry_id=row["entry_id"],
            original_event=event,
            reason=self.reason_type(row["reason"]),
            error_message=row["error_message"],
            error_stack=row["error_stack"],
            retry_count=row["retry_count"],
            first_failure_time=self.runtime.clock().fromisoformat(row["first_failure_time"]),
            last_failure_time=self.runtime.clock().fromisoformat(row["last_failure_time"]),
            handler_name=row["handler_name"],
            metadata=metadata,
        )

    def prepare(
        self,
        event: NeuroEvent,
        reason: DeadLetterReason,
        error_message: str,
        retry_count: int,
        handler_name: str | None,
        error_stack: str | None,
    ) -> DeadLetterEntry:
        now = self.runtime.clock().now()
        return self.entry_type(
            entry_id=f"dlq-{self.runtime.new_id()}",
            original_event=event,
            reason=reason,
            error_message=error_message,
            error_stack=error_stack,
            retry_count=retry_count,
            first_failure_time=now,
            last_failure_time=now,
            handler_name=handler_name,
            metadata={
                "enqueue_time": now.isoformat(),
                "original_event_id": event.metadata.event_id,
                "original_timestamp": event.metadata.timestamp,
                "original_domain": event.metadata.domain,
            },
        )

    def insert(self, entry: DeadLetterEntry) -> None:
        parameters: tuple[object, ...] = ()
        if self.storage.connection is not None:
            parameters = (
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
                json.dumps(entry.metadata, ensure_ascii=False),
            )
        with self.storage.write() as connection:
            if connection is not None:
                if (
                    int(
                        fetch_rows(
                            connection,
                            "SELECT COUNT(*) FROM neuro_dead_letters WHERE is_resolved = 0",
                        )[0][0]
                    )
                    >= self.max_size
                ):
                    self._evict(connection)
                connection.execute(
                    """INSERT INTO neuro_dead_letters
                       (entry_id, event_type, event_data, reason, error_message, error_stack,
                        retry_count, first_failure_time, last_failure_time, handler_name, metadata, is_resolved)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    parameters,
                ).close()
                record_audit(
                    connection, entry.entry_id, "enqueued", entry.original_event.metadata.event_id
                )
            else:
                if len(self.state.entries) >= self.max_size:
                    self._evict(None)
                self.state.entries[entry.entry_id] = entry

    def get(self, entry_id: str) -> DeadLetterEntry | None:
        if self.storage.connection is not None:
            rows = self.storage.rows(
                "SELECT * FROM neuro_dead_letters WHERE entry_id = ? AND is_resolved = 0",
                (entry_id,),
            )
            return self.from_row(rows[0]) if rows else None
        with self.storage.lock:
            return self.state.entries.get(entry_id)

    def remove(self, entry_id: str) -> bool:
        with self.storage.write() as connection:
            if connection is None:
                return self.state.entries.pop(entry_id, None) is not None
            if self.get(entry_id) is None:
                return False
            record_audit(connection, entry_id, "removed")
            cursor = connection.execute(
                "DELETE FROM neuro_dead_letters WHERE entry_id = ? AND is_resolved = 0",
                (entry_id,),
            )
            removed = cursor.rowcount > 0
            cursor.close()
            return removed

    def entries(
        self, reason: DeadLetterReason | None = None, event_type: str | None = None
    ) -> list[DeadLetterEntry]:
        if self.storage.connection is not None:
            sql = (
                "SELECT entry_id, event_data, reason, error_message, error_stack, retry_count, "
                "first_failure_time, last_failure_time, handler_name, metadata "
                "FROM neuro_dead_letters WHERE is_resolved = 0"
            )
            params: list[object] = []
            if reason is not None:
                sql += " AND reason = ?"
                params.append(reason.value)
            if event_type is not None:
                sql += " AND event_type = ?"
                params.append(event_type)
            # Preserve the legacy all-active-entries contract. Decode bounded
            # batches from one SQLite snapshot instead of materializing all raw rows.
            entries: list[DeadLetterEntry] = []
            with self.storage.lock:
                connection = self.storage.connection
                assert connection is not None
                with closing(connection.execute(sql, params)) as cursor:
                    for batch in iter(lambda: cursor.fetchmany(256), []):
                        entries.extend(self.from_row(row) for row in batch)
            return entries
        with self.storage.lock:
            return [
                entry
                for entry in self.state.entries.values()
                if (reason is None or entry.reason == reason)
                and (event_type is None or entry.original_event.event_type == event_type)
            ]

    def replay_candidates(self, event_type: str | None, max_age_seconds: float | None) -> list[str]:
        if self.storage.connection is not None:
            sql = (
                "SELECT entry_id, first_failure_time FROM neuro_dead_letters WHERE is_resolved = 0"
            )
            params: list[object] = []
            if event_type is not None:
                sql += " AND event_type = ?"
                params.append(event_type)
            now = self.runtime.clock().now()
            return [
                row["entry_id"]
                for row in self.storage.rows(sql, params)
                if max_age_seconds is None
                or (
                    now - self.runtime.clock().fromisoformat(row["first_failure_time"])
                ).total_seconds()
                <= max_age_seconds
            ]
        with self.storage.lock:
            return [
                entry_id
                for entry_id, entry in self.state.entries.items()
                if not (event_type and entry.original_event.event_type != event_type)
                and not (max_age_seconds and entry.age_seconds > max_age_seconds)
            ]

    def archived_entries(self, limit: int) -> list[DeadLetterEntry]:
        if limit <= 0 or limit > 1000:
            raise ValueError("archive limit must be between 1 and 1000")
        if self.storage.connection is None:
            return []
        return [
            self.from_row(row)
            for row in self.storage.rows(
                "SELECT * FROM neuro_dead_letters WHERE is_resolved = 2 "
                "ORDER BY first_failure_time, entry_id LIMIT ?",
                (limit,),
            )
        ]

    def restore_archived(self, entry_id: str, restored_by: str) -> bool:
        if not restored_by.strip():
            raise ValueError("restoration requires an operator identity")
        with self.storage.write() as connection:
            if connection is None:
                return False
            size = fetch_rows(
                connection, "SELECT COUNT(*) FROM neuro_dead_letters WHERE is_resolved = 0"
            )[0][0]
            if size >= self.max_size:
                return False
            cursor = connection.execute(
                "UPDATE neuro_dead_letters SET is_resolved = 0 WHERE entry_id = ? AND is_resolved = 2",
                (entry_id,),
            )
            restored = cursor.rowcount == 1
            cursor.close()
            if restored:
                record_audit(connection, entry_id, "restored", restored_by)
            return restored

    def audit_history(
        self, entry_id: str, *, after_audit_id: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000 or after_audit_id < 0:
            raise ValueError("audit limit must be 1..1000 and cursor must be nonnegative")
        if self.storage.connection is None:
            return []
        return [
            dict(row)
            for row in self.storage.rows(
                "SELECT audit_id, entry_id, action, recorded_at, event_type, reason, "
                "retry_count, details FROM neuro_dlq_audit "
                "WHERE entry_id = ? AND audit_id > ? ORDER BY audit_id LIMIT ?",
                (entry_id, after_audit_id, limit),
            )
        ]

    def _evict(self, connection: sqlite3.Connection | None) -> None:
        if connection is not None:
            rows = fetch_rows(
                connection,
                "SELECT entry_id FROM neuro_dead_letters WHERE is_resolved = 0 "
                "ORDER BY first_failure_time, entry_id LIMIT 1",
            )
            if not rows:
                return
            oldest_id = rows[0]["entry_id"]
            connection.execute(
                "UPDATE neuro_dead_letters SET is_resolved = 2 WHERE entry_id = ?", (oldest_id,)
            ).close()
            record_audit(connection, oldest_id, "archived_capacity")
        else:
            if not self.state.entries:
                return
            oldest_id = min(
                self.state.entries.values(), key=lambda entry: entry.first_failure_time
            ).entry_id
            del self.state.entries[oldest_id]
        self.runtime.log().warning("[DeadLetterQueue] 驱逐最老条目: %s", oldest_id)

    def evict_oldest(self) -> None:
        with self.storage.write() as connection:
            self._evict(connection)
