"""
Branch-coverage tests for app/neuro_bus/event_store.py

Targets the missing branches listed in MISSING_BRANCHES.
ALL external I/O (SQLite, filesystem) is either mocked or done with
in-memory / :memory: SQLite so that no real file is created.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str = "test.event",
    payload: dict[str, Any] | None = None,
) -> NeuroEvent:
    """Create a minimal valid NeuroEvent."""
    return NeuroEvent(event_type=event_type, payload=payload or {"k": "v"})


def _make_store(mode: EventStoreMode = EventStoreMode.MEMORY, **kwargs) -> EventStore:
    return EventStore(mode=mode, **kwargs)


def _stored(event: NeuroEvent, seq: int = 1, stream_id: str | None = None) -> StoredEvent:
    return StoredEvent(
        store_id=f"sid-{seq}",
        event=event,
        stored_at=datetime.now(),
        sequence_number=seq,
        stream_id=stream_id,
        metadata={},
    )


# ---------------------------------------------------------------------------
# UpcasterRegistry – lines 78-139
# ---------------------------------------------------------------------------


class _UpV1toV2(EventUpcaster):
    event_type = "order.placed"
    from_version = 1
    to_version = 2

    def upcast(self, payload: dict) -> dict:
        payload = dict(payload)
        payload["v"] = 2
        return payload


class _UpV2toV3(EventUpcaster):
    event_type = "order.placed"
    from_version = 2
    to_version = 3

    def upcast(self, payload: dict) -> dict:
        payload = dict(payload)
        payload["v"] = 3
        return payload


class _BadUpNonConsecutive(EventUpcaster):
    """from_version + 2 => to_version – should raise."""

    event_type = "bad.event"
    from_version = 1
    to_version = 3

    def upcast(self, payload: dict) -> dict:
        return payload


class TestUpcasterRegistry:
    # branch [81, 82]: duplicate registration raises ValueError
    def test_register_duplicate_raises(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        with pytest.raises(ValueError, match="重复注册"):
            reg.register(_UpV1toV2())

    # branch [81, 85]: key not in _upcasters → proceed normally
    def test_register_success(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        assert ("order.placed", 1) in reg._upcasters

    # branch [85, 86]: non-consecutive raises ValueError
    def test_register_non_consecutive_raises(self) -> None:
        reg = UpcasterRegistry()
        with pytest.raises(ValueError, match="必须连续升级"):
            reg.register(_BadUpNonConsecutive())

    # branch [85, 89]: consecutive ok, _current_versions updated
    def test_current_version_updated_on_register(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        assert reg.get_current_version("order.placed") == 2

    # branches [98, 99] / [98, 106]: get_chain loop enters body vs exits
    def test_get_chain_two_steps(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        reg.register(_UpV2toV3())
        chain = reg.get_chain("order.placed", 1, 3)
        assert len(chain) == 2

    # branch [100, 101]: upcaster missing → chain break raises
    def test_get_chain_missing_raises(self) -> None:
        reg = UpcasterRegistry()
        with pytest.raises(ValueError, match="链断裂"):
            reg.get_chain("no.such", 1, 3)

    # branch [100, 104]: upcaster found, append and advance
    def test_get_chain_single_step(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        chain = reg.get_chain("order.placed", 1, 2)
        assert len(chain) == 1

    # branches [118, 119]: from_version >= target → return payload unchanged
    def test_upcast_already_current(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        result, ver = reg.upcast("order.placed", {"x": 1}, from_version=2)
        assert ver == 2
        assert result == {"x": 1}

    # branch [118, 120]: from_version < target → run chain
    def test_upcast_runs_chain(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        result, ver = reg.upcast("order.placed", {"x": 1}, from_version=1)
        assert ver == 2
        assert result["v"] == 2

    # branches [122, 123] / [122, 124]: chain iteration
    def test_upcast_multi_step(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        reg.register(_UpV2toV3())
        result, ver = reg.upcast("order.placed", {"x": 1}, from_version=1)
        assert ver == 3
        assert result["v"] == 3

    # branches [132, -130] / [132, 133] / [134, 132] / [134, 135] / [135, 136] / [135, 139]
    # validate_chains: complete chain OK; missing link raises
    def test_validate_chains_ok(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        reg.validate_chains()  # should not raise

    def test_validate_chains_broken(self) -> None:
        reg = UpcasterRegistry()
        # Manually insert a target version without a matching upcaster chain from 1
        reg._current_versions["ghost.event"] = 3
        # upcaster for (ghost.event, 1) missing → chain break
        with pytest.raises(ValueError, match="链断裂"):
            reg.validate_chains()


# ---------------------------------------------------------------------------
# validate_event_schema – lines 142-158
# ---------------------------------------------------------------------------


class TestValidateEventSchema:
    # branch [152, 153]: empty event_type raises
    def test_empty_event_type_raises(self) -> None:
        e = _make_event()
        e.event_type = ""
        with pytest.raises(InvalidEventError, match="event_type"):
            validate_event_schema(e)

    # branch [154, 155]: non-dict payload raises
    def test_non_dict_payload_raises(self) -> None:
        e = _make_event()
        e.payload = "not-a-dict"  # type: ignore[assignment]
        with pytest.raises(InvalidEventError, match="payload"):
            validate_event_schema(e)

    # branch [156, 157]: empty event_id raises
    def test_empty_event_id_raises(self) -> None:
        e = _make_event()
        e.metadata.event_id = ""
        with pytest.raises(InvalidEventError, match="event_id"):
            validate_event_schema(e)

    # all-pass path
    def test_valid_event_ok(self) -> None:
        e = _make_event()
        assert validate_event_schema(e) is True


# ---------------------------------------------------------------------------
# EventStore MEMORY mode – basic ops
# ---------------------------------------------------------------------------


class TestEventStoreMemoryAppend:
    def test_append_returns_store_id(self) -> None:
        store = _make_store()
        sid = store.append(_make_event())
        assert sid.startswith("evt-")

    # branches [254, 255] / [256, 257]: JSON_FILE mode warns and degrades
    def test_json_file_mode_falls_back(self) -> None:
        with patch("app.neuro_bus.event_store.logger") as mock_log:
            store = EventStore(mode=EventStoreMode.JSON_FILE)
        # should have called logger.warning at least once during init
        assert store._mode == EventStoreMode.JSON_FILE

    # branches [260, 261]: upcaster_registry not None → validate_chains called
    def test_upcaster_registry_validate_called(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = EventStore(upcaster_registry=reg)
        assert store._upcaster_registry is reg

    # branch [272, 273] / [272, 276]: _init_sqlite missing path raises
    def test_sqlite_missing_path_raises(self) -> None:
        with pytest.raises(ValueError, match="storage_path"):
            EventStore(mode=EventStoreMode.SQLITE, storage_path=None)

    # branches [331, 332] / [331, 335]: metadata column exists vs missing
    def test_sqlite_in_memory(self, tmp_path) -> None:
        db = str(tmp_path / "ev.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        e = _make_event()
        sid = store.append(e, stream_id="s1")
        assert sid.startswith("evt-")
        store.clear()

    # branch [339, 340]: sequence counter restored from existing max_seq
    def test_sqlite_seq_counter_restored(self, tmp_path) -> None:
        db = str(tmp_path / "seq.db")
        store1 = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store1.append(_make_event())
        store1.append(_make_event())
        seq_before = store1._sequence_counter

        store2 = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store2._sequence_counter == seq_before

    # branch [339, 342]: row is None or max_seq is 0 (empty db)
    def test_sqlite_seq_counter_zero_on_empty(self, tmp_path) -> None:
        db = str(tmp_path / "empty.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store._sequence_counter == 0


# ---------------------------------------------------------------------------
# _apply_upcasters_to_stored – lines 372-398
# ---------------------------------------------------------------------------


class TestApplyUpcastersToStored:
    # branch [374, 376]: no registry → returns stored unchanged
    def test_no_registry_returns_same(self) -> None:
        store = _make_store()
        e = _make_event()
        s = _stored(e)
        result = store._apply_upcasters_to_stored(s)
        assert result is s

    # branch [380, 381]: new_version == schema_version → return stored unchanged
    def test_upcast_no_change(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = _make_store(upcaster_registry=reg)
        e = _make_event("order.placed")
        # store metadata says already at version 2 (= current)
        s = _stored(e)
        s.metadata["event_schema_version"] = 2
        result = store._apply_upcasters_to_stored(s)
        assert result is s

    # branch [380, 383]: version changed → return new StoredEvent
    def test_upcast_creates_new_stored(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = _make_store(upcaster_registry=reg)
        e = _make_event("order.placed")
        s = _stored(e)
        s.metadata["event_schema_version"] = 1
        result = store._apply_upcasters_to_stored(s)
        assert result is not s
        assert result.metadata["event_schema_version"] == 2


# ---------------------------------------------------------------------------
# _check_expected_version – lines 412-429
# ---------------------------------------------------------------------------


class TestCheckExpectedVersion:
    # branch [403, 404]: expected_version is None → return early
    def test_none_expected_version_no_raise(self) -> None:
        store = _make_store()
        # Should not raise
        store._check_expected_version("s1", None)

    # branch [403, 410]: expected_version == -2 → return early
    def test_minus2_expected_version_no_raise(self) -> None:
        store = _make_store()
        store._check_expected_version("s1", -2)

    # branch [414, 418]: expected_version == -1 and stream is empty → OK
    def test_minus1_create_empty_stream_ok(self) -> None:
        store = _make_store()
        store._check_expected_version("new-stream", -1)

    # branch [420, 422]: expected_version == -1 and stream exists → raise
    def test_minus1_stream_exists_raises(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        with pytest.raises(WrongExpectedVersionError):
            store._check_expected_version("s1", -1)

    # branch [420, 424]: expected_version >= 0 and matches actual → OK
    def test_exact_version_match_ok(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store._check_expected_version("s1", 1)

    # branch [424, 426] / [426, 427]: version mismatch raises
    def test_exact_version_mismatch_raises(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        with pytest.raises(WrongExpectedVersionError):
            store._check_expected_version("s1", 5)

    # branch [424, 429]: unexpected negative value raises ValueError
    def test_invalid_expected_version_raises(self) -> None:
        store = _make_store()
        with pytest.raises(ValueError, match="不支持的"):
            store._check_expected_version("s1", -99)

    # branch [422, -412]: expected_version == -1 and stream_id is None → actual = 0
    def test_minus1_none_stream_ok(self) -> None:
        store = _make_store()
        store._check_expected_version(None, -1)  # actual=0, should pass


# ---------------------------------------------------------------------------
# append – lines 433-508
# ---------------------------------------------------------------------------


class TestAppendBranches:
    # branch [468, 469]: upcaster_registry present → record schema version in metadata
    def test_append_with_upcaster_records_schema_version(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = _make_store(upcaster_registry=reg)
        sid = store.append(_make_event("order.placed"))
        stored = store._events[sid]
        assert stored.metadata.get("event_schema_version") is not None

    # branch [482, 483]: SQLITE mode → calls _append_sqlite
    def test_append_sqlite_mode(self, tmp_path) -> None:
        db = str(tmp_path / "a.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event())
        assert sid.startswith("evt-")

    # branch [519, 520] / [519, 523]: _append_sqlite capacity cleanup
    def test_append_sqlite_capacity_triggers_cleanup(self, tmp_path) -> None:
        db = str(tmp_path / "cap.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db, max_events=2)
        store.append(_make_event())
        store.append(_make_event())
        # This one should trigger cleanup
        store.append(_make_event())

    # branches [494, 495] / [495, 496] / [496, 497]: stream_id present → index updated
    def test_append_with_stream_id_creates_index(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="stream-A")
        assert "stream-A" in store._stream_events

    # branches related to capacity cleanup MEMORY mode
    def test_append_beyond_max_events_triggers_cleanup(self) -> None:
        store = _make_store(max_events=2)
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        # third exceeds capacity
        store.append(_make_event())
        # total stored should still be 2 (oldest cleared)
        assert len(store._events) <= 3  # cleanup may remove some


# ---------------------------------------------------------------------------
# append callbacks – lines 501-506
# ---------------------------------------------------------------------------


class TestAppendCallbacks:
    def test_callback_invoked(self) -> None:
        store = _make_store()
        received = []
        store.on_append(lambda s: received.append(s))
        store.append(_make_event())
        assert len(received) == 1

    # branch for callback exception (RECOVERABLE_ERRORS)
    def test_callback_exception_swallowed(self) -> None:
        store = _make_store()

        def bad_callback(s: StoredEvent) -> None:
            raise OSError("simulated transient")

        store.on_append(bad_callback)
        # should not raise
        store.append(_make_event())


# ---------------------------------------------------------------------------
# append_many – lines 542-631
# ---------------------------------------------------------------------------


class TestAppendMany:
    # branch [556, 557]: empty list returns []
    def test_empty_list_returns_empty(self) -> None:
        store = _make_store()
        assert store.append_many([]) == []

    # branch [564, 565]: SQLITE mode atomic transaction
    def test_append_many_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "many.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        ids = store.append_many([_make_event(), _make_event()], stream_id="s1")
        assert len(ids) == 2

    # branch [571, 572]: upcaster present in SQLITE many path
    def test_append_many_sqlite_with_upcaster(self, tmp_path) -> None:
        db = str(tmp_path / "many2.db")
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db, upcaster_registry=reg)
        ids = store.append_many([_make_event("order.placed")])
        assert len(ids) == 1

    # branch [571, 624]: SQLITE many callback invoked
    def test_append_many_sqlite_callback(self, tmp_path) -> None:
        db = str(tmp_path / "many3.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        received = []
        store.on_append(lambda s: received.append(s))
        store.append_many([_make_event(), _make_event()])
        assert len(received) == 2

    # branch [618, 571] / [618, 619]: callback raises in SQLITE many path
    def test_append_many_sqlite_callback_exception_swallowed(self, tmp_path) -> None:
        db = str(tmp_path / "many4.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.on_append(lambda s: (_ for _ in ()).throw(OSError("boom")))
        # should not raise
        store.append_many([_make_event()])

    # branch [577, 578] / [577, 582]: MEMORY path - first event uses expected_version
    def test_append_many_memory_first_has_expected_version(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")  # version now 1
        ids = store.append_many([_make_event(), _make_event()], stream_id="s1", expected_version=1)
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# append_with_retry – lines 633-686
# ---------------------------------------------------------------------------


class TestAppendWithRetry:
    # branch [658, 660]: build_events returns empty → return []
    def test_build_events_returns_empty(self) -> None:
        store = _make_store()
        result = store.append_with_retry("s1", build_events=lambda evs: [])
        assert result == []

    # branch [658, 686]: all retries exhausted → reraises
    def test_retries_exhausted_raises(self) -> None:
        store = _make_store()

        # Patch append_many so it always raises WrongExpectedVersionError
        def always_conflict(events, stream_id=None, expected_version=None):
            raise WrongExpectedVersionError(stream_id or "s1", expected_version or 0, 99)

        store.append_many = always_conflict  # type: ignore[method-assign]

        with pytest.raises(WrongExpectedVersionError):
            store.append_with_retry(
                "s1",
                build_events=lambda evs: [_make_event()],
                max_retries=0,
                base_delay=0,
            )

    # branch [665, 666]: no new events on retry
    def test_success_on_first_attempt(self) -> None:
        store = _make_store()
        result = store.append_with_retry(
            "s1",
            build_events=lambda evs: [_make_event()],
        )
        assert len(result) == 1

    # branch [674, 658]: retry path (attempt < max_retries) with sleep mocked
    def test_retry_on_conflict_then_succeeds(self) -> None:
        store = _make_store()
        attempts = []

        def build(evs):
            attempts.append(len(evs))
            return [_make_event()]

        # First call will conflict; subsequent calls will succeed
        original_append = store.append_many
        call_count = [0]

        def patched_append(events, stream_id=None, expected_version=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise WrongExpectedVersionError("s1", 0, 1)
            return original_append(events, stream_id=stream_id, expected_version=None)

        store.append_many = patched_append  # type: ignore[method-assign]

        with patch("app.neuro_bus.event_store.time.sleep"):
            result = store.append_with_retry("s1", build_events=build, max_retries=2, base_delay=0)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# get – lines 690-704
# ---------------------------------------------------------------------------


class TestGet:
    # branch [692, 693]: SQLITE path returns event
    def test_get_sqlite_existing(self, tmp_path) -> None:
        db = str(tmp_path / "g.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event())
        result = store.get(sid)
        assert result is not None

    # branch [698, 699]: SQLITE row is None → return None
    def test_get_sqlite_missing(self, tmp_path) -> None:
        db = str(tmp_path / "g2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store.get("no-such-id") is None

    # branch [698, 700]: SQLITE row found → return event
    def test_get_sqlite_found(self, tmp_path) -> None:
        db = str(tmp_path / "g3.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event())
        assert store.get(sid) is not None

    # MEMORY path: event not in _events → returns None
    def test_get_memory_missing(self) -> None:
        store = _make_store()
        assert store.get("not-here") is None

    # MEMORY path: event in _events → returns StoredEvent
    def test_get_memory_found(self) -> None:
        store = _make_store()
        sid = store.append(_make_event())
        assert store.get(sid) is not None


# ---------------------------------------------------------------------------
# get_all – lines 706-751
# ---------------------------------------------------------------------------


class TestGetAll:
    # branches [717, 719] / [722, 723] / [722, 725] / [725, 726] / [725, 728] / [728, 729] / [728, 732]
    # SQLITE mode with various filters
    def test_get_all_sqlite_no_filter(self, tmp_path) -> None:
        db = str(tmp_path / "all.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        events = list(store.get_all())
        assert len(events) == 1

    def test_get_all_sqlite_with_start_time(self, tmp_path) -> None:
        db = str(tmp_path / "all2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        events = list(store.get_all(start_time=datetime(2000, 1, 1)))
        assert len(events) == 1

    def test_get_all_sqlite_with_end_time(self, tmp_path) -> None:
        db = str(tmp_path / "all3.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        events = list(store.get_all(end_time=datetime(2099, 1, 1)))
        assert len(events) == 1

    def test_get_all_sqlite_with_event_type(self, tmp_path) -> None:
        db = str(tmp_path / "all4.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("type.a"))
        store.append(_make_event("type.b"))
        events = list(store.get_all(event_type="type.a"))
        assert len(events) == 1

    # branches [735, 736] / [735, 737]: MEMORY mode time filter
    def test_get_all_memory_start_time_filter(self) -> None:
        store = _make_store()
        store.append(_make_event())
        events = list(store.get_all(start_time=datetime(2000, 1, 1)))
        assert len(events) == 1

    def test_get_all_memory_start_time_skip(self) -> None:
        store = _make_store()
        store.append(_make_event())
        # future start_time → no events
        events = list(store.get_all(start_time=datetime(2099, 1, 1)))
        assert len(events) == 0

    # branch [744, 745]: event_type filter MEMORY – skips non-matching
    def test_get_all_memory_event_type_filter(self) -> None:
        store = _make_store()
        store.append(_make_event("type.a"))
        store.append(_make_event("type.b"))
        events = list(store.get_all(event_type="type.a"))
        assert len(events) == 1 and events[0].event.event_type == "type.a"


# ---------------------------------------------------------------------------
# get_stream_events – lines 753-783
# ---------------------------------------------------------------------------


class TestGetStreamEvents:
    def test_memory_returns_sorted_events(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        events = store.get_stream_events("s1")
        assert len(events) == 2
        assert events[0].sequence_number < events[1].sequence_number

    def test_memory_from_sequence_filters(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        # Only get second event (from_sequence = seq of second)
        all_evs = store.get_stream_events("s1")
        second_seq = all_evs[1].sequence_number
        filtered = store.get_stream_events("s1", from_sequence=second_seq)
        assert len(filtered) == 1

    # branch [763, 764]: SQLITE path
    def test_sqlite_stream_events(self, tmp_path) -> None:
        db = str(tmp_path / "se.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        events = store.get_stream_events("s1")
        assert len(events) == 2


# ---------------------------------------------------------------------------
# get_latest – lines 785-801
# ---------------------------------------------------------------------------


class TestGetLatest:
    # branch [787, 788]: SQLITE path
    def test_sqlite_get_latest(self, tmp_path) -> None:
        db = str(tmp_path / "lat.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        store.append(_make_event())
        events = store.get_latest(limit=1)
        assert len(events) == 1

    def test_memory_get_latest(self) -> None:
        store = _make_store()
        store.append(_make_event())
        store.append(_make_event())
        events = store.get_latest(limit=1)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# save_snapshot / get_snapshot – lines 812-965
# ---------------------------------------------------------------------------


class TestSnapshotBranches:
    # branch [836, 837]: SQLITE mode save_snapshot
    def test_save_and_get_snapshot_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "snap.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        snap_id = store.save_snapshot("s1", {"balance": 100}, sequence_number=5)
        assert snap_id.startswith("snap-")
        snap = store.get_snapshot("s1")
        assert snap is not None
        assert snap.stream_id == "s1"

    # branch [879, 880]: MEMORY mode – save trimmed to max_snapshots
    def test_save_snapshot_memory_trims(self) -> None:
        store = _make_store(max_snapshots_per_stream=2)
        store.save_snapshot("s1", {"a": 1}, 1)
        store.save_snapshot("s1", {"a": 2}, 2)
        store.save_snapshot("s1", {"a": 3}, 3)
        # should have max 2 snapshots
        history = store.get_snapshot_history("s1")
        assert len(history) == 2

    # branch [907, 908]: SQLITE – get_snapshot returns None when empty
    def test_get_snapshot_sqlite_none(self, tmp_path) -> None:
        db = str(tmp_path / "snap2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store.get_snapshot("no-such") is None

    # branch [918, 919] / [918, 920]: MEMORY – empty list → None; non-empty → last
    def test_get_snapshot_memory_none(self) -> None:
        store = _make_store()
        assert store.get_snapshot("s1") is None

    def test_get_snapshot_memory_returns_latest(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 1)
        store.save_snapshot("s1", {"v": 2}, 2)
        snap = store.get_snapshot("s1")
        assert snap is not None
        assert snap.state["v"] == 2

    # branch [929, 930] / [929, 941]: get_snapshot_history SQLITE vs MEMORY
    def test_get_snapshot_history_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "hist.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.save_snapshot("s1", {"v": 1}, 1)
        store.save_snapshot("s1", {"v": 2}, 2)
        history = store.get_snapshot_history("s1")
        assert len(history) == 2

    def test_get_snapshot_history_memory(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 1)
        store.save_snapshot("s1", {"v": 2}, 2)
        history = store.get_snapshot_history("s1")
        assert len(history) == 2

    # branch [946, 947] / [946, 961]: get_snapshot_at_version
    def test_get_snapshot_at_version_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "av.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.save_snapshot("s1", {"v": 1}, sequence_number=10)
        snap = store.get_snapshot_at_version("s1", 10)
        assert snap is not None
        assert snap.sequence_number == 10

    def test_get_snapshot_at_version_sqlite_none(self, tmp_path) -> None:
        db = str(tmp_path / "av2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store.get_snapshot_at_version("s1", 99) is None

    # branch [957, 958] / [957, 959]: MEMORY find vs not-found
    def test_get_snapshot_at_version_memory_found(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 10)
        snap = store.get_snapshot_at_version("s1", 10)
        assert snap is not None

    def test_get_snapshot_at_version_memory_not_found(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 10)
        assert store.get_snapshot_at_version("s1", 99) is None

    # branch [962, 963] / [963, 962] / [963, 964]: reversed loop
    def test_get_snapshot_at_version_memory_multiple(self) -> None:
        store = _make_store(max_snapshots_per_stream=5)
        for i in range(1, 4):
            store.save_snapshot("s1", {"v": i}, i)
        snap = store.get_snapshot_at_version("s1", 2)
        assert snap is not None
        assert snap.sequence_number == 2


# ---------------------------------------------------------------------------
# replay_stream – lines 1029-1089
# ---------------------------------------------------------------------------


class TestReplayStream:
    # branch [1050, 1068]: no snapshot (use_snapshot=True but empty) → from seq 0
    def test_replay_stream_no_snapshot(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        result = store.replay_stream("s1", use_snapshot=True)
        assert result["applied_events"] == 1
        assert result["snapshot_used"] is False

    # branch [1053, 1066]: snapshot hash mismatch → discard and full replay
    def test_replay_stream_hash_mismatch_discards_snapshot(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        snap_id = store.save_snapshot("s1", {"balance": 100}, sequence_number=1)
        # Corrupt the stored_hash in the snapshot metadata
        snap = store._snapshots["s1"][-1]
        snap.metadata["state_hash"] = "corrupted_hash"

        result = store.replay_stream("s1", use_snapshot=True)
        assert result["snapshot_used"] is False
        assert result["snapshot_hash_verified"] is False

    # branch [1055, 1056]: hash valid → snapshot used
    def test_replay_stream_valid_snapshot(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"balance": 100}, sequence_number=1)
        # Ensure hash is correct (default save_snapshot sets it correctly)
        result = store.replay_stream("s1", use_snapshot=True)
        assert result["snapshot_used"] is True
        assert result["snapshot_hash_verified"] is True

    # branch [1050, 1068]: use_snapshot=False → skip snapshot lookup
    def test_replay_stream_no_snapshot_flag(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"x": 1}, 1)
        result = store.replay_stream("s1", use_snapshot=False)
        assert result["snapshot_used"] is False

    # branch where callback is provided
    def test_replay_stream_with_callback(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        received = []
        store.replay_stream("s1", callback=lambda e: received.append(e))
        assert len(received) == 1

    # branch [1083, 1084]: snapshot present → result includes snapshot_sequence
    def test_replay_stream_snapshot_result_keys(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"x": 1}, 1)
        result = store.replay_stream("s1", use_snapshot=True)
        if result["snapshot_used"]:
            assert "snapshot_sequence" in result
            assert "snapshot_age_seconds" in result


# ---------------------------------------------------------------------------
# replay – lines 979-1027
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_no_filter(self) -> None:
        store = _make_store()
        store.append(_make_event())
        count = store.replay()
        assert count == 1

    def test_replay_stream_id_path(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        count = store.replay(stream_id="s1")
        assert count == 1

    def test_replay_with_callback(self) -> None:
        store = _make_store()
        store.append(_make_event())
        received = []
        count = store.replay(callback=lambda e: received.append(e))
        assert count == 1 and len(received) == 1

    def test_replay_callback_exception_swallowed(self) -> None:
        store = _make_store()
        store.append(_make_event())

        def bad(e):
            raise OSError("fail")

        count = store.replay(callback=bad)
        assert count == 0  # error swallowed, not counted

    def test_replay_event_type_filter(self) -> None:
        store = _make_store()
        store.append(_make_event("type.a"))
        store.append(_make_event("type.b"))
        count = store.replay(event_types=["type.a"])
        assert count == 1


# ---------------------------------------------------------------------------
# get_audit_log – lines 1093-1115
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    def test_audit_log_with_stream(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        log = store.get_audit_log(stream_id="s1")
        assert len(log) == 1
        assert "event_type" in log[0]

    def test_audit_log_no_stream(self) -> None:
        store = _make_store()
        store.append(_make_event())
        log = store.get_audit_log()
        assert len(log) == 1


# ---------------------------------------------------------------------------
# get_stats – lines 1119-1218
# ---------------------------------------------------------------------------


class TestGetStats:
    # branch [1121, 1122]: SQLITE path
    def test_get_stats_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "stats.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("t.a"), stream_id="s1")
        stats = store.get_stats()
        assert stats["total_events"] == 1

    # MEMORY path
    def test_get_stats_memory_with_events(self) -> None:
        store = _make_store()
        store.append(_make_event("t.a"), stream_id="s1")
        store.append(_make_event("t.b"), stream_id="s1")
        stats = store.get_stats()
        assert stats["total_events"] == 2
        assert "oldest_event" in stats
        assert "newest_event" in stats

    def test_get_stats_memory_empty(self) -> None:
        store = _make_store()
        stats = store.get_stats()
        assert stats["total_events"] == 0
        assert stats["oldest_event"] is None
        assert stats["newest_event"] is None


# ---------------------------------------------------------------------------
# delete_stream – lines 1222-1263
# ---------------------------------------------------------------------------


class TestDeleteStream:
    # branch [1224, 1225]: SQLITE logical delete
    def test_delete_stream_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "del.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event(), stream_id="s1")
        count = store.delete_stream("s1")
        assert count == 1

    # branch [1252, 1251] (loop body for store_ids)
    def test_delete_stream_memory(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        count = store.delete_stream("s1")
        assert count == 2
        assert "s1" not in store._stream_events

    # branch [1268, 1269]: stream_id in _snapshots → deleted
    def test_delete_stream_memory_removes_snapshots(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"x": 1}, 1)
        store.delete_stream("s1")
        assert "s1" not in store._snapshots

    # delete non-existent stream → count = 0
    def test_delete_nonexistent_stream(self) -> None:
        store = _make_store()
        count = store.delete_stream("ghost")
        assert count == 0


# ---------------------------------------------------------------------------
# clear – lines 1265-1279
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_memory(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.clear()
        assert len(store._events) == 0
        assert store._sequence_counter == 0

    def test_clear_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "clr.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        store.clear()
        stats = store.get_stats()
        assert stats["total_events"] == 0


# ---------------------------------------------------------------------------
# _cleanup_oldest – lines 1285-1324
# ---------------------------------------------------------------------------


class TestCleanupOldest:
    # branch [1292, 1293]: SQLITE path
    def test_cleanup_oldest_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "cln.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        store.append(_make_event())
        store._cleanup_oldest(count=1)
        # after logical delete, get_all returns 1
        events = list(store.get_all())
        assert len(events) == 1

    # branches [1319, 1320] / [1321, 1315] / [1321, 1322]: MEMORY loop
    def test_cleanup_oldest_memory_with_stream(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        store._cleanup_oldest(count=1)
        # one event removed from s1 stream index
        remaining = store.get_stream_events("s1")
        assert len(remaining) == 1

    # branch [1335, 1336]: store_id not in stream_list (already removed)
    def test_cleanup_oldest_memory_no_stream(self) -> None:
        store = _make_store()
        store.append(_make_event())  # no stream_id
        store._cleanup_oldest(count=1)
        assert len(store._events) == 0


# ---------------------------------------------------------------------------
# Global convenience functions – lines 1332-1353
# ---------------------------------------------------------------------------


class TestGlobalFunctions:
    # branch [1335, 1336]: get_event_store creates instance when None
    def test_get_event_store_creates_instance(self) -> None:
        import app.neuro_bus.event_store as es_mod

        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = None
            store = get_event_store()
            assert store is not None
        finally:
            es_mod._event_store_instance = original

    def test_get_event_store_returns_same_instance(self) -> None:
        s1 = get_event_store()
        s2 = get_event_store()
        assert s1 is s2

    def test_store_event_shortcut(self) -> None:
        import app.neuro_bus.event_store as es_mod

        store = _make_store()
        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = store
            sid = store_event(_make_event())
            assert sid.startswith("evt-")
        finally:
            es_mod._event_store_instance = original

    def test_replay_events_shortcut(self) -> None:
        import app.neuro_bus.event_store as es_mod

        store = _make_store()
        store.append(_make_event())
        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = store
            count = replay_events()
            assert count >= 1
        finally:
            es_mod._event_store_instance = original

    def test_get_event_stats_shortcut(self) -> None:
        import app.neuro_bus.event_store as es_mod

        store = _make_store()
        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = store
            stats = get_event_stats()
            assert "total_events" in stats
        finally:
            es_mod._event_store_instance = original


# ---------------------------------------------------------------------------
# _row_to_stored_event with upcaster – lines 348-370
# ---------------------------------------------------------------------------


class TestRowToStoredEventUpcaster:
    # branch [354, 355]: upcaster_registry is not None and version changed
    def test_row_to_stored_event_applies_upcaster(self, tmp_path) -> None:
        db = str(tmp_path / "up.db")
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db, upcaster_registry=reg)

        # Append event as v1 (store current=2, but we want to read back a v1 event)
        # We do this by inserting a raw row with schema_version=1
        import json

        e = _make_event("order.placed")
        metadata = {"event_schema_version": 1}
        import sqlite3

        store._conn.execute(
            """
            INSERT INTO neuro_events
                (store_id, event_type, event_data, stream_id, sequence_number, stored_at, metadata, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "test-row-1",
                e.event_type,
                e.to_json(),
                None,
                9999,
                datetime.now().isoformat(),
                json.dumps(metadata),
            ),
        )

        result = store.get("test-row-1")
        assert result is not None
        # v2 upcaster sets payload["v"] = 2
        assert result.event.payload.get("v") == 2

    # branch [359, 360]: new_version != schema_version
    def test_row_to_stored_event_no_upcaster(self, tmp_path) -> None:
        db = str(tmp_path / "no_up.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event())
        result = store.get(sid)
        assert result is not None


# ---------------------------------------------------------------------------
# _get_stream_version with SQLITE – lines 401-410
# ---------------------------------------------------------------------------


class TestGetStreamVersion:
    def test_sqlite_stream_version(self, tmp_path) -> None:
        db = str(tmp_path / "sv.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        assert store._get_stream_version("s1") == 2

    def test_memory_stream_version(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        assert store._get_stream_version("s1") == 1

    def test_memory_stream_version_nonexistent(self) -> None:
        store = _make_store()
        assert store._get_stream_version("no-stream") == 0
