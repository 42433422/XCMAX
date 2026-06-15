"""Tests for app.neuro_bus.event_store — coverage ramp."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.neuro_bus.event_store import (
    EventStore,
    EventStoreMode,
    Snapshot,
    StoredEvent,
    get_event_store,
    get_event_stats,
    replay_events,
    store_event,
)


def _make_event(event_type: str = "test_event", payload: dict | None = None, source: str = "test"):
    from app.neuro_bus.events.base import NeuroEvent, EventMetadata, EventPriority

    meta = EventMetadata(
        event_id=f"evt-{event_type}",
        source=source,
        correlation_id="corr-1",
    )
    return NeuroEvent(
        event_type=event_type,
        payload=payload or {"key": "value"},
        metadata=meta,
        priority=EventPriority.NORMAL,
    )


class TestStoredEvent:
    def test_to_dict(self):
        event = _make_event("order_created", {"order_id": 42})
        stored = StoredEvent(
            store_id="evt-abc123",
            event=event,
            stored_at=datetime(2026, 1, 1, 12, 0, 0),
            sequence_number=1,
            stream_id="stream-1",
            metadata={"extra": True},
        )
        d = stored.to_dict()
        assert d["store_id"] == "evt-abc123"
        assert d["sequence_number"] == 1
        assert d["stream_id"] == "stream-1"
        assert d["metadata"] == {"extra": True}
        assert d["event"]["event_type"] == "order_created"
        assert d["event"]["payload"] == {"order_id": 42}
        assert d["stored_at"] == "2026-01-01T12:00:00"

    def test_to_dict_no_stream_id(self):
        event = _make_event()
        stored = StoredEvent(
            store_id="evt-x",
            event=event,
            stored_at=datetime(2026, 6, 1),
            sequence_number=5,
        )
        d = stored.to_dict()
        assert d["stream_id"] is None


class TestEventStoreInit:
    def test_default_mode(self):
        store = EventStore()
        assert store._mode == EventStoreMode.MEMORY
        assert store._max_events == 100000
        assert len(store._events) == 0

    def test_custom_max_events(self):
        store = EventStore(max_events=50)
        assert store._max_events == 50


class TestAppend:
    def test_append_returns_store_id(self):
        store = EventStore()
        event = _make_event()
        store_id = store.append(event)
        assert store_id.startswith("evt-")

    def test_append_stores_event(self):
        store = EventStore()
        event = _make_event("test_type")
        store_id = store.append(event)
        stored = store.get(store_id)
        assert stored is not None
        assert stored.event.event_type == "test_type"

    def test_append_with_stream_id(self):
        store = EventStore()
        event = _make_event()
        store.append(event, stream_id="stream-1")
        stream_events = store.get_stream_events("stream-1")
        assert len(stream_events) == 1

    def test_append_increments_sequence(self):
        store = EventStore()
        id1 = store.append(_make_event())
        id2 = store.append(_make_event())
        s1 = store.get(id1)
        s2 = store.get(id2)
        assert s2.sequence_number == s1.sequence_number + 1

    def test_append_triggers_callback(self):
        store = EventStore()
        callback_events = []
        store.on_append(lambda e: callback_events.append(e))
        store.append(_make_event("cb_test"))
        assert len(callback_events) == 1
        assert callback_events[0].event.event_type == "cb_test"

    def test_append_callback_error_does_not_crash(self):
        store = EventStore()

        def bad_callback(e):
            raise RuntimeError("callback failed")

        store.on_append(bad_callback)
        store_id = store.append(_make_event())
        assert store_id is not None

    def test_append_many(self):
        store = EventStore()
        events = [_make_event(f"evt_{i}") for i in range(5)]
        ids = store.append_many(events, stream_id="batch-stream")
        assert len(ids) == 5
        assert all(sid.startswith("evt-") for sid in ids)


class TestGetAll:
    def test_get_all_returns_sorted(self):
        store = EventStore()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        results = list(store.get_all())
        assert len(results) == 2
        assert results[0].sequence_number < results[1].sequence_number

    def test_get_all_filter_by_event_type(self):
        store = EventStore()
        store.append(_make_event("type_a"))
        store.append(_make_event("type_b"))
        results = list(store.get_all(event_type="type_a"))
        assert len(results) == 1
        assert results[0].event.event_type == "type_a"

    def test_get_all_filter_by_time(self):
        store = EventStore()
        store.append(_make_event())
        results = list(store.get_all(start_time=datetime.now() + timedelta(hours=1)))
        assert len(results) == 0

        results = list(store.get_all(end_time=datetime.now() + timedelta(hours=1)))
        assert len(results) == 1


class TestGetStreamEvents:
    def test_returns_events_for_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        events = store.get_stream_events("s1")
        assert len(events) == 2

    def test_from_sequence(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        events = store.get_stream_events("s1", from_sequence=2)
        assert all(e.sequence_number >= 2 for e in events)

    def test_empty_stream(self):
        store = EventStore()
        events = store.get_stream_events("nonexistent")
        assert events == []


class TestGetLatest:
    def test_returns_latest(self):
        store = EventStore()
        for i in range(5):
            store.append(_make_event(f"evt_{i}"))
        latest = store.get_latest(limit=3)
        assert len(latest) == 3
        assert latest[0].sequence_number > latest[-1].sequence_number


class TestSnapshots:
    def test_save_and_get_snapshot(self):
        store = EventStore()
        snap_id = store.save_snapshot("stream-1", {"state": "initial"}, sequence_number=5)
        assert snap_id.startswith("snap-")
        snap = store.get_snapshot("stream-1")
        assert snap is not None
        assert snap.state == {"state": "initial"}
        assert snap.sequence_number == 5

    def test_get_snapshot_not_found(self):
        store = EventStore()
        assert store.get_snapshot("nonexistent") is None

    def test_get_events_after_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"state": "snap"}, sequence_number=2)
        store.append(_make_event(), stream_id="s1")
        events = store.get_events_after_snapshot("s1")
        assert all(e.sequence_number >= 3 for e in events)

    def test_get_events_after_snapshot_no_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        events = store.get_events_after_snapshot("s1")
        assert len(events) == 1


class TestReplay:
    def test_replay_all(self):
        store = EventStore()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        count = store.replay()
        assert count == 2

    def test_replay_with_callback(self):
        store = EventStore()
        store.append(_make_event("x"))
        store.append(_make_event("y"))
        replayed = []
        count = store.replay(callback=lambda e: replayed.append(e.event_type))
        assert count == 2
        assert "x" in replayed
        assert "y" in replayed

    def test_replay_by_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        count = store.replay(stream_id="s1")
        assert count == 1

    def test_replay_by_event_types(self):
        store = EventStore()
        store.append(_make_event("type_a"))
        store.append(_make_event("type_b"))
        count = store.replay(event_types=["type_a"])
        assert count == 1

    def test_replay_callback_error(self):
        store = EventStore()
        store.append(_make_event())

        def bad_cb(e):
            raise RuntimeError("fail")

        count = store.replay(callback=bad_cb)
        assert count == 0


class TestReplayStream:
    def test_replay_stream_with_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"v": 1}, sequence_number=2)
        store.append(_make_event(), stream_id="s1")
        result = store.replay_stream("s1", use_snapshot=True)
        assert result["stream_id"] == "s1"
        assert result["snapshot_used"] is True
        assert result["applied_events"] >= 1

    def test_replay_stream_without_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        result = store.replay_stream("s1", use_snapshot=False)
        assert result["snapshot_used"] is False
        assert result["applied_events"] == 1


class TestAuditLog:
    def test_get_audit_log(self):
        store = EventStore()
        store.append(_make_event("order_created", {"id": 1}), stream_id="s1")
        log = store.get_audit_log(stream_id="s1")
        assert len(log) == 1
        assert log[0]["event_type"] == "order_created"
        assert "id" in log[0]["payload_keys"]

    def test_get_audit_log_all(self):
        store = EventStore()
        store.append(_make_event())
        log = store.get_audit_log()
        assert len(log) == 1


class TestStats:
    def test_empty_stats(self):
        store = EventStore()
        stats = store.get_stats()
        assert stats["total_events"] == 0
        assert stats["streams"] == 0
        assert stats["snapshots"] == 0
        assert stats["oldest_event"] is None
        assert stats["newest_event"] is None

    def test_stats_with_events(self):
        store = EventStore()
        store.append(_make_event("type_a"), stream_id="s1")
        store.append(_make_event("type_b"), stream_id="s1")
        stats = store.get_stats()
        assert stats["total_events"] == 2
        assert stats["streams"] == 1
        assert stats["by_event_type"]["type_a"] == 1
        assert stats["by_stream"]["s1"] == 2
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None


class TestManagement:
    def test_delete_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        count = store.delete_stream("s1")
        assert count == 2
        assert store.get_stream_events("s1") == []
        assert len(store.get_stream_events("s2")) == 1

    def test_delete_stream_with_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"v": 1}, sequence_number=1)
        store.delete_stream("s1")
        assert store.get_snapshot("s1") is None

    def test_clear(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"v": 1}, sequence_number=1)
        store.clear()
        assert len(store._events) == 0
        assert len(store._stream_events) == 0
        assert len(store._snapshots) == 0
        assert store._sequence_counter == 0


class TestCleanup:
    def test_cleanup_oldest_on_max(self):
        store = EventStore(max_events=5)
        for i in range(6):
            store.append(_make_event(f"evt_{i}"))
        assert len(store._events) <= 5


class TestGlobalFunctions:
    def test_get_event_store_singleton(self):
        s1 = get_event_store()
        s2 = get_event_store()
        assert s1 is s2

    def test_store_event(self):
        store = store_event(_make_event("global_test"))
        assert store.startswith("evt-")

    def test_replay_events(self):
        store_event(_make_event("replay_test"))
        count = replay_events()
        assert count >= 1

    def test_get_event_stats(self):
        stats = get_event_stats()
        assert "total_events" in stats
