"""The sync service delegates persistence without changing sidecar semantics."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.db import xcmax_sync
from app.services import xcmax_sync_service as service


@pytest.fixture()
def db_path(monkeypatch, tmp_path):
    path = tmp_path / "sync.db"
    monkeypatch.setattr(xcmax_sync, "_db_path", path)
    return path


def test_meta_helpers_delegate_to_existing_dao(db_path):
    with (
        patch.object(xcmax_sync.SyncDb, "read_meta", return_value={"synthetic": True}) as read,
        patch.object(xcmax_sync.SyncDb, "write_meta") as write,
    ):
        assert service._read_sync_meta("key") == {"synthetic": True}
        service._write_sync_meta("key", {"value": 1})
    read.assert_called_once_with("key")
    write.assert_called_once_with("key", {"value": 1})


def test_meta_serialization_and_commit_survive_reopen(db_path):
    xcmax_sync.SyncDb.write_meta("key", {"name": "合成样例", "at": datetime(2026, 10, 22)})
    assert xcmax_sync.SyncDb.read_meta("key") == {"name": "合成样例", "at": "2026-10-22 00:00:00"}
    assert xcmax_sync.SyncDb.read_meta("absent") == {}


@pytest.mark.parametrize("operation", ["read", "write"])
def test_meta_does_not_rebuild_a_corrupt_existing_database(db_path, operation):
    original = b"synthetic invalid sqlite file"
    db_path.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError):
        if operation == "read":
            service._read_sync_meta("key")
        else:
            service._write_sync_meta("key", {"value": 1})
    assert db_path.read_bytes() == original
    assert list(db_path.parent.glob("*.incompatible-*")) == []


@pytest.mark.parametrize("operation", ["read", "write"])
def test_meta_connection_closes_when_schema_access_fails(db_path, operation):
    conn = MagicMock()
    with (
        patch.object(xcmax_sync.sqlite3, "connect", return_value=conn),
        patch.object(
            xcmax_sync, "_ensure_schema", side_effect=sqlite3.OperationalError("synthetic error")
        ),
        pytest.raises(sqlite3.OperationalError),
    ):
        if operation == "read":
            xcmax_sync.SyncDb.read_meta("key")
        else:
            xcmax_sync.SyncDb.write_meta("key", {})
    conn.close.assert_called_once_with()


def test_pending_inbox_keeps_limit_status_and_row_contract(db_path):
    db = xcmax_sync.SyncDb()
    db.enqueue_inbox(
        [{"entity_type": "synthetic", "entity_id": str(n), "payload": {"n": n}} for n in range(3)]
    )
    db.mark_inbox_applied(1)
    rows = db.get_pending_inbox(limit=1)
    assert len(rows) == 1
    assert rows[0]["id"] == 2
    assert set(rows[0]) == {"id", "entity_type", "entity_id", "operation", "payload_json"}
    assert db.get_pending_inbox(limit=0) == []
    assert len(db.get_pending_inbox()) == 2


def test_apply_inbox_delegates_pending_read(db_path):
    db = MagicMock()
    db.get_pending_inbox.return_value = []
    with patch.object(xcmax_sync, "SyncDb", return_value=db):
        assert service.apply_inbox(limit=7) == {"applied": 0, "conflicts": 0, "errors": 0}
    db.get_pending_inbox.assert_called_once_with(limit=7)
