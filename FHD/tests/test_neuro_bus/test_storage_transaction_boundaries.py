"""Persistence and live replay boundaries exercised against real SQLite files."""

import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import suppress
from datetime import datetime, timedelta

import pytest

from app.neuro_bus.dead_letter_queue import DeadLetterQueue, DeadLetterReason
from app.neuro_bus.event_store import EventStore, EventStoreMode, WrongExpectedVersionError
from app.neuro_bus.events.events_base import NeuroEvent


def event(kind="sample"):
    return NeuroEvent(event_type=kind, payload={"value": 1})


@pytest.fixture
def owned_stores(tmp_path):
    instances = []

    def create(kind, name="events.sqlite3", **kwargs):
        if kind == "events":
            instance = EventStore(
                mode=EventStoreMode.SQLITE, storage_path=str(tmp_path / name), **kwargs
            )
        else:
            instance = DeadLetterQueue(storage_path=str(tmp_path / name), **kwargs)
        instances.append(instance)
        return instance

    yield create
    for instance in instances:
        if instance._conn is not None:
            with suppress(sqlite3.ProgrammingError):
                instance._conn.close()


@pytest.mark.parametrize("failure", ["sql", "serialization"])
def test_failed_event_batch_rolls_back_rows_sequence_and_callbacks(owned_stores, failure):
    store = owned_stores("events")
    callbacks = []
    store.on_append(callbacks.append)
    rejected = event("rejected")
    if failure == "sql":
        store._conn.execute(
            "CREATE TRIGGER reject_event BEFORE INSERT ON neuro_events "
            "WHEN NEW.event_type = 'rejected' BEGIN SELECT RAISE(ABORT, 'rejected'); END"
        )
    else:
        rejected.payload["unserializable"] = object()
    with pytest.raises((sqlite3.IntegrityError, TypeError)):
        store.append_many([event(), rejected], stream_id="orders", expected_version=0)
    assert store.get_stream_events("orders") == []
    assert callbacks == []
    assert store._sequence_counter == 0
    assert store._conn.in_transaction is False
    accepted = store.append(event(), stream_id="orders", expected_version=0)
    assert store.get(accepted).sequence_number == 1


def test_event_capacity_eviction_is_rolled_back_when_insert_fails(owned_stores):
    store = owned_stores("events", max_events=1)
    original = store.append(event(), stream_id="orders")
    store._conn.execute(
        "CREATE TRIGGER reject_event BEFORE INSERT ON neuro_events "
        "WHEN NEW.event_type = 'rejected' BEGIN SELECT RAISE(ABORT, 'rejected'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.append(event("rejected"), stream_id="orders")
    assert store.get(original) is not None
    assert store.get_stats()["total_events"] == 1
    assert store._sequence_counter == 1
    assert store._conn.in_transaction is False


def test_open_event_stores_share_one_persisted_sequence(owned_stores):
    first = owned_stores("events")
    second = owned_stores("events")
    first.append(event(), stream_id="first")
    second.append(event(), stream_id="second")
    first.append(event(), stream_id="first")
    assert [item.sequence_number for item in second.get_all()] == [1, 2, 3]


def test_event_expected_version_is_checked_after_serialization(owned_stores, monkeypatch):
    first = owned_stores("events")
    second = owned_stores("events")
    candidate = event()
    serialize = candidate.to_json
    serializing = threading.Event()
    resume = threading.Event()

    def prepare():
        serializing.set()
        assert resume.wait(5)
        return serialize()

    monkeypatch.setattr(candidate, "to_json", prepare)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(first.append, candidate, "orders", 0)
        try:
            assert serializing.wait(5)
            committed = executor.submit(second.append, event(), "orders", 0)
            committed_id = committed.result(timeout=5)
        finally:
            resume.set()
        with pytest.raises(WrongExpectedVersionError):
            pending.result(timeout=5)
    assert [item.store_id for item in first.get_stream_events("orders")] == [committed_id]


@pytest.mark.parametrize("kind", ["events", "dlq"])
def test_failed_schema_initialization_closes_the_owned_connection(tmp_path, monkeypatch, kind):
    original_connect = sqlite3.connect
    opened = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        opened.append(connection)
        connection.set_authorizer(
            lambda action, *_args: (
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE else sqlite3.SQLITE_OK
            )
        )
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(sqlite3.DatabaseError):
        if kind == "events":
            EventStore(mode=EventStoreMode.SQLITE, storage_path=str(tmp_path / "events.sqlite3"))
        else:
            DeadLetterQueue(storage_path=str(tmp_path / "dlq.sqlite3"))
    assert len(opened) == 1
    try:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1")
    finally:
        opened[0].close()


def test_dead_letter_capacity_eviction_rolls_back_on_insert_failure(owned_stores):
    queue = owned_stores("dlq", max_size=1)
    original = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    queue._conn.execute(
        "CREATE TRIGGER reject_entry BEFORE INSERT ON neuro_dead_letters "
        "WHEN NEW.event_type = 'rejected' BEGIN SELECT RAISE(ABORT, 'rejected'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        queue.enqueue(event("rejected"), DeadLetterReason.TIMEOUT, "timeout", 0)
    assert queue.dequeue(original) is not None
    assert queue.get_stats()["current_size"] == 1
    assert queue.get_stats()["total_entries"] == 1
    assert queue._conn.in_transaction is False


@pytest.mark.parametrize("event_type", [None, "selected"])
def test_sqlite_replay_age_filter_preserves_the_stored_entries(owned_stores, event_type):
    queue = owned_stores("dlq")
    old = queue.enqueue(event("selected"), DeadLetterReason.TIMEOUT, "old", 0)
    young = queue.enqueue(event("selected"), DeadLetterReason.TIMEOUT, "young", 0)
    other = queue.enqueue(event("other"), DeadLetterReason.TIMEOUT, "other", 0)
    queue._conn.execute(
        "UPDATE neuro_dead_letters SET first_failure_time = ? WHERE entry_id = ?",
        ((datetime.now() - timedelta(hours=1)).isoformat(), old),
    )
    selected = queue._get_replay_candidates(event_type=event_type, max_age_seconds=60)
    assert set(selected) == ({young} if event_type else {young, other})
    assert {item.entry_id for item in queue.get_all_entries()} == {old, young, other}


@pytest.mark.parametrize("mode", ["memory", "sqlite", "shared_sqlite"])
def test_live_replays_deliver_one_callback_per_fingerprint(owned_stores, mode):
    first = DeadLetterQueue() if mode == "memory" else owned_stores("dlq")
    second = owned_stores("dlq") if mode == "shared_sqlite" else first
    entry_id = first.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    started = threading.Event()
    resume = threading.Event()
    calls = []
    calls_lock = threading.Lock()

    def consume(delivered):
        with calls_lock:
            calls.append(delivered.metadata.event_id)
            is_first = len(calls) == 1
        if is_first:
            started.set()
            assert resume.wait(5)

    first.on_replay(consume)
    if second is not first:
        second.on_replay(consume)
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(first.replay, entry_id)
        assert started.wait(5)
        two = executor.submit(second.replay, entry_id)
        try:
            two.result(timeout=0.5)
        except FutureTimeout:
            pass
        finally:
            resume.set()
        outcomes = [one.result(timeout=5)[0], two.result(timeout=5)[0]]
    assert sorted(outcomes) == [False, True]
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["memory", "shared_sqlite", "aliased_sqlite"])
def test_recursive_replay_across_queue_instances_is_in_progress(owned_stores, tmp_path, mode):
    first = DeadLetterQueue() if mode == "memory" else owned_stores("dlq")
    if mode == "aliased_sqlite":
        (tmp_path / "nested").mkdir()
        second = owned_stores("dlq", name="nested/../events.sqlite3")
    else:
        second = owned_stores("dlq") if mode == "shared_sqlite" else first
    entry_id = first.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    calls = []
    nested = []

    def consume(delivered):
        calls.append(delivered.metadata.event_id)
        if len(calls) == 1:
            nested.append(second.replay(entry_id))

    first.on_replay(consume)
    if second is not first:
        second.on_replay(consume)
    assert first.replay(entry_id) == (True, "")
    assert nested == [(False, "replay_in_progress")]
    assert len(calls) == 1
    assert first.dequeue(entry_id).retry_count == 0
    assert second.replay(entry_id) == (False, "already_replayed")


@pytest.mark.parametrize("mode", ["memory", "sqlite"])
def test_callback_allows_concurrent_enqueue_and_read(owned_stores, mode):
    queue = DeadLetterQueue() if mode == "memory" else owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    observed = []

    def concurrent_storage():
        added = queue.enqueue(event("during_replay"), DeadLetterReason.TIMEOUT, "timeout", 0)
        return added, {entry.entry_id for entry in queue.get_all_entries()}

    with ThreadPoolExecutor(max_workers=1) as executor:

        def consume(_event):
            if queue._conn is not None:
                assert queue._conn.in_transaction is False
            observed.append(executor.submit(concurrent_storage).result(timeout=5))

        queue.on_replay(consume)
        assert queue.replay(entry_id) == (True, "")
    assert len(observed) == 1
    added, entries = observed[0]
    assert entries == {entry_id, added}
    assert queue.get_stats()["total_entries"] == 2


def test_concurrent_retry_updates_use_current_persisted_count(owned_stores, monkeypatch):
    from app.neuro_bus import dead_letter_queue as module

    first = owned_stores("dlq")
    second = owned_stores("dlq")
    entry_id = first.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    barrier = threading.Barrier(2)

    def random_value():
        barrier.wait(timeout=5)
        return 1.0

    monkeypatch.setattr(module.random, "random", random_value)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(queue.schedule_retry, entry_id) for queue in (first, second)]
        delays = [future.result(timeout=5) for future in futures]
    assert first.dequeue(entry_id).retry_count == 2
    assert sorted(delays) == [0.5, 1.0]
    assert first._conn.in_transaction is False
    assert second._conn.in_transaction is False


def test_failed_manual_resolution_preserves_entry_and_statistics(owned_stores):
    queue = owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    original_metadata = queue.dequeue(entry_id).metadata
    queue._conn.execute(
        "CREATE TRIGGER reject_resolution BEFORE DELETE ON neuro_dead_letters "
        "BEGIN SELECT RAISE(ABORT, 'rejected'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        queue.resolve_manually(entry_id, "verified", "operator")
    assert queue.dequeue(entry_id).metadata == original_metadata
    assert (
        queue._conn.execute(
            "SELECT is_resolved FROM neuro_dead_letters WHERE entry_id = ?", (entry_id,)
        ).fetchone()[0]
        == 0
    )
    assert queue.get_stats()["manually_resolved"] == 0
    assert queue._conn.in_transaction is False


@pytest.mark.parametrize("mode", ["memory", "sqlite"])
def test_replay_marks_the_attempt_that_ran_when_callback_schedules_retry(owned_stores, mode):
    queue = DeadLetterQueue() if mode == "memory" else owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    calls = []

    def consume(delivered):
        calls.append(delivered.metadata.event_id)
        if len(calls) == 1:
            assert queue.schedule_retry(entry_id) is not None

    queue.on_replay(consume)
    assert queue.replay(entry_id) == (True, "")
    assert queue.dequeue(entry_id).retry_count == 1
    assert queue.replay(entry_id) == (True, "")
    assert len(calls) == 2
    assert queue.replay(entry_id) == (False, "already_replayed")


def test_process_competitor_cannot_deliver_a_live_replay(owned_stores, tmp_path):
    queue = owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    started = threading.Event()
    resume = threading.Event()
    calls = []

    def consume(delivered):
        calls.append(delivered.metadata.event_id)
        started.set()
        assert resume.wait(20)

    queue.on_replay(consume)
    child = """
import json, sys
from app.neuro_bus.dead_letter_queue import DeadLetterQueue
queue = DeadLetterQueue(storage_path=sys.argv[1])
delivered = []
queue.on_replay(lambda event: delivered.append(event.metadata.event_id))
result = queue.replay(sys.argv[2])
queue._conn.close()
print(json.dumps({'result': result, 'delivered': delivered}))
"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(queue.replay, entry_id)
        try:
            assert started.wait(5)
            competitor = subprocess.run(
                [sys.executable, "-c", child, str(tmp_path / "events.sqlite3"), entry_id],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            result = json.loads(competitor.stdout)
        finally:
            resume.set()
        assert pending.result(timeout=5) == (True, "")
    assert result == {"result": [False, "replay_in_progress"], "delivered": []}
    assert len(calls) == 1
    assert queue.dequeue(entry_id).retry_count == 0


def test_event_batch_callbacks_observe_the_whole_committed_batch(owned_stores):
    store = owned_stores("events")
    observer = owned_stores("events")
    observed = []
    store.on_append(
        lambda _stored: observed.append(
            (len(observer.get_stream_events("orders")), store._conn.in_transaction)
        )
    )
    store.append_many([event(), event()], stream_id="orders")
    assert observed == [(2, False), (2, False)]


def test_suspended_event_iteration_releases_its_sqlite_cursor(owned_stores):
    store = owned_stores("events")
    ids = store.append_many([event(), event(), event()])
    stream = store.get_all()
    assert next(stream).store_id == ids[0]
    try:
        checkpoint = store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert checkpoint[0] == 0
        assert [stored.store_id for stored in stream] == ids[1:]
    finally:
        stream.close()


def test_snapshot_pruning_failure_rolls_back_the_new_snapshot(owned_stores):
    store = owned_stores("events", max_snapshots_per_stream=1)
    original = store.save_snapshot("orders", {"value": 1}, 1)
    store._conn.execute(
        "CREATE TRIGGER reject_pruning BEFORE DELETE ON neuro_snapshots "
        "BEGIN SELECT RAISE(ABORT, 'rejected'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.save_snapshot("orders", {"value": 2}, 2)
    assert [snapshot.snapshot_id for snapshot in store.get_snapshot_history("orders")] == [original]
    assert store.get_snapshot("orders").state == {"value": 1}
    assert store._conn.in_transaction is False


@pytest.mark.parametrize("operation", ["delete_stream", "clear"])
def test_event_and_snapshot_removal_is_one_transaction(owned_stores, operation):
    store = owned_stores("events")
    event_id = store.append(event(), stream_id="orders")
    snapshot_id = store.save_snapshot("orders", {"value": 1}, 1)
    store._conn.execute(
        "CREATE TRIGGER reject_snapshot_removal BEFORE DELETE ON neuro_snapshots "
        "BEGIN SELECT RAISE(ABORT, 'rejected'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "clear":
            store.clear()
        else:
            store.delete_stream("orders")
    assert store.get(event_id) is not None
    assert store.get_snapshot("orders").snapshot_id == snapshot_id
    assert store._sequence_counter == 1
    assert store._conn.in_transaction is False


@pytest.mark.parametrize("mode", ["memory", "sqlite"])
def test_unexpected_callback_failure_releases_live_claim(owned_stores, mode):
    queue = DeadLetterQueue() if mode == "memory" else owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    attempts = []

    def consume(_event):
        attempts.append(len(attempts))
        if len(attempts) == 1:
            raise TypeError("unexpected handler failure")

    queue.on_replay(consume)
    with pytest.raises(TypeError, match="unexpected handler failure"):
        queue.replay(entry_id)
    assert queue.get_stats()["replayed"] == 0
    assert queue.dequeue(entry_id).retry_count == 0
    assert queue.replay(entry_id) == (True, "")
    assert len(attempts) == 2


def test_replay_refuses_a_symlink_lock_without_touching_its_target(owned_stores, tmp_path):
    queue = owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    delivered = []
    queue.on_replay(delivered.append)
    target = tmp_path / "unrelated.txt"
    target.write_text("unchanged")
    (tmp_path / "events.sqlite3.dlq-replay.lock").symlink_to(target)
    with pytest.raises(OSError, match="Invalid lock path"):
        queue.replay(entry_id)
    assert target.read_text() == "unchanged"
    assert delivered == []
    assert queue.dequeue(entry_id).retry_count == 0


@pytest.mark.parametrize("mode", ["memory", "sqlite"])
def test_handler_can_replay_a_different_entry_in_the_same_thread(owned_stores, mode):
    queue = DeadLetterQueue() if mode == "memory" else owned_stores("dlq")
    first = queue.enqueue(event("first"), DeadLetterReason.TIMEOUT, "timeout", 0)
    second = queue.enqueue(event("second"), DeadLetterReason.TIMEOUT, "timeout", 0)
    delivered = []

    def consume(item):
        delivered.append(item.event_type)
        if item.event_type == "first":
            assert queue.replay(second) == (True, "")

    queue.on_replay(consume)
    assert queue.replay(first) == (True, "")
    assert delivered == ["first", "second"]
    assert queue.get_stats()["replayed"] == 2


def test_process_exit_releases_claim_but_does_not_promise_exactly_once(owned_stores, tmp_path):
    queue = owned_stores("dlq")
    entry_id = queue.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    side_effect = tmp_path / "delivered.txt"
    child = """
import os, sys
from pathlib import Path
from app.neuro_bus.dead_letter_queue import DeadLetterQueue
queue = DeadLetterQueue(storage_path=sys.argv[1])
def consume(event):
    Path(sys.argv[3]).write_text('first delivery')
    os._exit(0)
queue.on_replay(consume)
queue.replay(sys.argv[2])
raise AssertionError('callback did not exit the process')
"""
    subprocess.run(
        [sys.executable, "-c", child, str(tmp_path / "events.sqlite3"), entry_id, str(side_effect)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert side_effect.read_text() == "first delivery"
    assert queue._deduplicator.is_replayed(entry_id, 0) is False
    queue.on_replay(lambda _event: side_effect.write_text("delivery after crash"))
    assert queue.replay(entry_id) == (True, "")
    assert side_effect.read_text() == "delivery after crash"
    assert queue._deduplicator.is_replayed(entry_id, 0) is True


@pytest.mark.parametrize("kind", ["events", "dlq"])
def test_closed_sqlite_store_fails_instead_of_falling_back_to_memory(owned_stores, kind):
    store = owned_stores(kind)
    if kind == "events":
        record_id = store.append(event())
    else:
        record_id = store.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    store.close()
    store.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        if kind == "events":
            store.append(event())
        else:
            store.enqueue(event(), DeadLetterReason.TIMEOUT, "timeout", 0)
    reopened = owned_stores(kind)
    if kind == "events":
        assert reopened.get(record_id) is not None
    else:
        assert reopened.dequeue(record_id) is not None
