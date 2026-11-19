"""Durable storage for one desktop-owned, device-synced business workspace."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

_KINDS = {"customer", "product", "order"}
_RECORD_LIMIT = 64 * 1024
_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    workspace_id TEXT NOT NULL,
    cursor INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    deleted INTEGER NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS changes (
    seq INTEGER PRIMARY KEY,
    record TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    op_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS archives (
    archive_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    cursor INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    records TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS peer_binding (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    binding TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
"""


class WorkspaceChanged(ValueError):
    """The supplied workspace ID no longer refers to the active data."""


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("工作台数据必须为有效 JSON") from exc


def _identifier(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"无效的 {key}")
    return value


def _normalize_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("无效的工作台记录")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError("无效的记录类型")
    data = value.get("data")
    if not isinstance(data, dict):
        raise ValueError("记录数据必须为对象")
    deleted = value.get("deleted", False)
    if not isinstance(deleted, bool):
        raise ValueError("无效的删除状态")
    record = {
        "id": _identifier(value.get("id"), "id"),
        "kind": kind,
        "data": data,
        "deleted": deleted,
    }
    if len(_json(record).encode()) > _RECORD_LIMIT:
        raise ValueError("单条工作区记录不得超过 64 KiB")
    return record


def _normalize_snapshot(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = []
    keys: set[tuple[str, str]] = set()
    for value in values:
        record = _normalize_record(value)
        key = (record["kind"], record["id"])
        if key in keys:
            raise ValueError("快照包含重复记录")
        keys.add(key)
        records.append({**record, "version": _identifier(value.get("version"), "version")})
    return records


def _normalize_operation(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _normalize_record(value)
    base = value.get("base_version")
    return {
        **record,
        "op_id": _identifier(value.get("op_id"), "op_id"),
        "base_version": None if base is None else _identifier(base, "base_version"),
    }


class LocalWorkspace:
    def __init__(self, path: str | Path):
        self.path = Path(path).absolute()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(_SCHEMA)
            db.execute(
                "INSERT OR IGNORE INTO workspace (singleton, workspace_id) VALUES (1, ?)",
                (uuid4().hex,),
            )

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db

    @staticmethod
    def _state(db: sqlite3.Connection, expected: str | None = None) -> tuple[str, int]:
        workspace_id, cursor = db.execute(
            "SELECT workspace_id, cursor FROM workspace WHERE singleton = 1"
        ).fetchone()
        if expected is not None and workspace_id != expected:
            raise WorkspaceChanged("工作台已更换，请重新连接并同步")
        return workspace_id, cursor

    @classmethod
    def _status(cls, db: sqlite3.Connection, expected: str | None = None) -> dict[str, Any]:
        workspace_id, cursor = cls._state(db, expected)
        count = db.execute("SELECT COUNT(*) FROM records WHERE deleted = 0").fetchone()[0]
        return {"workspace_id": workspace_id, "cursor": cursor, "record_count": count}

    @staticmethod
    def _records(db: sqlite3.Connection) -> list[dict[str, Any]]:
        return [
            json.loads(row[0]) for row in db.execute("SELECT record FROM records ORDER BY kind, id")
        ]

    def status(self) -> dict[str, Any]:
        with self._transaction() as db:
            return self._status(db)

    def snapshot(self, *, workspace_id: str | None = None) -> dict[str, Any]:
        with self._transaction() as db:
            return {**self._status(db, workspace_id), "records": self._records(db)}

    def peer_binding(self) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute("SELECT binding FROM peer_binding").fetchone()
            return json.loads(row[0]) if row is not None else {}

    def pairing_snapshot(self) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute("SELECT snapshot FROM peer_binding").fetchone()
            if row is None:
                raise WorkspaceChanged("工作区已解除绑定，请重新配对")
            return json.loads(row[0])

    def bind_peer(
        self,
        binding: dict[str, Any],
        *,
        workspace_id: str,
        max_snapshot_bytes: int,
        records: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized = None if records is None else _normalize_snapshot(records)
        with self._transaction(write=True) as db:
            if db.execute("SELECT 1 FROM peer_binding").fetchone() is not None:
                raise ValueError("请先解除当前设备绑定")
            if normalized is None:
                snapshot = {
                    **self._status(db, workspace_id),
                    "records": self._records(db),
                }
            else:
                snapshot = self._replace(db, normalized, workspace_id)
            encoded = _json(snapshot)
            if len(encoded.encode()) > max_snapshot_bytes:
                raise ValueError("首次同步的数据过大，请缩小起始工作区后再配对")
            db.execute(
                "INSERT INTO peer_binding (singleton, binding, snapshot) VALUES (1, ?, ?)",
                (_json({**binding, "workspace_id": snapshot["workspace_id"]}), encoded),
            )
            return snapshot

    def unbind_peer(self) -> None:
        with self._transaction(write=True) as db:
            db.execute("DELETE FROM peer_binding")

    @staticmethod
    def _save_record(db: sqlite3.Connection, record: dict[str, Any], encoded: str) -> None:
        db.execute(
            """INSERT INTO records (kind, id, deleted, record) VALUES (?, ?, ?, ?)
               ON CONFLICT(kind, id) DO UPDATE SET deleted = excluded.deleted,
                                                  record = excluded.record""",
            (record["kind"], record["id"], record["deleted"], encoded),
        )

    def apply(
        self, operations: Iterable[Mapping[str, Any]], *, workspace_id: str | None = None
    ) -> dict[str, Any]:
        normalized = [_normalize_operation(operation) for operation in operations]
        with self._transaction(write=True) as db:
            active_id, cursor = self._state(db, workspace_id)
            results = []
            for operation in normalized:
                op_id = operation["op_id"]
                payload = _json(operation)
                receipt = db.execute(
                    "SELECT operation, result FROM receipts WHERE op_id = ?", (op_id,)
                ).fetchone()
                if receipt is not None:
                    if receipt[0] != payload:
                        raise ValueError("重复的操作编号对应了不同数据")
                    results.append(json.loads(receipt[1]))
                    continue

                saved = db.execute(
                    "SELECT record FROM records WHERE kind = ? AND id = ?",
                    (operation["kind"], operation["id"]),
                ).fetchone()
                current = json.loads(saved[0]) if saved else None
                base = current["version"] if current is not None else None
                if operation["base_version"] != base:
                    result = {"op_id": op_id, "status": "conflict", "record": current}
                else:
                    record = {key: operation[key] for key in ("id", "kind", "data", "deleted")}
                    record["version"] = op_id
                    encoded = _json(record)
                    self._save_record(db, record, encoded)
                    cursor += 1
                    db.execute("INSERT INTO changes (seq, record) VALUES (?, ?)", (cursor, encoded))
                    result = {"op_id": op_id, "status": "applied", "record": record}

                db.execute(
                    "INSERT INTO receipts (op_id, operation, result) VALUES (?, ?, ?)",
                    (op_id, payload, _json(result)),
                )
                results.append(result)

            db.execute("UPDATE workspace SET cursor = ? WHERE singleton = 1", (cursor,))
            return {"workspace_id": active_id, "cursor": cursor, "results": results}

    def pull(
        self, after: int, limit: int = 100, *, workspace_id: str | None = None
    ) -> dict[str, Any]:
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("无效的同步游标或分页大小")
        with self._transaction() as db:
            active_id, cursor = self._state(db, workspace_id)
            if after > cursor:
                raise ValueError("同步游标超过工作台当前记录")
            rows = db.execute(
                "SELECT seq, record FROM changes WHERE seq > ? ORDER BY seq LIMIT ?",
                (after, limit + 1),
            ).fetchall()
            changes = [{"seq": seq, "record": json.loads(record)} for seq, record in rows[:limit]]
            return {
                "workspace_id": active_id,
                "cursor": changes[-1]["seq"] if changes else after,
                "changes": changes,
                "has_more": len(rows) > limit,
            }

    def _replace(
        self, db: sqlite3.Connection, records: list[dict[str, Any]], expected: str | None
    ) -> dict[str, Any]:
        previous = self._status(db, expected)
        archive_id = uuid4().hex
        db.execute(
            """INSERT INTO archives (archive_id, workspace_id, cursor, created_at,
                                     record_count, records)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                archive_id,
                previous["workspace_id"],
                previous["cursor"],
                datetime.now(UTC).isoformat(),
                previous["record_count"],
                _json(self._records(db)),
            ),
        )
        db.execute("UPDATE workspace SET workspace_id = ?, cursor = 0", (uuid4().hex,))
        db.execute("DELETE FROM records")
        db.execute("DELETE FROM changes")
        db.execute("DELETE FROM receipts")
        for record in records:
            self._save_record(db, record, _json(record))
        # Imported versions cannot be recycled as operation IDs. Doing so
        # could let an edit based on an earlier revision pass as current.
        db.executemany(
            "INSERT OR IGNORE INTO receipts (op_id, operation, result) VALUES (?, 'null', 'null')",
            ((record["version"],) for record in records),
        )
        return {**self._status(db), "archive_id": archive_id, "records": records}

    def archives(self) -> list[dict[str, Any]]:
        with self._transaction() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT archive_id, workspace_id, cursor, created_at, record_count
                   FROM archives ORDER BY created_at DESC, archive_id DESC"""
            )
            return [dict(row) for row in rows]

    def restore_archive(
        self, archive_id: str, *, workspace_id: str | None = None
    ) -> dict[str, Any]:
        with self._transaction(write=True) as db:
            if db.execute("SELECT 1 FROM peer_binding").fetchone() is not None:
                raise ValueError("请先解除当前设备绑定")
            saved = db.execute(
                "SELECT records FROM archives WHERE archive_id = ?", (archive_id,)
            ).fetchone()
            if saved is None:
                raise ValueError("未找到该工作台备份")
            return self._replace(db, json.loads(saved[0]), workspace_id)
