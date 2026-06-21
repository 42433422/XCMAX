"""Behavioral coverage for app.neuro_bus.event_store.

Covers the paths the existing tests/neuro/test_event_store.py leaves cold:
- UpcasterRegistry: registration validation, chain construction, chained
  upcasting, current-version tracking, chain integrity validation.
- EventStore wired with an upcaster registry (MEMORY + SQLITE): payloads are
  upgraded on read-back.
- Optimistic concurrency control (expected_version semantics).
- append_many / append_with_retry conflict-and-retry loop.
- Full SQLITE backend: append, query, snapshots, replay, stats, delete, clear,
  capacity cleanup.
- Schema validation failures and snapshot hash tampering.

Assertions verify real round-trip behaviour, not mere line execution.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

import pytest

import app.neuro_bus.event_store as event_store_mod
from app.neuro_bus.event_store import (
    EventStore,
    EventStoreMode,
    EventUpcaster,
    InvalidEventError,
    Snapshot,
    StoredEvent,
    UpcasterRegistry,
    WrongExpectedVersionError,
    get_event_stats,
    get_event_store,
    replay_events,
    store_event,
    validate_event_schema,
)
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


def _make_event(
    event_type: str = "demo.event",
    payload: dict[str, Any] | None = None,
    source: str = "unit-test",
    event_id: str | None = None,
) -> NeuroEvent:
    meta = EventMetadata(
        event_id=event_id or "evt-fixed-id",
        source=source,
        trace_id="trace-xyz",
    )
    return NeuroEvent(
        event_type=event_type,
        payload=dict(payload) if payload is not None else {"k": "v"},
        metadata=meta,
        priority=EventPriority.NORMAL,
        preserve_queue_identity=True,
    )


# --------------------------------------------------------------------------- #
# Upcaster helpers
# --------------------------------------------------------------------------- #


class _AddFieldUpcaster(EventUpcaster):
    """v1 -> v2: introduce a `version_tag` field with a default."""

    event_type = "demo.event"
    from_version = 1
    to_version = 2

    def upcast(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        out["version_tag"] = "v2-default"
        return out


class _RenameFieldUpcaster(EventUpcaster):
    """v2 -> v3: rename `name` to `full_name`."""

    event_type = "demo.event"
    from_version = 2
    to_version = 3

    def upcast(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        if "name" in out:
            out["full_name"] = out.pop("name")
        return out


# --------------------------------------------------------------------------- #
# UpcasterRegistry
# --------------------------------------------------------------------------- #


class TestUpcasterRegistry:
    def test_register_tracks_current_version(self):
        reg = UpcasterRegistry()
        assert reg.get_current_version("demo.event") == 1  # unseen defaults to 1
        reg.register(_AddFieldUpcaster())
        assert reg.get_current_version("demo.event") == 2
        reg.register(_RenameFieldUpcaster())
        assert reg.get_current_version("demo.event") == 3

    def test_register_duplicate_raises(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        with pytest.raises(ValueError, match="重复注册"):
            reg.register(_AddFieldUpcaster())

    def test_register_non_consecutive_raises(self):
        class _Skip(EventUpcaster):
            event_type = "demo.event"
            from_version = 1
            to_version = 3  # not from+1

            def upcast(self, payload):
                return payload

        reg = UpcasterRegistry()
        with pytest.raises(ValueError, match="必须连续升级"):
            reg.register(_Skip())

    def test_get_chain_returns_ordered_upcasters(self):
        reg = UpcasterRegistry()
        u1, u2 = _AddFieldUpcaster(), _RenameFieldUpcaster()
        reg.register(u1)
        reg.register(u2)
        chain = reg.get_chain("demo.event", 1, 3)
        assert chain == [u1, u2]
        # Partial chain
        assert reg.get_chain("demo.event", 2, 3) == [u2]
        # Empty when already current
        assert reg.get_chain("demo.event", 3, 3) == []

    def test_get_chain_broken_raises(self):
        reg = UpcasterRegistry()
        reg.register(_RenameFieldUpcaster())  # only v2->v3 registered, v1->v2 missing
        with pytest.raises(ValueError, match="链断裂"):
            reg.get_chain("demo.event", 1, 3)

    def test_upcast_applies_full_chain(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        reg.register(_RenameFieldUpcaster())
        payload, final = reg.upcast("demo.event", {"name": "Alice"}, from_version=1)
        assert final == 3
        # v1->v2 adds version_tag, v2->v3 renames name -> full_name.
        assert payload == {"version_tag": "v2-default", "full_name": "Alice"}

    def test_upcast_noop_when_already_current(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())  # current = 2
        payload, final = reg.upcast("demo.event", {"x": 1}, from_version=2)
        assert final == 2
        assert payload == {"x": 1}
        # from_version greater than target also returns unchanged
        payload2, final2 = reg.upcast("demo.event", {"x": 1}, from_version=5)
        assert final2 == 5
        assert payload2 == {"x": 1}

    def test_upcast_unknown_event_type_is_noop(self):
        reg = UpcasterRegistry()
        payload, final = reg.upcast("unregistered", {"a": 1}, from_version=1)
        assert (payload, final) == ({"a": 1}, 1)

    def test_validate_chains_passes_for_complete_chain(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        reg.register(_RenameFieldUpcaster())
        # Should not raise.
        reg.validate_chains()

    def test_validate_chains_detects_gap(self):
        reg = UpcasterRegistry()
        # Manually inject a broken state: current version 3 but only v2->v3 present.
        reg.register(_RenameFieldUpcaster())  # registers v2->v3, current = 3
        with pytest.raises(ValueError, match="链断裂"):
            reg.validate_chains()


# --------------------------------------------------------------------------- #
# validate_event_schema
# --------------------------------------------------------------------------- #


class TestValidateEventSchema:
    def test_valid_event_returns_true(self):
        assert validate_event_schema(_make_event()) is True

    def test_empty_event_type_raises(self):
        ev = _make_event()
        ev.event_type = ""
        with pytest.raises(InvalidEventError, match="event_type"):
            validate_event_schema(ev)

    def test_non_dict_payload_raises(self):
        ev = _make_event()
        ev.payload = ["not", "a", "dict"]  # type: ignore[assignment]
        with pytest.raises(InvalidEventError, match="payload"):
            validate_event_schema(ev)

    def test_missing_event_id_raises(self):
        ev = _make_event()
        ev.metadata.event_id = ""
        with pytest.raises(InvalidEventError, match="event_id"):
            validate_event_schema(ev)


# --------------------------------------------------------------------------- #
# EventStore + UpcasterRegistry (MEMORY)
# --------------------------------------------------------------------------- #


class TestEventStoreUpcastingMemory:
    def test_init_validates_chains(self):
        reg = UpcasterRegistry()
        reg.register(_RenameFieldUpcaster())  # broken: current 3, missing v1->v2
        with pytest.raises(ValueError, match="链断裂"):
            EventStore(upcaster_registry=reg)

    def test_append_records_current_schema_version(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        reg.register(_RenameFieldUpcaster())  # current version 3
        store = EventStore(upcaster_registry=reg)
        sid = store.append(_make_event(payload={"name": "Bob"}))
        stored = store.get(sid)
        assert stored is not None
        # Stored as current version, so no upcasting needed on read; payload as-is.
        assert stored.metadata["event_schema_version"] == 3

    def test_read_applies_upcasters_to_old_payload(self):
        # Build a store with NO registry, append an "old" v1 event,
        # then attach a registry and confirm read upgrades it.
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        reg.register(_RenameFieldUpcaster())
        store = EventStore(upcaster_registry=reg)
        # Force-inject a v1 stored event bypassing the schema-version stamping.
        ev = _make_event(payload={"name": "Carol"})
        sid = store.append(ev)
        # Simulate that this event was actually stored under schema v1.
        store._events[sid].metadata["event_schema_version"] = 1

        upgraded = store.get(sid)
        assert upgraded is not None
        assert upgraded.metadata["event_schema_version"] == 3
        assert upgraded.event.payload["full_name"] == "Carol"
        assert upgraded.event.payload["version_tag"] == "v2-default"
        assert "name" not in upgraded.event.payload
        # Original stored object untouched (immutability contract).
        assert store._events[sid].event.payload == {"name": "Carol"}
        assert store._events[sid].metadata["event_schema_version"] == 1

    def test_get_all_and_get_latest_apply_upcasters(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        store = EventStore(upcaster_registry=reg)
        sid = store.append(_make_event(payload={"a": 1}))
        store._events[sid].metadata["event_schema_version"] = 1

        all_events = list(store.get_all())
        assert all_events[0].event.payload["version_tag"] == "v2-default"

        latest = store.get_latest(limit=5)
        assert latest[0].event.payload["version_tag"] == "v2-default"

    def test_get_stream_events_applies_upcasters(self):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        store = EventStore(upcaster_registry=reg)
        sid = store.append(_make_event(payload={"a": 1}), stream_id="s1")
        store._events[sid].metadata["event_schema_version"] = 1
        events = store.get_stream_events("s1")
        assert events[0].event.payload["version_tag"] == "v2-default"


# --------------------------------------------------------------------------- #
# Optimistic concurrency control
# --------------------------------------------------------------------------- #


class TestExpectedVersion:
    def test_create_requires_empty_stream(self):
        store = EventStore()
        # -1 means stream must NOT exist yet.
        store.append(_make_event(), stream_id="agg", expected_version=-1)
        # Second create attempt must fail since stream now has 1 event.
        with pytest.raises(WrongExpectedVersionError) as exc:
            store.append(_make_event(), stream_id="agg", expected_version=-1)
        assert exc.value.expected == -1
        assert exc.value.actual == 1
        assert exc.value.stream_id == "agg"

    def test_exact_version_match(self):
        store = EventStore()
        store.append(_make_event(), stream_id="agg")  # version now 1
        store.append(_make_event(), stream_id="agg", expected_version=1)  # ok
        with pytest.raises(WrongExpectedVersionError):
            store.append(_make_event(), stream_id="agg", expected_version=1)  # now 2

    def test_minus_two_allows_any(self):
        store = EventStore()
        # -2 allows append whether or not stream exists.
        store.append(_make_event(), stream_id="agg", expected_version=-2)
        store.append(_make_event(), stream_id="agg", expected_version=-2)
        assert len(store.get_stream_events("agg")) == 2

    def test_none_skips_check(self):
        store = EventStore()
        store.append(_make_event(), stream_id="agg", expected_version=None)
        assert len(store.get_stream_events("agg")) == 1

    def test_invalid_expected_version_raises_value_error(self):
        store = EventStore()
        with pytest.raises(ValueError, match="不支持的 expected_version"):
            store.append(_make_event(), stream_id="agg", expected_version=-99)


# --------------------------------------------------------------------------- #
# append_many / append_with_retry
# --------------------------------------------------------------------------- #


class TestAppendMany:
    def test_append_many_empty_returns_empty(self):
        store = EventStore()
        assert store.append_many([]) == []

    def test_append_many_memory_stores_all(self):
        store = EventStore()
        events = [_make_event(payload={"i": i}) for i in range(3)]
        ids = store.append_many(events, stream_id="batch")
        assert len(ids) == 3
        assert len(store.get_stream_events("batch")) == 3

    def test_append_many_expected_version_on_first(self):
        store = EventStore()
        store.append(_make_event(), stream_id="batch")  # version 1
        # expected_version=0 means "empty" but stream has 1 -> conflict.
        with pytest.raises(WrongExpectedVersionError):
            store.append_many(
                [_make_event(), _make_event()],
                stream_id="batch",
                expected_version=0,
            )

    def test_append_many_validates_schema(self):
        store = EventStore()
        bad = _make_event()
        bad.event_type = ""
        with pytest.raises(InvalidEventError):
            store.append_many([_make_event(), bad], stream_id="batch")


class TestAppendWithRetry:
    def test_retry_builds_on_current_state(self):
        store = EventStore()

        def build(current: list[StoredEvent]) -> list[NeuroEvent]:
            # Append one event reflecting current count.
            return [_make_event(payload={"seq": len(current)})]

        ids1 = store.append_with_retry("agg", build)
        ids2 = store.append_with_retry("agg", build)
        assert len(ids1) == 1 and len(ids2) == 1
        events = store.get_stream_events("agg")
        assert [e.event.payload["seq"] for e in events] == [0, 1]

    def test_retry_empty_build_returns_empty(self):
        store = EventStore()
        result = store.append_with_retry("agg", lambda _cur: [])
        assert result == []

    def test_retry_exhausted_raises(self, monkeypatch):
        store = EventStore()

        # Force every append_many to conflict so retries exhaust.
        def always_conflict(*_a, **_k):
            raise WrongExpectedVersionError("agg", 0, 99)

        monkeypatch.setattr(store, "append_many", always_conflict)
        # Zero delay so the test is fast.
        with pytest.raises(WrongExpectedVersionError):
            store.append_with_retry(
                "agg",
                lambda _cur: [_make_event()],
                max_retries=2,
                base_delay=0.0,
            )


# --------------------------------------------------------------------------- #
# Append callbacks
# --------------------------------------------------------------------------- #


class TestAppendCallbacks:
    def test_callback_invoked_on_append(self):
        store = EventStore()
        seen: list[StoredEvent] = []
        store.on_append(seen.append)
        store.append(_make_event())
        assert len(seen) == 1
        assert isinstance(seen[0], StoredEvent)

    def test_callback_exception_is_swallowed(self):
        store = EventStore()

        def boom(_stored: StoredEvent) -> None:
            raise ValueError("callback failed")  # in RECOVERABLE_ERRORS

        store.on_append(boom)
        # Append must still succeed despite callback error.
        sid = store.append(_make_event())
        assert store.get(sid) is not None


# --------------------------------------------------------------------------- #
# SQLITE backend
# --------------------------------------------------------------------------- #


@pytest.fixture
def sqlite_store(tmp_path):
    path = tmp_path / "events.db"
    store = EventStore(mode=EventStoreMode.SQLITE, storage_path=str(path))
    yield store
    if store._conn is not None:
        store._conn.close()


class TestSqliteInit:
    def test_sqlite_requires_storage_path(self):
        with pytest.raises(ValueError, match="storage_path"):
            EventStore(mode=EventStoreMode.SQLITE, storage_path=None)

    def test_sequence_counter_restored_on_reopen(self, tmp_path):
        path = str(tmp_path / "reopen.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=path)
        store.append(_make_event())
        store.append(_make_event())
        assert store._sequence_counter == 2
        store._conn.close()
        # Reopen: counter must resume from persisted max sequence.
        store2 = EventStore(mode=EventStoreMode.SQLITE, storage_path=path)
        try:
            assert store2._sequence_counter == 2
            sid = store2.append(_make_event())
            assert store2.get(sid).sequence_number == 3
        finally:
            store2._conn.close()


class TestSqliteRoundTrip:
    def test_append_and_get(self, sqlite_store):
        sid = sqlite_store.append(_make_event(payload={"hello": "world"}))
        stored = sqlite_store.get(sid)
        assert stored is not None
        assert stored.event.payload == {"hello": "world"}
        assert stored.store_id == sid

    def test_get_missing_returns_none(self, sqlite_store):
        assert sqlite_store.get("evt-nonexistent") is None

    def test_get_stream_events_ordered(self, sqlite_store):
        for i in range(3):
            sqlite_store.append(_make_event(payload={"i": i}), stream_id="st")
        events = sqlite_store.get_stream_events("st")
        assert [e.event.payload["i"] for e in events] == [0, 1, 2]
        # from_sequence filter
        tail = sqlite_store.get_stream_events("st", from_sequence=2)
        assert [e.event.payload["i"] for e in tail] == [1, 2]

    def test_get_all_filters(self, sqlite_store):
        sqlite_store.append(_make_event(event_type="type.a"))
        sqlite_store.append(_make_event(event_type="type.b"))
        only_a = list(sqlite_store.get_all(event_type="type.a"))
        assert len(only_a) == 1
        assert only_a[0].event.event_type == "type.a"
        # Time window in the future yields nothing.
        future = datetime.now() + timedelta(days=1)
        assert list(sqlite_store.get_all(start_time=future)) == []
        # Past window yields all.
        past = datetime.now() - timedelta(days=1)
        assert len(list(sqlite_store.get_all(start_time=past))) == 2

    def test_get_latest(self, sqlite_store):
        for i in range(5):
            sqlite_store.append(_make_event(payload={"i": i}))
        latest = sqlite_store.get_latest(limit=2)
        assert len(latest) == 2
        # Newest first (highest sequence).
        assert latest[0].sequence_number > latest[1].sequence_number

    def test_expected_version_sqlite(self, sqlite_store):
        sqlite_store.append(_make_event(), stream_id="agg", expected_version=-1)
        with pytest.raises(WrongExpectedVersionError):
            sqlite_store.append(_make_event(), stream_id="agg", expected_version=-1)

    def test_append_many_sqlite_atomic(self, sqlite_store):
        ids = sqlite_store.append_many(
            [_make_event(payload={"i": i}) for i in range(4)],
            stream_id="batch",
        )
        assert len(ids) == 4
        assert len(sqlite_store.get_stream_events("batch")) == 4

    def test_append_many_sqlite_conflict(self, sqlite_store):
        sqlite_store.append(_make_event(), stream_id="batch")
        with pytest.raises(WrongExpectedVersionError):
            sqlite_store.append_many(
                [_make_event()], stream_id="batch", expected_version=0
            )

    def test_callback_fires_in_append_many_sqlite(self, sqlite_store):
        seen: list[StoredEvent] = []
        sqlite_store.on_append(seen.append)
        sqlite_store.append_many([_make_event(), _make_event()], stream_id="cb")
        assert len(seen) == 2


class TestSqliteSnapshots:
    def test_save_and_get_snapshot(self, sqlite_store):
        sid = sqlite_store.save_snapshot("st", {"balance": 100}, sequence_number=5)
        assert sid.startswith("snap-")
        snap = sqlite_store.get_snapshot("st")
        assert snap is not None
        assert snap.state == {"balance": 100}
        assert snap.sequence_number == 5
        assert "state_hash" in snap.metadata

    def test_get_snapshot_missing(self, sqlite_store):
        assert sqlite_store.get_snapshot("nope") is None

    def test_snapshot_history_and_pruning(self, sqlite_store):
        # max_snapshots_per_stream defaults to 3.
        for i in range(5):
            sqlite_store.save_snapshot("st", {"v": i}, sequence_number=i)
        history = sqlite_store.get_snapshot_history("st", limit=10)
        # Only 3 retained, newest first.
        assert len(history) == 3
        assert history[0].state["v"] == 4

    def test_get_snapshot_at_version(self, sqlite_store):
        sqlite_store.save_snapshot("st", {"v": 1}, sequence_number=10)
        sqlite_store.save_snapshot("st", {"v": 2}, sequence_number=20)
        snap = sqlite_store.get_snapshot_at_version("st", 10)
        assert snap is not None and snap.state["v"] == 1
        assert sqlite_store.get_snapshot_at_version("st", 999) is None

    def test_get_events_after_snapshot(self, sqlite_store):
        for i in range(4):
            sqlite_store.append(_make_event(payload={"i": i}), stream_id="st")
        # Snapshot at sequence 2 -> only events with seq > 2 returned.
        sqlite_store.save_snapshot("st", {"folded": True}, sequence_number=2)
        after = sqlite_store.get_events_after_snapshot("st")
        assert [e.sequence_number for e in after] == [3, 4]

    def test_events_after_snapshot_without_snapshot(self, sqlite_store):
        for i in range(2):
            sqlite_store.append(_make_event(), stream_id="st")
        after = sqlite_store.get_events_after_snapshot("st")
        assert len(after) == 2


class TestSqliteManagement:
    def test_delete_stream_logical(self, sqlite_store):
        for _ in range(3):
            sqlite_store.append(_make_event(), stream_id="doomed")
        sqlite_store.save_snapshot("doomed", {"x": 1}, sequence_number=1)
        count = sqlite_store.delete_stream("doomed")
        assert count == 3
        # Logical delete: events no longer visible.
        assert sqlite_store.get_stream_events("doomed") == []
        assert sqlite_store.get_snapshot("doomed") is None

    def test_clear(self, sqlite_store):
        sqlite_store.append(_make_event(), stream_id="s")
        sqlite_store.save_snapshot("s", {"x": 1}, sequence_number=1)
        sqlite_store.clear()
        assert sqlite_store.get_stats()["total_events"] == 0
        assert sqlite_store._sequence_counter == 0

    def test_stats(self, sqlite_store):
        sqlite_store.append(_make_event(event_type="a"), stream_id="s1")
        sqlite_store.append(_make_event(event_type="b"), stream_id="s1")
        sqlite_store.append(_make_event(event_type="a"), stream_id="s2")
        stats = sqlite_store.get_stats()
        assert stats["total_events"] == 3
        assert stats["by_event_type"] == {"a": 2, "b": 1}
        assert stats["by_stream"] == {"s1": 2, "s2": 1}
        assert stats["streams"] == 2
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None

    def test_stats_empty(self, sqlite_store):
        stats = sqlite_store.get_stats()
        assert stats["total_events"] == 0
        assert stats["oldest_event"] is None
        assert stats["newest_event"] is None

    def test_capacity_cleanup_logical(self, tmp_path):
        path = str(tmp_path / "cap.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=path, max_events=2)
        try:
            store.append(_make_event(payload={"i": 0}))
            store.append(_make_event(payload={"i": 1}))
            # Third append triggers _cleanup_oldest (logical delete of 1000 oldest).
            store.append(_make_event(payload={"i": 2}))
            stats = store.get_stats()
            # Oldest events logically deleted; only newest survives.
            assert stats["total_events"] == 1
        finally:
            store._conn.close()


class TestSqliteUpcasting:
    def test_row_upcast_on_read(self, tmp_path):
        reg = UpcasterRegistry()
        reg.register(_AddFieldUpcaster())
        reg.register(_RenameFieldUpcaster())
        path = str(tmp_path / "up.db")
        store = EventStore(
            mode=EventStoreMode.SQLITE,
            storage_path=path,
            upcaster_registry=reg,
        )
        try:
            sid = store.append(_make_event(payload={"name": "Dave"}))
            # Persisted at current version 3 -> read back unchanged structurally.
            stored = store.get(sid)
            assert stored.metadata["event_schema_version"] == 3
            # Now downgrade the persisted schema version to force an upcast on read.
            store._conn.execute(
                "UPDATE neuro_events SET metadata = ? WHERE store_id = ?",
                ('{"event_schema_version": 1}', sid),
            )
            upgraded = store.get(sid)
            assert upgraded.metadata["event_schema_version"] == 3
            assert upgraded.event.payload["full_name"] == "Dave"
            assert upgraded.event.payload["version_tag"] == "v2-default"
        finally:
            store._conn.close()


# --------------------------------------------------------------------------- #
# Replay & snapshot hash verification (MEMORY)
# --------------------------------------------------------------------------- #


class TestReplay:
    def test_replay_all_with_callback(self):
        store = EventStore()
        for i in range(3):
            store.append(_make_event(payload={"i": i}))
        seen: list[NeuroEvent] = []
        count = store.replay(callback=seen.append)
        assert count == 3
        assert len(seen) == 3

    def test_replay_type_filter(self):
        store = EventStore()
        store.append(_make_event(event_type="keep"))
        store.append(_make_event(event_type="drop"))
        seen: list[str] = []
        count = store.replay(event_types=["keep"], callback=lambda e: seen.append(e.event_type))
        assert count == 1
        assert seen == ["keep"]

    def test_replay_stream_specific(self):
        store = EventStore()
        store.append(_make_event(), stream_id="a")
        store.append(_make_event(), stream_id="b")
        count = store.replay(stream_id="a", callback=lambda _e: None)
        assert count == 1

    def test_replay_no_callback_counts(self):
        store = EventStore()
        store.append(_make_event())
        assert store.replay() == 1

    def test_replay_callback_error_swallowed(self):
        store = EventStore()
        store.append(_make_event())
        store.append(_make_event())

        def boom(_e: NeuroEvent) -> None:
            raise RuntimeError("replay boom")

        # Both fail -> count stays 0 but no exception escapes.
        assert store.replay(callback=boom) == 0

    def test_replay_stream_uses_snapshot(self):
        store = EventStore()
        for i in range(4):
            store.append(_make_event(payload={"i": i}), stream_id="agg")
        store.save_snapshot("agg", {"folded": 2}, sequence_number=2)
        applied: list[Any] = []
        result = store.replay_stream("agg", callback=lambda e: applied.append(e))
        assert result["snapshot_used"] is True
        assert result["snapshot_hash_verified"] is True
        assert result["snapshot_sequence"] == 2
        assert "snapshot_age_seconds" in result
        # Only events after snapshot replayed (seq 3 and 4).
        assert result["applied_events"] == 2

    def test_replay_stream_no_snapshot_full_replay(self):
        store = EventStore()
        for _ in range(3):
            store.append(_make_event(), stream_id="agg")
        result = store.replay_stream("agg", use_snapshot=False)
        assert result["snapshot_used"] is False
        assert result["applied_events"] == 3

    def test_replay_stream_tampered_snapshot_falls_back(self):
        store = EventStore()
        for i in range(3):
            store.append(_make_event(payload={"i": i}), stream_id="agg")
        store.save_snapshot("agg", {"x": 1}, sequence_number=1)
        # Tamper with the stored state so its hash no longer matches metadata.
        snap = store.get_snapshot("agg")
        snap.state["x"] = 999  # mutate in place; hash now stale
        result = store.replay_stream("agg")
        assert result["snapshot_hash_verified"] is False
        assert result["snapshot_used"] is False
        # Full replay of all 3 events since snapshot discarded.
        assert result["applied_events"] == 3


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #


class TestAuditLog:
    def test_audit_log_all(self):
        store = EventStore()
        store.append(_make_event(event_type="login", payload={"user": "x"}))
        log = store.get_audit_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["event_type"] == "login"
        assert entry["correlation_id"] == "trace-xyz"
        assert entry["payload_keys"] == ["user"]

    def test_audit_log_by_stream(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        log = store.get_audit_log(stream_id="s1")
        assert len(log) == 1


# --------------------------------------------------------------------------- #
# Concurrency smoke test
# --------------------------------------------------------------------------- #


class TestConcurrency:
    def test_concurrent_appends_unique_sequences(self):
        store = EventStore()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(20):
                    store.append(_make_event(), stream_id="shared")
            except Exception as exc:  # noqa: BLE001 - record for assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        events = store.get_stream_events("shared")
        assert len(events) == 80
        # Sequence numbers must be unique under the lock.
        seqs = [e.sequence_number for e in events]
        assert len(set(seqs)) == 80


# --------------------------------------------------------------------------- #
# StoredEvent / Snapshot dataclasses
# --------------------------------------------------------------------------- #


class TestDataclasses:
    def test_stored_event_to_dict(self):
        store = EventStore()
        sid = store.append(_make_event(payload={"a": 1}), stream_id="s")
        stored = store.get(sid)
        d = stored.to_dict()
        assert d["store_id"] == sid
        assert d["event"]["payload"] == {"a": 1}
        assert d["stream_id"] == "s"
        assert "stored_at" in d

    def test_snapshot_defaults(self):
        snap = Snapshot(
            snapshot_id="snap-1",
            stream_id="s",
            sequence_number=1,
            state={"x": 1},
            created_at=datetime.now(),
        )
        assert snap.version == 1
        assert snap.metadata == {}


# --------------------------------------------------------------------------- #
# MEMORY-mode management (delete_stream / clear / stats / cleanup)
# --------------------------------------------------------------------------- #


class TestMemoryManagement:
    def test_delete_stream_physical(self):
        store = EventStore()
        for _ in range(3):
            store.append(_make_event(), stream_id="doomed")
        store.save_snapshot("doomed", {"x": 1}, sequence_number=1)
        count = store.delete_stream("doomed")
        assert count == 3
        # Physical removal: events, index and snapshot all gone.
        assert store.get_stream_events("doomed") == []
        assert store.get_snapshot("doomed") is None
        assert store.get_stats()["total_events"] == 0

    def test_clear_memory(self):
        store = EventStore()
        store.append(_make_event(), stream_id="s")
        store.save_snapshot("s", {"x": 1}, sequence_number=1)
        store.clear()
        assert store.get_stats()["total_events"] == 0
        assert store._sequence_counter == 0
        assert store.get_snapshot("s") is None

    def test_stats_memory(self):
        store = EventStore()
        store.append(_make_event(event_type="a"), stream_id="s1")
        store.append(_make_event(event_type="b"), stream_id="s1")
        store.append(_make_event(event_type="a"))  # no stream
        stats = store.get_stats()
        assert stats["total_events"] == 3
        assert stats["by_event_type"] == {"a": 2, "b": 1}
        assert stats["by_stream"] == {"s1": 2}
        assert stats["streams"] == 1
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None

    def test_stats_empty_memory(self):
        store = EventStore()
        stats = store.get_stats()
        assert stats["total_events"] == 0
        assert stats["oldest_event"] is None
        assert stats["newest_event"] is None

    def test_capacity_cleanup_memory(self):
        store = EventStore(max_events=2)
        store.append(_make_event(payload={"i": 0}), stream_id="s")
        store.append(_make_event(payload={"i": 1}), stream_id="s")
        # Third append triggers _cleanup_oldest(count=1000) -> removes the
        # two existing events (oldest first) before storing the new one.
        store.append(_make_event(payload={"i": 2}), stream_id="s")
        remaining = list(store.get_all())
        assert len(remaining) == 1
        assert remaining[0].event.payload["i"] == 2
        # Stream index pruned for removed events.
        assert len(store.get_stream_events("s")) == 1


# --------------------------------------------------------------------------- #
# Module-level helpers / global singleton
# --------------------------------------------------------------------------- #


class TestModuleHelpers:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        original = event_store_mod._event_store_instance
        event_store_mod._event_store_instance = None
        yield
        event_store_mod._event_store_instance = original

    def test_get_event_store_is_singleton(self):
        s1 = get_event_store()
        s2 = get_event_store()
        assert s1 is s2

    def test_store_event_and_stats_helpers(self):
        sid = store_event(_make_event(event_type="helper"), stream_id="h")
        assert sid.startswith("evt-")
        stats = get_event_stats()
        assert stats["total_events"] == 1
        assert stats["by_event_type"] == {"helper": 1}

    def test_replay_events_helper(self):
        store_event(_make_event())
        seen: list[Any] = []
        count = replay_events(callback=seen.append)
        assert count == 1
        assert len(seen) == 1
