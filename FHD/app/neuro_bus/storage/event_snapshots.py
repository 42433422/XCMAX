"""Snapshot retention and state integrity, sharing the journal's transaction owner."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any

from .event_records import Snapshot
from .sqlite import SQLiteOwner, StorageRuntime


def state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class EventSnapshots:
    def __init__(
        self,
        storage: SQLiteOwner,
        snapshots: dict[str, list[Snapshot]],
        runtime: StorageRuntime,
        max_snapshots: int,
        compute_hash: Callable[[dict[str, Any]], str],
    ):
        self.storage = storage
        self.snapshots = snapshots
        self.runtime = runtime
        self.max_snapshots = max_snapshots
        self.compute_hash = compute_hash

    def save(self, stream_id: str, state: dict[str, Any], sequence_number: int) -> str:
        snapshot = Snapshot(
            snapshot_id=f"snap-{self.runtime.new_id()}",
            stream_id=stream_id,
            sequence_number=sequence_number,
            state=state,
            created_at=self.runtime.clock().now(),
            metadata={"state_hash": self.compute_hash(state)},
        )
        if self.storage.connection is not None:
            state_json = json.dumps(snapshot.state, ensure_ascii=False)
            metadata_json = json.dumps(snapshot.metadata, ensure_ascii=False)
            with self.storage.transaction() as connection:
                connection.execute(
                    """INSERT INTO neuro_snapshots
                       (snapshot_id, stream_id, sequence_number, state, created_at, version, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot.snapshot_id,
                        stream_id,
                        sequence_number,
                        state_json,
                        snapshot.created_at.isoformat(),
                        snapshot.version,
                        metadata_json,
                    ),
                ).close()
                connection.execute(
                    """DELETE FROM neuro_snapshots WHERE snapshot_id IN (
                           SELECT snapshot_id FROM (
                               SELECT snapshot_id, ROW_NUMBER() OVER (ORDER BY created_at DESC) AS rn
                               FROM neuro_snapshots WHERE stream_id = ?
                           ) WHERE rn > ?)""",
                    (stream_id, self.max_snapshots),
                ).close()
        else:
            with self.storage.lock:
                current = self.snapshots.setdefault(stream_id, [])
                current.append(snapshot)
                if len(current) > self.max_snapshots:
                    self.snapshots[stream_id] = current[-self.max_snapshots :]
        self.runtime.log().debug(
            "[EventStore] 快照保存: %s (seq=%s, snap_id=%s, hash=%s)",
            stream_id,
            sequence_number,
            snapshot.snapshot_id,
            snapshot.metadata["state_hash"][:8],
        )
        return snapshot.snapshot_id

    def from_row(self, row: sqlite3.Row) -> Snapshot:
        return Snapshot(
            snapshot_id=row["snapshot_id"],
            stream_id=row["stream_id"],
            sequence_number=row["sequence_number"],
            state=json.loads(row["state"]),
            created_at=self.runtime.clock().fromisoformat(row["created_at"]),
            version=row["version"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def history(self, stream_id: str, limit: int) -> list[Snapshot]:
        if self.storage.connection is not None:
            return [
                self.from_row(row)
                for row in self.storage.rows(
                    "SELECT * FROM neuro_snapshots WHERE stream_id = ? ORDER BY created_at DESC LIMIT ?",
                    (stream_id, limit),
                )
            ]
        with self.storage.lock:
            return list(reversed(self.snapshots.get(stream_id, [])))[:limit]

    def latest(self, stream_id: str) -> Snapshot | None:
        snapshots = self.history(stream_id, 1)
        return snapshots[0] if snapshots else None

    def at_version(self, stream_id: str, version: int) -> Snapshot | None:
        if self.storage.connection is not None:
            rows = self.storage.rows(
                "SELECT * FROM neuro_snapshots WHERE stream_id = ? AND sequence_number = ? ORDER BY created_at DESC LIMIT 1",
                (stream_id, version),
            )
            return self.from_row(rows[0]) if rows else None
        with self.storage.lock:
            return next(
                (
                    snapshot
                    for snapshot in reversed(self.snapshots.get(stream_id, []))
                    if snapshot.sequence_number == version
                ),
                None,
            )
