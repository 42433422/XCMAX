"""Durable global DLQ and non-destructive retention contracts."""

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.neuro_bus import dead_letter_queue as module
from app.neuro_bus.dead_letter_queue import (
    DeadLetterQueue,
    DeadLetterReason,
    NeuroBusDLQIntegration,
)
from app.neuro_bus.events.events_base import NeuroEvent


def _enqueue(queue: DeadLetterQueue) -> str:
    return queue.enqueue(
        NeuroEvent(event_type="test.durable", payload={"value": 7}),
        DeadLetterReason.TIMEOUT,
        "handler failed",
        1,
    )


@pytest.fixture
def isolated_global(tmp_path, monkeypatch):
    path = tmp_path / "neurobus.sqlite3"
    monkeypatch.setenv("XCAGI_NEURO_BUS_DLQ_PATH", str(path))
    monkeypatch.setattr(module, "_dlq_instance", None)
    yield path
    if module._dlq_instance is not None:
        module._dlq_instance.close()


def test_global_singleton_durable_and_shared(isolated_global, monkeypatch):
    with ThreadPoolExecutor(max_workers=8) as executor:
        queues = list(executor.map(lambda _: module.get_dead_letter_queue(), range(16)))
    queue = queues[0]
    assert all(item is queue for item in queues)
    assert NeuroBusDLQIntegration().dlq is queue
    assert isolated_global.is_file()
    entry_id = _enqueue(queue)
    original = queue.dequeue(entry_id).original_event.metadata.event_id
    queue.close()
    with pytest.raises(sqlite3.ProgrammingError):
        queue.dequeue(entry_id)
    other = isolated_global.with_name("other.sqlite3")
    monkeypatch.setenv("XCAGI_NEURO_BUS_DLQ_PATH", str(other))
    with pytest.raises(ValueError, match="different storage"):
        module.get_dead_letter_queue(str(other))
    with ThreadPoolExecutor(max_workers=8) as executor:
        reopened_queues = list(executor.map(lambda _: module.get_dead_letter_queue(), range(16)))
    reopened = reopened_queues[0]
    assert reopened is not queue
    assert all(item is reopened for item in reopened_queues)
    assert not other.exists()
    assert reopened.dequeue(entry_id).original_event.metadata.event_id == original
    assert reopened.get_audit_history(entry_id)[0]["action"] == "enqueued"
    with pytest.raises(ValueError, match="different storage"):
        module.get_dead_letter_queue(str(isolated_global.with_name("other.sqlite3")))


def test_default_data_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("XCAGI_NEURO_BUS_DLQ_PATH", raising=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    assert Path(module._default_dlq_path()) == tmp_path / "data" / "neurobus_dlq.sqlite3"


def test_global_storage_error_never_falls_back(isolated_global, monkeypatch):
    isolated_global.mkdir()
    with pytest.raises(sqlite3.OperationalError):
        module.get_dead_letter_queue()
    assert module._dlq_instance is None
    monkeypatch.setenv("XCAGI_NEURO_BUS_DLQ_PATH", ":memory:")
    with pytest.raises(ValueError, match="persistent storage"):
        module.get_dead_letter_queue()


def test_committed_dead_letter_survives_process_exit(isolated_global):
    # Keep the first instance open while an independent interpreter accesses
    # the same durable database. This is local process evidence, not multi-pod.
    queue = module.get_dead_letter_queue()
    parent_entry_id = _enqueue(queue)
    script = """
import os
import sys
from app.neuro_bus.dead_letter_queue import get_dead_letter_queue, DeadLetterReason
from app.neuro_bus.events.events_base import NeuroEvent
queue = get_dead_letter_queue()
assert queue.dequeue(sys.argv[1]).original_event.payload == {"value": 7}
entry = queue.enqueue(NeuroEvent(event_type="test.durable", payload={"value": 8}),
                      DeadLetterReason.TIMEOUT, "failure", 1)
print(entry, flush=True)
os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, parent_entry_id],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    entry_id = result.stdout.strip().splitlines()[-1]
    assert entry_id != parent_entry_id
    assert queue.dequeue(parent_entry_id).original_event.payload == {"value": 7}
    assert queue.dequeue(entry_id).original_event.payload == {"value": 8}
    assert queue.get_audit_history(entry_id)[0]["action"] == "enqueued"
    queue.close()
    reopened = module.get_dead_letter_queue()
    assert reopened.dequeue(parent_entry_id).original_event.payload == {"value": 7}
    assert reopened.dequeue(entry_id).original_event.payload == {"value": 8}


def test_archive_restore_and_audit_survive_restart(tmp_path):
    path = str(tmp_path / "archive.sqlite3")
    queue = DeadLetterQueue(storage_path=path, max_size=1)
    first = _enqueue(queue)
    original = queue.dequeue(first).original_event.metadata.event_id
    second = _enqueue(queue)
    assert queue.dequeue(first) is None
    assert queue.get_stats()["archived_size"] == 1
    assert not queue.restore_archived(first, "operator")
    assert queue.resolve_manually(second, "verified", "operator")
    queue.close()

    reopened = DeadLetterQueue(storage_path=path, max_size=1)
    try:
        assert reopened.get_archived_entries()[0].entry_id == first
        assert reopened.restore_archived(first, "operator")
        assert not reopened.restore_archived(first, "operator")
        assert reopened.dequeue(first).original_event.metadata.event_id == original
        assert reopened.schedule_retry(first) is not None
        assert [row["action"] for row in reopened.get_audit_history(first)] == [
            "enqueued",
            "archived_capacity",
            "restored",
            "retry_scheduled",
        ]
        resolution = reopened.get_audit_history(second)[-1]
        assert resolution["action"] == "manually_resolved"
        assert json.loads(resolution["details"]) == {
            "resolution": "verified",
            "resolved_by": "operator",
        }
    finally:
        reopened.close()


def test_expiry_archives_and_failed_audit_rolls_back(tmp_path):
    queue = DeadLetterQueue(storage_path=str(tmp_path / "expiry.sqlite3"), retention_hours=1)
    try:
        entry_id = _enqueue(queue)
        queue._conn.execute(
            "UPDATE neuro_dead_letters SET first_failure_time = '2000-01-01T00:00:00' "
            "WHERE entry_id = ?",
            (entry_id,),
        ).close()
        queue._conn.execute(
            """CREATE TRIGGER deny_archive BEFORE INSERT ON neuro_dlq_audit
               WHEN NEW.action = 'archived_expired'
               BEGIN SELECT RAISE(ABORT, 'audit failed'); END"""
        ).close()
        with pytest.raises(sqlite3.IntegrityError, match="audit failed"):
            queue.cleanup_expired()
        assert queue.dequeue(entry_id) is not None
        queue._conn.execute("DROP TRIGGER deny_archive").close()
        assert queue.cleanup_expired() == 1
        assert queue.get_archived_entries()[0].entry_id == entry_id
        assert queue.get_audit_history(entry_id)[-1]["action"] == "archived_expired"
    finally:
        queue.close()


def test_replay_fingerprint_cleanup_preserves_audit(tmp_path):
    queue = DeadLetterQueue(storage_path=str(tmp_path / "replay.sqlite3"))
    try:
        entry_id = _enqueue(queue)
        queue.on_replay(lambda event: None)
        assert queue.replay(entry_id) == (True, "")
        queue._conn.execute("DELETE FROM neuro_dlq_replay_log").close()
        assert queue.get_audit_history(entry_id)[-1]["action"] == "replay_recorded"
    finally:
        queue.close()
