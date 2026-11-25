"""Durable admission is independent of volatile queue acceptance."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.event_store import EventStore, EventStoreMode, InvalidEventError
from app.neuro_bus.events.events_base import NeuroEvent


@pytest.fixture
def bus(monkeypatch):
    monkeypatch.setenv("FHD_ENV", "test")
    for flag in (
        "SLA_LOG",
        "RETRY",
        "RATE_LIMIT",
        "CIRCUIT",
        "LIFELINE",
        "TRACE",
        "DLQ_AUTO",
        "REDIS_PUBSUB",
        "DEDUP",
    ):
        monkeypatch.setenv(f"XCAGI_NEURO_BUS_{flag}", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "")
    return NeuroBus()


def _event():
    return NeuroEvent("test.admission", {"tenant_id": "t1", "value": 17})


def test_commit_is_visible_to_an_independent_connection_before_queue(bus, tmp_path, monkeypatch):
    path = str(tmp_path / "events.sqlite")
    store = EventStore(EventStoreMode.SQLITE, path)
    event = _event()
    calls = []

    def enqueue(stored):
        reader = EventStore(EventStoreMode.SQLITE, path)
        try:
            actual = reader.get_admitted_event(event.metadata.event_id)
            assert actual is not None
            assert actual.to_dict() == event.to_dict() == stored.to_dict()
            calls.append(stored.metadata.event_id)
            return True
        finally:
            reader.close()

    monkeypatch.setattr(bus, "publish", enqueue)
    try:
        receipt = bus.publish_reliable(event, event_store=store)
        assert receipt.newly_admitted and receipt.queued is True
        assert receipt.event_id == event.metadata.event_id
        assert len(receipt.event_sha256) == 64
        again = bus.publish_reliable(event, event_store=store)
        assert not again.newly_admitted and again.queued is None
        assert again.admitted_at == receipt.admitted_at
        assert again.event_sha256 == receipt.event_sha256
        assert calls == [receipt.event_id]
    finally:
        store.close()


def test_queue_refusal_preserves_original_receipt_across_reopen(bus, tmp_path):
    path = str(tmp_path / "events.sqlite")
    event = _event()
    store = EventStore(EventStoreMode.SQLITE, path)
    try:
        # The real bus has not started; its local queue rejects the event.
        receipt = bus.publish_reliable(event, event_store=store)
        assert receipt.newly_admitted and receipt.queued is False
    finally:
        store.close()
    reader = EventStore(EventStoreMode.SQLITE, path)
    try:
        stored = reader.get_admitted_event(receipt.event_id)
        assert stored is not None and stored.to_dict() == event.to_dict()
        duplicate = bus.publish_reliable(stored, event_store=reader)
        assert not duplicate.newly_admitted and duplicate.queued is None
        assert duplicate.admitted_at == receipt.admitted_at
        stored.payload["value"] = 99
        with pytest.raises(InvalidEventError, match="identity conflict"):
            bus.publish_reliable(stored, event_store=reader)
    finally:
        reader.close()


@pytest.mark.parametrize("mode", [EventStoreMode.MEMORY, EventStoreMode.SQLITE])
def test_memory_store_never_acknowledges_reliable_admission(bus, mode, monkeypatch):
    store = EventStore(mode, ":memory:" if mode == EventStoreMode.SQLITE else None)
    calls = []
    monkeypatch.setattr(bus, "publish", calls.append)
    try:
        with pytest.raises(RuntimeError, match="file-backed|in-memory"):
            bus.publish_reliable(_event(), event_store=store)
        assert calls == []
    finally:
        store.close()


def test_insert_failure_does_not_dispatch_or_persist(bus, tmp_path, monkeypatch):
    import sqlite3

    store = EventStore(EventStoreMode.SQLITE, str(tmp_path / "events.sqlite"))
    event = _event()
    calls = []
    monkeypatch.setattr(bus, "publish", calls.append)
    try:
        assert store._conn is not None
        store._conn.execute(
            """CREATE TRIGGER reject_admission BEFORE INSERT ON neuro_admissions
            BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"""
        ).close()
        with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
            bus.publish_reliable(event, event_store=store)
        assert calls == []
        assert store.get_admitted_event(event.metadata.event_id) is None
        store._conn.execute("DROP TRIGGER reject_admission").close()
        monkeypatch.setattr(bus, "publish", lambda _: True)
        assert bus.publish_reliable(event, event_store=store).newly_admitted
    finally:
        store.close()


def test_concurrent_instances_commit_one_admission(tmp_path):
    path = str(tmp_path / "events.sqlite")
    event = _event()
    first = EventStore(EventStoreMode.SQLITE, path)
    second = EventStore(EventStoreMode.SQLITE, path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda store: store.admit(event), (first, second)))
        assert sum(receipt.newly_admitted for receipt in receipts) == 1
        assert receipts[0].admitted_at == receipts[1].admitted_at
        assert receipts[0].event_sha256 == receipts[1].event_sha256
        assert first.get_admitted_event(event.metadata.event_id) is not None
        assert second.get_admitted_event(event.metadata.event_id) is not None
    finally:
        first.close()
        second.close()


def test_ordinary_event_retention_does_not_trim_or_replay_admission(tmp_path):
    store = EventStore(EventStoreMode.SQLITE, str(tmp_path / "events.sqlite"), max_events=1)
    try:
        event = _event()
        receipt = store.admit(event)
        store.append(NeuroEvent("ordinary.first", {}))
        store.append(NeuroEvent("ordinary.second", {}))
        assert store.get_admitted_event(receipt.event_id) is not None
        assert all(record.event.metadata.event_id != receipt.event_id for record in store.get_all())
    finally:
        store.close()
