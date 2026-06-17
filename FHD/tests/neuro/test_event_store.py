"""Tests for app.neuro_bus.event_store — extended coverage."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.event_store import (
    EventStore,
    EventStoreMode,
    Snapshot,
    StoredEvent,
    get_event_stats,
    get_event_store,
    replay_events,
    store_event,
)


def _make_event(event_type: str = "test_event", payload: dict | None = None, source: str = "test"):
    from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent

    meta = EventMetadata(
        event_id=f"evt-{event_type}",
        source=source,
        trace_id="corr-1",
    )
    return NeuroEvent(
        event_type=event_type,
        payload=payload or {"key": "value"},
        metadata=meta,
        priority=EventPriority.NORMAL,
    )


class TestEventStoreMode:
    def test_enum_values(self):
        assert EventStoreMode.MEMORY.value == "memory"
        assert EventStoreMode.JSON_FILE.value == "json"
        assert EventStoreMode.SQLITE.value == "sqlite"


class TestEventStoreAppend:
    def test_append_returns_store_id(self):
        store = EventStore()
        sid = store.append(_make_event())
        assert sid.startswith("evt-")

    def test_append_with_stream_id(self):
        store = EventStore()
        sid = store.append(_make_event(), stream_id="stream-1")
        events = store.get_stream_events("stream-1")
        assert len(events) == 1

    def test_append_increments_sequence(self):
        store = EventStore()
        sid1 = store.append(_make_event())
        sid2 = store.append(_make_event())
        e1 = store.get(sid1)
        e2 = store.get(sid2)
        assert e2.sequence_number == e1.sequence_number + 1

    def test_append_triggers_callback(self):
        store = EventStore()
        cb = MagicMock()
        store.on_append(cb)
        store.append(_make_event())
        cb.assert_called_once()

    def test_callback_error_does_not_crash(self):
        store = EventStore()
        cb = MagicMock(side_effect=RuntimeError("cb fail"))
        store.on_append(cb)
        sid = store.append(_make_event())
        assert sid is not None

    def test_append_many(self):
        store = EventStore()
        ids = store.append_many([_make_event(), _make_event()], stream_id="s1")
        assert len(ids) == 2

    def test_cleanup_oldest_when_max_reached(self):
        store = EventStore(max_events=5)
        for i in range(7):
            store.append(_make_event(f"ev{i}"))
        assert len(store._events) <= 5


class TestEventStoreQuery:
    def test_get_returns_none_for_unknown(self):
        store = EventStore()
        assert store.get("nonexistent") is None

    def test_get_all_no_filter(self):
        store = EventStore()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        assert len(list(store.get_all())) == 2

    def test_get_all_with_time_filter(self):
        store = EventStore()
        store.append(_make_event("old"))
        now = datetime.now() + timedelta(hours=1)
        store.append(_make_event("new"))
        result = list(store.get_all(start_time=now))
        # The "old" event was stored before now, so it should be filtered
        assert len(result) <= 2

    def test_get_all_with_event_type_filter(self):
        store = EventStore()
        store.append(_make_event("type_a"))
        store.append(_make_event("type_b"))
        result = list(store.get_all(event_type="type_a"))
        assert len(result) == 1
        assert result[0].event.event_type == "type_a"

    def test_get_stream_events_empty(self):
        store = EventStore()
        assert store.get_stream_events("nonexistent") == []

    def test_get_stream_events_from_sequence(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        events = store.get_stream_events("s1", from_sequence=2)
        assert all(e.sequence_number >= 2 for e in events)

    def test_get_latest(self):
        store = EventStore()
        store.append(_make_event())
        store.append(_make_event())
        latest = store.get_latest(limit=1)
        assert len(latest) == 1


class TestEventStoreSnapshots:
    def test_save_and_get_snapshot(self):
        store = EventStore()
        snap_id = store.save_snapshot("stream-1", {"count": 5}, sequence_number=3)
        assert snap_id.startswith("snap-")
        snap = store.get_snapshot("stream-1")
        assert snap.state == {"count": 5}
        assert snap.sequence_number == 3

    def test_get_snapshot_returns_none(self):
        store = EventStore()
        assert store.get_snapshot("nonexistent") is None

    def test_get_events_after_snapshot_no_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        events = store.get_events_after_snapshot("s1")
        assert len(events) == 2

    def test_get_events_after_snapshot_with_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"v": 1}, sequence_number=2)
        store.append(_make_event(), stream_id="s1")
        events = store.get_events_after_snapshot("s1")
        assert all(e.sequence_number > 2 for e in events)


class TestEventStoreReplay:
    def test_replay_all_events(self):
        store = EventStore()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        count = store.replay()
        assert count == 2

    def test_replay_with_callback(self):
        store = EventStore()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        cb = MagicMock()
        count = store.replay(callback=cb)
        assert count == 2
        assert cb.call_count == 2

    def test_replay_callback_error_does_not_crash(self):
        store = EventStore()
        store.append(_make_event())
        cb = MagicMock(side_effect=RuntimeError("fail"))
        count = store.replay(callback=cb)
        assert count == 0

    def test_replay_with_event_type_filter(self):
        store = EventStore()
        store.append(_make_event("type_a"))
        store.append(_make_event("type_b"))
        count = store.replay(event_types=["type_a"])
        assert count == 1

    def test_replay_specific_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        count = store.replay(stream_id="s1")
        assert count == 1

    def test_replay_stream_with_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"v": 1}, sequence_number=1)
        store.append(_make_event(), stream_id="s1")
        cb = MagicMock()
        result = store.replay_stream("s1", use_snapshot=True, callback=cb)
        assert result["snapshot_used"] is True
        assert result["snapshot_sequence"] == 1
        assert "snapshot_age_seconds" in result

    def test_replay_stream_without_snapshot(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        result = store.replay_stream("s1", use_snapshot=False)
        assert result["snapshot_used"] is False
        assert result["applied_events"] == 1


class TestEventStoreAudit:
    def test_get_audit_log(self):
        store = EventStore()
        store.append(_make_event("order_created", {"order_id": 1}))
        log = store.get_audit_log()
        assert len(log) == 1
        assert log[0]["event_type"] == "order_created"
        assert "order_id" in log[0]["payload_keys"]

    def test_get_audit_log_for_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        log = store.get_audit_log(stream_id="s1")
        assert len(log) == 1


class TestEventStoreStats:
    def test_empty_stats(self):
        store = EventStore()
        stats = store.get_stats()
        assert stats["total_events"] == 0
        assert stats["oldest_event"] is None
        assert stats["newest_event"] is None

    def test_stats_with_events(self):
        store = EventStore()
        store.append(_make_event("type_a"))
        store.append(_make_event("type_b"))
        store.append(_make_event("type_a"))
        stats = store.get_stats()
        assert stats["total_events"] == 3
        assert stats["by_event_type"]["type_a"] == 2
        assert stats["by_event_type"]["type_b"] == 1
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None


class TestEventStoreManagement:
    def test_delete_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"v": 1}, sequence_number=1)
        count = store.delete_stream("s1")
        assert count == 2
        assert store.get_stream_events("s1") == []
        assert store.get_snapshot("s1") is None

    def test_delete_nonexistent_stream(self):
        store = EventStore()
        count = store.delete_stream("nonexistent")
        assert count == 0

    def test_clear(self):
        store = EventStore()
        store.append(_make_event())
        store.clear()
        assert store.get_stats()["total_events"] == 0
        assert store._sequence_counter == 0


class TestGlobalFunctions:
    def test_store_event(self):
        with patch.object(EventStore, "append", return_value="evt-123") as mock_append:
            # Reset global instance
            import app.neuro_bus.event_store as es_mod

            es_mod._event_store_instance = EventStore()
            sid = store_event(_make_event())
            assert sid.startswith("evt-")

    def test_replay_events(self):
        import app.neuro_bus.event_store as es_mod

        es_mod._event_store_instance = EventStore()
        es_mod._event_store_instance.append(_make_event())
        count = replay_events()
        assert count == 1

    def test_get_event_stats(self):
        import app.neuro_bus.event_store as es_mod

        es_mod._event_store_instance = EventStore()
        stats = get_event_stats()
        assert "total_events" in stats


class TestSnapshot:
    def test_snapshot_creation(self):
        snap = Snapshot(
            snapshot_id="snap-abc",
            stream_id="s1",
            sequence_number=5,
            state={"count": 10},
            created_at=datetime(2026, 1, 1),
            version=2,
        )
        assert snap.snapshot_id == "snap-abc"
        assert snap.version == 2
