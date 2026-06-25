"""
Behavior tests for app/neuro_bus/event_store.py

Covers the same source lines/branches as the original coverage suite, but every
test now asserts a concrete return value / state change / data-structure content
instead of merely "ran without raising" or "is not None".

ALL external I/O (SQLite, filesystem) uses tmp_path-backed real SQLite files or
in-memory dicts so that no global state is mutated and tests stay deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from app.neuro_bus.event_store import (
    EventStore,
    EventStoreMode,
    EventUpcaster,
    InvalidEventError,
    StoredEvent,
    UpcasterRegistry,
    WrongExpectedVersionError,
    get_event_stats,
    get_event_store,
    replay_events,
    store_event,
    validate_event_schema,
)
from app.neuro_bus.events.base import NeuroEvent

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
        # registry must still hold exactly the first registration
        assert len(reg._upcasters) == 1

    # branch [81, 85]: key not in _upcasters → proceed normally
    def test_register_success_records_key_and_current_version(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        assert ("order.placed", 1) in reg._upcasters
        # current version advanced to the upcaster's to_version
        assert reg._current_versions["order.placed"] == 2

    # branch [85, 86]: non-consecutive raises ValueError + leaves registry empty
    def test_register_non_consecutive_raises(self) -> None:
        reg = UpcasterRegistry()
        with pytest.raises(ValueError, match="必须连续升级"):
            reg.register(_BadUpNonConsecutive())
        assert reg._upcasters == {}
        assert reg._current_versions == {}

    # branch [85, 89]: consecutive ok, _current_versions tracks the max to_version
    def test_current_version_is_max_to_version(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        assert reg.get_current_version("order.placed") == 2
        reg.register(_UpV2toV3())
        assert reg.get_current_version("order.placed") == 3
        # unknown event type defaults to 1
        assert reg.get_current_version("never.seen") == 1

    # branches [98, 99] / [98, 106]: get_chain loop enters body vs exits
    def test_get_chain_two_steps_returns_ordered_upcasters(self) -> None:
        reg = UpcasterRegistry()
        u1, u2 = _UpV1toV2(), _UpV2toV3()
        reg.register(u1)
        reg.register(u2)
        chain = reg.get_chain("order.placed", 1, 3)
        assert chain == [u1, u2]

    # branch [98, 106]: from_version already == to_version → empty chain (loop never enters)
    def test_get_chain_no_steps_returns_empty(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        assert reg.get_chain("order.placed", 2, 2) == []

    # branch [100, 101]: upcaster missing → chain break raises with diagnostic
    def test_get_chain_missing_raises(self) -> None:
        reg = UpcasterRegistry()
        with pytest.raises(ValueError, match="链断裂.*from_version=1"):
            reg.get_chain("no.such", 1, 3)

    # branch [100, 104]: upcaster found, append and advance
    def test_get_chain_single_step(self) -> None:
        reg = UpcasterRegistry()
        u1 = _UpV1toV2()
        reg.register(u1)
        chain = reg.get_chain("order.placed", 1, 2)
        assert chain == [u1]

    # branches [118, 119]: from_version >= target → return payload unchanged (identity)
    def test_upcast_already_current_returns_same_payload(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        original = {"x": 1}
        result, ver = reg.upcast("order.placed", original, from_version=2)
        assert ver == 2
        # payload object returned unchanged (no copy, no mutation)
        assert result is original
        assert result == {"x": 1}

    # branch [118, 120]: from_version < target → run chain, payload transformed
    def test_upcast_runs_chain_transforms_payload(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        result, ver = reg.upcast("order.placed", {"x": 1}, from_version=1)
        assert ver == 2
        assert result == {"x": 1, "v": 2}

    # branches [122, 123] / [122, 124]: full multi-step chain runs in order
    def test_upcast_multi_step_applies_both_upcasters(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        reg.register(_UpV2toV3())
        result, ver = reg.upcast("order.placed", {"x": 1}, from_version=1)
        assert ver == 3
        # v1->v2 sets v=2, then v2->v3 overwrites v=3
        assert result == {"x": 1, "v": 3}

    # validate_chains: complete chain OK (no raise) – assert it returns None and is idempotent
    def test_validate_chains_ok_is_noop(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        reg.register(_UpV2toV3())
        assert reg.validate_chains() is None
        assert reg.validate_chains() is None  # idempotent

    def test_validate_chains_broken_raises(self) -> None:
        reg = UpcasterRegistry()
        # current_version says 3 but no upcaster chain from 1 exists
        reg._current_versions["ghost.event"] = 3
        with pytest.raises(ValueError, match="链断裂.*ghost.event"):
            reg.validate_chains()


# ---------------------------------------------------------------------------
# validate_event_schema – lines 142-158
# ---------------------------------------------------------------------------


class TestValidateEventSchema:
    # branch [152, 153]: empty event_type raises with offending value
    def test_empty_event_type_raises(self) -> None:
        e = _make_event()
        e.event_type = ""
        with pytest.raises(InvalidEventError, match="event_type 必须是非空字符串"):
            validate_event_schema(e)

    # branch [152]: non-str event_type also raises
    def test_non_str_event_type_raises(self) -> None:
        e = _make_event()
        e.event_type = 123  # type: ignore[assignment]
        with pytest.raises(InvalidEventError, match="event_type"):
            validate_event_schema(e)

    # branch [154, 155]: non-dict payload raises with type name
    def test_non_dict_payload_raises(self) -> None:
        e = _make_event()
        e.payload = "not-a-dict"  # type: ignore[assignment]
        with pytest.raises(InvalidEventError, match="payload 必须是 dict.*str"):
            validate_event_schema(e)

    # branch [156, 157]: empty event_id raises
    def test_empty_event_id_raises(self) -> None:
        e = _make_event()
        e.metadata.event_id = ""
        with pytest.raises(InvalidEventError, match="event_id 不能为空"):
            validate_event_schema(e)

    # all-pass path returns exactly True
    def test_valid_event_returns_true(self) -> None:
        e = _make_event()
        assert validate_event_schema(e) is True


# ---------------------------------------------------------------------------
# EventStore construction & SQLite init
# ---------------------------------------------------------------------------


class TestEventStoreMemoryAppend:
    def test_append_returns_unique_store_ids(self) -> None:
        store = _make_store()
        sid1 = store.append(_make_event())
        sid2 = store.append(_make_event())
        assert sid1.startswith("evt-")
        assert sid2.startswith("evt-")
        assert sid1 != sid2
        # both events recorded with monotonic sequence numbers
        assert store._events[sid1].sequence_number == 1
        assert store._events[sid2].sequence_number == 2

    # branches [254, 257]: JSON_FILE mode warns and degrades to MEMORY behavior
    def test_json_file_mode_warns_and_degrades_to_memory(self) -> None:
        with patch("app.neuro_bus.event_store.logger") as mock_log:
            store = EventStore(mode=EventStoreMode.JSON_FILE)
        # a warning about JSON_FILE not being implemented was logged
        assert mock_log.warning.called
        warning_text = mock_log.warning.call_args[0][0]
        assert "JSON_FILE" in warning_text
        # mode flag preserved but storage actually behaves like MEMORY (no sqlite conn)
        assert store._mode == EventStoreMode.JSON_FILE
        assert store._conn is None
        sid = store.append(_make_event())
        assert store._events[sid].store_id == sid

    # branches [260, 261]: upcaster_registry not None → validate_chains called at init
    def test_upcaster_registry_validated_at_init(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        with patch.object(reg, "validate_chains", wraps=reg.validate_chains) as spy:
            store = EventStore(upcaster_registry=reg)
        spy.assert_called_once()
        assert store._upcaster_registry is reg

    # init with a broken registry surfaces the validation error
    def test_init_with_broken_registry_raises(self) -> None:
        reg = UpcasterRegistry()
        reg._current_versions["ghost.event"] = 2  # no upcaster chain
        with pytest.raises(ValueError, match="链断裂"):
            EventStore(upcaster_registry=reg)

    # branch [272, 273]: SQLITE missing path raises ValueError
    def test_sqlite_missing_path_raises(self) -> None:
        with pytest.raises(ValueError, match="storage_path"):
            EventStore(mode=EventStoreMode.SQLITE, storage_path=None)

    # SQLite append round-trips the event through the DB
    def test_sqlite_append_roundtrips(self, tmp_path) -> None:
        db = str(tmp_path / "ev.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        e = _make_event("acct.opened", {"balance": 50})
        sid = store.append(e, stream_id="s1")
        assert sid.startswith("evt-")
        fetched = store.get(sid)
        assert fetched is not None
        assert fetched.event.event_type == "acct.opened"
        assert fetched.event.payload == {"balance": 50}
        assert fetched.stream_id == "s1"
        store.clear()

    # branch [339, 340]: sequence counter restored from existing max_seq on reopen
    def test_sqlite_seq_counter_restored_on_reopen(self, tmp_path) -> None:
        db = str(tmp_path / "seq.db")
        store1 = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store1.append(_make_event())
        store1.append(_make_event())
        assert store1._sequence_counter == 2

        store2 = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store2._sequence_counter == 2
        # next append continues from restored counter
        store2.append(_make_event())
        assert store2._sequence_counter == 3

    # branch [339, 342]: empty db → counter stays at 0
    def test_sqlite_seq_counter_zero_on_empty(self, tmp_path) -> None:
        db = str(tmp_path / "empty.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store._sequence_counter == 0


# ---------------------------------------------------------------------------
# _apply_upcasters_to_stored – lines 372-398
# ---------------------------------------------------------------------------


class TestApplyUpcastersToStored:
    # branch [374, 376]: no registry → returns the exact same object
    def test_no_registry_returns_identity(self) -> None:
        store = _make_store()
        s = _stored(_make_event())
        assert store._apply_upcasters_to_stored(s) is s

    # branch [380, 381]: new_version == schema_version → return same object unchanged
    def test_already_current_returns_identity(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = _make_store(upcaster_registry=reg)
        s = _stored(_make_event("order.placed"))
        s.metadata["event_schema_version"] = 2  # already current
        result = store._apply_upcasters_to_stored(s)
        assert result is s
        assert "v" not in result.event.payload  # untouched

    # branch [380, 383]: version changed → new StoredEvent with upgraded payload
    def test_upcast_creates_new_stored_with_upgraded_payload(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = _make_store(upcaster_registry=reg)
        s = _stored(_make_event("order.placed", {"x": 1}))
        s.metadata["event_schema_version"] = 1
        result = store._apply_upcasters_to_stored(s)
        assert result is not s
        assert result.metadata["event_schema_version"] == 2
        assert result.event.payload == {"x": 1, "v": 2}
        # original object left intact (pure function)
        assert s.metadata["event_schema_version"] == 1
        assert "v" not in s.event.payload
        # identity fields preserved on the copy
        assert result.store_id == s.store_id
        assert result.sequence_number == s.sequence_number


# ---------------------------------------------------------------------------
# _check_expected_version – lines 412-429
# ---------------------------------------------------------------------------


class TestCheckExpectedVersion:
    # branch [403, 404]: expected_version is None → returns None, no raise
    def test_none_expected_version_returns_none(self) -> None:
        store = _make_store()
        assert store._check_expected_version("s1", None) is None

    # branch [403, 410]: expected_version == -2 → returns None even if stream exists
    def test_minus2_ignores_existing_stream(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        assert store._check_expected_version("s1", -2) is None

    # branch [414, 418]: expected_version == -1 and stream empty → OK
    def test_minus1_create_empty_stream_ok(self) -> None:
        store = _make_store()
        assert store._check_expected_version("new-stream", -1) is None

    # branch [420, 422]: expected_version == -1 but stream exists → raise w/ actual=1
    def test_minus1_stream_exists_raises_with_actual(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        with pytest.raises(WrongExpectedVersionError) as exc:
            store._check_expected_version("s1", -1)
        assert exc.value.expected == -1
        assert exc.value.actual == 1
        assert exc.value.stream_id == "s1"

    # branch [424]: expected_version >= 0 and matches actual → OK
    def test_exact_version_match_ok(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        assert store._check_expected_version("s1", 1) is None

    # branch [426, 427]: version mismatch raises with both values
    def test_exact_version_mismatch_raises_with_values(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        with pytest.raises(WrongExpectedVersionError) as exc:
            store._check_expected_version("s1", 5)
        assert exc.value.expected == 5
        assert exc.value.actual == 1

    # branch [424, 429]: unexpected negative value raises ValueError
    def test_invalid_expected_version_raises_valueerror(self) -> None:
        store = _make_store()
        with pytest.raises(ValueError, match="不支持的 expected_version 值: -99"):
            store._check_expected_version("s1", -99)

    # branch [422, -412]: expected_version == -1 and stream_id is None → actual=0 → OK
    def test_minus1_none_stream_treated_as_empty(self) -> None:
        store = _make_store()
        assert store._check_expected_version(None, -1) is None


# ---------------------------------------------------------------------------
# append – lines 433-508
# ---------------------------------------------------------------------------


class TestAppendBranches:
    # branch [468, 469]: upcaster_registry present → records current schema version
    def test_append_with_upcaster_records_current_schema_version(self) -> None:
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())  # current version of order.placed = 2
        store = _make_store(upcaster_registry=reg)
        sid = store.append(_make_event("order.placed"))
        assert store._events[sid].metadata["event_schema_version"] == 2

    # without an upcaster registry no schema_version is recorded
    def test_append_without_upcaster_has_empty_metadata(self) -> None:
        store = _make_store()
        sid = store.append(_make_event())
        assert store._events[sid].metadata == {}

    # branch [482, 483]: SQLITE mode → event persisted and retrievable
    def test_append_sqlite_mode_persists(self, tmp_path) -> None:
        db = str(tmp_path / "a.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event("x.y"))
        assert sid.startswith("evt-")
        assert store.get_stats()["total_events"] == 1
        assert store.get(sid).event.event_type == "x.y"

    # branch [519, 520]: SQLITE capacity → cleanup logically deletes a batch of oldest.
    # _cleanup_oldest() runs with its default count=1000, so when the 3rd append hits
    # capacity (max_events=2) it sweeps BOTH pre-existing rows, leaving only the new one.
    def test_append_sqlite_capacity_triggers_batch_cleanup(self, tmp_path) -> None:
        db = str(tmp_path / "cap.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db, max_events=2)
        store.append(_make_event("e1"))
        store.append(_make_event("e2"))
        store.append(_make_event("e3"))  # capacity reached → batch cleanup before insert
        types = [e.event.event_type for e in store.get_all()]
        # cleanup default count (1000) swept e1+e2; only the just-inserted e3 remains
        assert types == ["e3"]
        assert store.get_stats()["total_events"] == 1

    # branches [494, 497]: stream_id present → index created and points to store_id
    def test_append_with_stream_id_indexes_event(self) -> None:
        store = _make_store()
        sid = store.append(_make_event(), stream_id="stream-A")
        assert store._stream_events["stream-A"] == [sid]

    # MEMORY capacity cleanup: _cleanup_oldest() default count=1000 sweeps all existing
    # events when capacity is hit, so the 3rd append (max_events=2) leaves only e3.
    def test_append_beyond_max_events_batch_evicts_oldest(self) -> None:
        store = _make_store(max_events=2)
        sid1 = store.append(_make_event("e1"))
        sid2 = store.append(_make_event("e2"))
        store.append(_make_event("e3"))  # capacity reached → cleanup before insert
        # batch cleanup removed both pre-existing events; only e3 survives
        assert sid1 not in store._events
        assert sid2 not in store._events
        types = [e.event.event_type for e in store._events.values()]
        assert types == ["e3"]


# ---------------------------------------------------------------------------
# append callbacks – lines 501-506
# ---------------------------------------------------------------------------


class TestAppendCallbacks:
    def test_callback_receives_stored_event(self) -> None:
        store = _make_store()
        received: list[StoredEvent] = []
        store.on_append(received.append)
        sid = store.append(_make_event("cb.event"))
        assert len(received) == 1
        assert received[0].store_id == sid
        assert received[0].event.event_type == "cb.event"

    # recoverable callback exception is swallowed but the event is still stored
    def test_callback_exception_swallowed_event_still_stored(self) -> None:
        store = _make_store()

        def bad_callback(s: StoredEvent) -> None:
            raise OSError("simulated transient")

        store.on_append(bad_callback)
        sid = store.append(_make_event())  # must not raise
        assert sid in store._events


# ---------------------------------------------------------------------------
# append_many – lines 542-631
# ---------------------------------------------------------------------------


class TestAppendMany:
    # branch [556, 557]: empty list returns [] and stores nothing
    def test_empty_list_returns_empty_and_stores_nothing(self) -> None:
        store = _make_store()
        assert store.append_many([]) == []
        assert store._events == {}

    # validation runs over every event before any insert
    def test_append_many_invalid_event_raises_before_storing(self) -> None:
        store = _make_store()
        bad = _make_event()
        bad.event_type = ""
        with pytest.raises(InvalidEventError):
            store.append_many([_make_event(), bad])

    # branch [564, 565]: SQLITE atomic transaction stores all events under one stream
    def test_append_many_sqlite_atomic(self, tmp_path) -> None:
        db = str(tmp_path / "many.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        ids = store.append_many([_make_event("a"), _make_event("b")], stream_id="s1")
        assert len(ids) == 2
        stream = store.get_stream_events("s1")
        assert [e.event.event_type for e in stream] == ["a", "b"]
        assert [e.sequence_number for e in stream] == [1, 2]

    # branch [571, 572]: upcaster present in SQLITE many path records schema version
    def test_append_many_sqlite_records_schema_version(self, tmp_path) -> None:
        db = str(tmp_path / "many2.db")
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db, upcaster_registry=reg)
        ids = store.append_many([_make_event("order.placed")])
        assert len(ids) == 1
        stored = store.get(ids[0])
        assert stored.metadata["event_schema_version"] == 2

    # branch [571, 624]: SQLITE many callback fires once per event with correct ids
    def test_append_many_sqlite_callback_per_event(self, tmp_path) -> None:
        db = str(tmp_path / "many3.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        received: list[str] = []
        store.on_append(lambda s: received.append(s.store_id))
        ids = store.append_many([_make_event(), _make_event()])
        assert received == ids

    # branch [618, 619]: callback raises in SQLITE many path → swallowed, events committed
    def test_append_many_sqlite_callback_exception_swallowed(self, tmp_path) -> None:
        db = str(tmp_path / "many4.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.on_append(lambda s: (_ for _ in ()).throw(OSError("boom")))
        ids = store.append_many([_make_event("survived")])  # must not raise
        # event committed despite the callback blowing up
        assert store.get(ids[0]).event.event_type == "survived"

    # branch [577, 582]: MEMORY path - first event uses expected_version, succeeds
    def test_append_many_memory_with_expected_version(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")  # version now 1
        ids = store.append_many([_make_event(), _make_event()], stream_id="s1", expected_version=1)
        assert len(ids) == 2
        assert store._get_stream_version("s1") == 3

    # MEMORY path with wrong expected_version raises before storing extra events
    def test_append_many_memory_wrong_expected_version_raises(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")  # version 1
        with pytest.raises(WrongExpectedVersionError):
            store.append_many([_make_event()], stream_id="s1", expected_version=99)


# ---------------------------------------------------------------------------
# append_with_retry – lines 633-686
# ---------------------------------------------------------------------------


class TestAppendWithRetry:
    # branch [658, 660]: build_events returns empty → returns [] and stores nothing
    def test_build_events_empty_returns_empty(self) -> None:
        store = _make_store()
        result = store.append_with_retry("s1", build_events=lambda evs: [])
        assert result == []
        assert store._get_stream_version("s1") == 0

    # build_events receives the current (initially empty) stream state
    def test_build_events_receives_current_stream(self) -> None:
        store = _make_store()
        store.append(_make_event("seed"), stream_id="s1")
        seen_lengths: list[int] = []

        def build(evs):
            seen_lengths.append(len(evs))
            return [_make_event("new")]

        store.append_with_retry("s1", build_events=build)
        # on first (only) attempt it saw the one pre-existing event
        assert seen_lengths == [1]

    # branch [658, 686]: retries exhausted → reraises the conflict
    def test_retries_exhausted_raises(self) -> None:
        store = _make_store()

        def always_conflict(events, stream_id=None, expected_version=None):
            raise WrongExpectedVersionError(stream_id or "s1", expected_version or 0, 99)

        store.append_many = always_conflict  # type: ignore[method-assign]

        with pytest.raises(WrongExpectedVersionError) as exc:
            store.append_with_retry(
                "s1",
                build_events=lambda evs: [_make_event()],
                max_retries=0,
                base_delay=0,
            )
        assert exc.value.actual == 99

    # branch [665, 666]: success on first attempt returns the new store ids
    def test_success_on_first_attempt(self) -> None:
        store = _make_store()
        result = store.append_with_retry(
            "s1",
            build_events=lambda evs: [_make_event("only")],
        )
        assert len(result) == 1
        assert store.get_stream_events("s1")[0].event.event_type == "only"

    # branch [674, 658]: conflict then retry → second attempt succeeds, sleep backoff used
    def test_retry_on_conflict_then_succeeds(self) -> None:
        store = _make_store()
        original_append = store.append_many
        call_count = [0]

        def patched_append(events, stream_id=None, expected_version=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise WrongExpectedVersionError("s1", 0, 1)
            return original_append(events, stream_id=stream_id, expected_version=None)

        store.append_many = patched_append  # type: ignore[method-assign]

        with patch("app.neuro_bus.event_store.time.sleep") as sleep_mock:
            result = store.append_with_retry(
                "s1", build_events=lambda evs: [_make_event()], max_retries=2, base_delay=0.5
            )
        assert len(result) == 1
        assert call_count[0] == 2  # one conflict, one success
        # backoff sleep called once with base_delay * 2**0
        sleep_mock.assert_called_once_with(0.5)


# ---------------------------------------------------------------------------
# get – lines 690-704
# ---------------------------------------------------------------------------


class TestGet:
    # branch [698, 700]: SQLITE row found → returns the stored event with matching id
    def test_get_sqlite_found(self, tmp_path) -> None:
        db = str(tmp_path / "g.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event("found.me", {"n": 7}))
        result = store.get(sid)
        assert result.store_id == sid
        assert result.event.payload == {"n": 7}

    # branch [698, 699]: SQLITE missing id → None
    def test_get_sqlite_missing_returns_none(self, tmp_path) -> None:
        db = str(tmp_path / "g2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store.get("no-such-id") is None

    # MEMORY missing → None
    def test_get_memory_missing_returns_none(self) -> None:
        store = _make_store()
        assert store.get("not-here") is None

    # MEMORY found → returns the same StoredEvent object (no upcaster)
    def test_get_memory_found_returns_stored(self) -> None:
        store = _make_store()
        sid = store.append(_make_event("m.found"))
        result = store.get(sid)
        assert result.store_id == sid
        assert result.event.event_type == "m.found"


# ---------------------------------------------------------------------------
# get_all – lines 706-751
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_get_all_sqlite_orders_by_sequence(self, tmp_path) -> None:
        db = str(tmp_path / "all.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        events = list(store.get_all())
        assert [e.event.event_type for e in events] == ["a", "b"]

    def test_get_all_sqlite_start_time_includes_past_boundary(self, tmp_path) -> None:
        db = str(tmp_path / "all2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("x"))
        included = list(store.get_all(start_time=datetime(2000, 1, 1)))
        excluded = list(store.get_all(start_time=datetime(2099, 1, 1)))
        assert len(included) == 1
        assert excluded == []

    def test_get_all_sqlite_end_time_filters(self, tmp_path) -> None:
        db = str(tmp_path / "all3.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("x"))
        included = list(store.get_all(end_time=datetime(2099, 1, 1)))
        excluded = list(store.get_all(end_time=datetime(2000, 1, 1)))
        assert len(included) == 1
        assert excluded == []

    def test_get_all_sqlite_event_type_filter(self, tmp_path) -> None:
        db = str(tmp_path / "all4.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("type.a"))
        store.append(_make_event("type.b"))
        events = list(store.get_all(event_type="type.a"))
        assert [e.event.event_type for e in events] == ["type.a"]

    # branch [735]: MEMORY start_time within range → kept
    def test_get_all_memory_start_time_keeps_in_range(self) -> None:
        store = _make_store()
        store.append(_make_event("kept"))
        events = list(store.get_all(start_time=datetime(2000, 1, 1)))
        assert [e.event.event_type for e in events] == ["kept"]

    # branch [735, 736]: MEMORY future start_time → skip all
    def test_get_all_memory_future_start_time_skips(self) -> None:
        store = _make_store()
        store.append(_make_event())
        assert list(store.get_all(start_time=datetime(2099, 1, 1))) == []

    # branch [744, 745]: MEMORY event_type filter keeps only matching, in seq order
    def test_get_all_memory_event_type_filter(self) -> None:
        store = _make_store()
        store.append(_make_event("type.a"))
        store.append(_make_event("type.b"))
        store.append(_make_event("type.a"))
        events = list(store.get_all(event_type="type.a"))
        assert [e.event.event_type for e in events] == ["type.a", "type.a"]
        assert [e.sequence_number for e in events] == [1, 3]


# ---------------------------------------------------------------------------
# get_stream_events – lines 753-783
# ---------------------------------------------------------------------------


class TestGetStreamEvents:
    def test_memory_returns_events_sorted_by_sequence(self) -> None:
        store = _make_store()
        store.append(_make_event("first"), stream_id="s1")
        store.append(_make_event("second"), stream_id="s1")
        events = store.get_stream_events("s1")
        assert [e.event.event_type for e in events] == ["first", "second"]
        assert events[0].sequence_number < events[1].sequence_number

    def test_memory_from_sequence_excludes_earlier(self) -> None:
        store = _make_store()
        store.append(_make_event("first"), stream_id="s1")
        store.append(_make_event("second"), stream_id="s1")
        second_seq = store.get_stream_events("s1")[1].sequence_number
        filtered = store.get_stream_events("s1", from_sequence=second_seq)
        assert [e.event.event_type for e in filtered] == ["second"]

    def test_memory_unknown_stream_returns_empty(self) -> None:
        store = _make_store()
        assert store.get_stream_events("nope") == []

    # branch [763, 764]: SQLITE path returns ordered events
    def test_sqlite_stream_events_ordered(self, tmp_path) -> None:
        db = str(tmp_path / "se.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("a"), stream_id="s1")
        store.append(_make_event("b"), stream_id="s1")
        events = store.get_stream_events("s1")
        assert [e.event.event_type for e in events] == ["a", "b"]


# ---------------------------------------------------------------------------
# get_latest – lines 785-801
# ---------------------------------------------------------------------------


class TestGetLatest:
    # branch [787, 788]: SQLITE returns newest first, respecting limit
    def test_sqlite_get_latest_newest_first(self, tmp_path) -> None:
        db = str(tmp_path / "lat.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("old"))
        store.append(_make_event("new"))
        events = store.get_latest(limit=1)
        assert [e.event.event_type for e in events] == ["new"]

    def test_memory_get_latest_newest_first(self) -> None:
        store = _make_store()
        store.append(_make_event("old"))
        store.append(_make_event("new"))
        events = store.get_latest(limit=1)
        assert [e.event.event_type for e in events] == ["new"]


# ---------------------------------------------------------------------------
# save_snapshot / get_snapshot – lines 812-965
# ---------------------------------------------------------------------------


class TestSnapshotBranches:
    # branch [836, 837]: SQLITE save_snapshot persists state and metadata
    def test_save_and_get_snapshot_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "snap.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        snap_id = store.save_snapshot("s1", {"balance": 100}, sequence_number=5)
        assert snap_id.startswith("snap-")
        snap = store.get_snapshot("s1")
        assert snap.stream_id == "s1"
        assert snap.state == {"balance": 100}
        assert snap.sequence_number == 5
        # state_hash recorded for integrity verification
        assert snap.metadata["state_hash"] == EventStore._compute_state_hash({"balance": 100})

    # branch [879, 880]: MEMORY save trims to max_snapshots_per_stream, keeping newest
    def test_save_snapshot_memory_trims_to_newest(self) -> None:
        store = _make_store(max_snapshots_per_stream=2)
        store.save_snapshot("s1", {"a": 1}, 1)
        store.save_snapshot("s1", {"a": 2}, 2)
        store.save_snapshot("s1", {"a": 3}, 3)
        history = store.get_snapshot_history("s1")
        # only the 2 newest kept, newest-first
        assert [s.sequence_number for s in history] == [3, 2]

    # branch [918, 919]: SQLITE get_snapshot empty → None
    def test_get_snapshot_sqlite_none(self, tmp_path) -> None:
        db = str(tmp_path / "snap2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        assert store.get_snapshot("no-such") is None

    # branch [918, 920]: MEMORY empty list → None
    def test_get_snapshot_memory_none(self) -> None:
        store = _make_store()
        assert store.get_snapshot("s1") is None

    # branch [918, 920]: MEMORY non-empty → returns the latest snapshot
    def test_get_snapshot_memory_returns_latest(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 1)
        store.save_snapshot("s1", {"v": 2}, 2)
        snap = store.get_snapshot("s1")
        assert snap.state == {"v": 2}
        assert snap.sequence_number == 2

    # branch [929, 930]: SQLITE history newest-first
    def test_get_snapshot_history_sqlite(self, tmp_path) -> None:
        db = str(tmp_path / "hist.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.save_snapshot("s1", {"v": 1}, 1)
        store.save_snapshot("s1", {"v": 2}, 2)
        history = store.get_snapshot_history("s1")
        assert [s.sequence_number for s in history] == [2, 1]

    # branch [929, 941]: MEMORY history newest-first
    def test_get_snapshot_history_memory(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 1)
        store.save_snapshot("s1", {"v": 2}, 2)
        history = store.get_snapshot_history("s1")
        assert [s.sequence_number for s in history] == [2, 1]

    # branch [946, 947]: SQLITE get_snapshot_at_version exact match
    def test_get_snapshot_at_version_sqlite_match(self, tmp_path) -> None:
        db = str(tmp_path / "av.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.save_snapshot("s1", {"v": 1}, sequence_number=10)
        snap = store.get_snapshot_at_version("s1", 10)
        assert snap.sequence_number == 10
        assert snap.state == {"v": 1}

    def test_get_snapshot_at_version_sqlite_no_match(self, tmp_path) -> None:
        db = str(tmp_path / "av2.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.save_snapshot("s1", {"v": 1}, sequence_number=10)
        assert store.get_snapshot_at_version("s1", 99) is None

    # branch [957, 958]: MEMORY find by version
    def test_get_snapshot_at_version_memory_found(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 10)
        snap = store.get_snapshot_at_version("s1", 10)
        assert snap.sequence_number == 10

    # branch [957, 959]: MEMORY not found → None
    def test_get_snapshot_at_version_memory_not_found(self) -> None:
        store = _make_store()
        store.save_snapshot("s1", {"v": 1}, 10)
        assert store.get_snapshot_at_version("s1", 99) is None

    # branch [962, 963]: MEMORY reversed loop picks the right version among many
    def test_get_snapshot_at_version_memory_picks_correct(self) -> None:
        store = _make_store(max_snapshots_per_stream=5)
        for i in range(1, 4):
            store.save_snapshot("s1", {"v": i}, i)
        snap = store.get_snapshot_at_version("s1", 2)
        assert snap.sequence_number == 2
        assert snap.state == {"v": 2}


# ---------------------------------------------------------------------------
# replay_stream – lines 1029-1089
# ---------------------------------------------------------------------------


class TestReplayStream:
    # branch [1050, 1068]: no snapshot exists → replay from seq 0, snapshot_used False
    def test_replay_stream_no_snapshot(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        result = store.replay_stream("s1", use_snapshot=True)
        assert result["applied_events"] == 2
        assert result["snapshot_used"] is False
        assert result["snapshot_hash_verified"] is True
        assert "snapshot_sequence" not in result

    # branch [1053, 1066]: snapshot hash mismatch → discard snapshot, full replay
    def test_replay_stream_hash_mismatch_discards_snapshot(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"balance": 100}, sequence_number=1)
        # Corrupt the stored hash → verification must fail
        store._snapshots["s1"][-1].metadata["state_hash"] = "corrupted_hash"
        result = store.replay_stream("s1", use_snapshot=True)
        assert result["snapshot_used"] is False
        assert result["snapshot_hash_verified"] is False
        # falls back to full replay from sequence 0
        assert result["applied_events"] == 1

    # branch [1055, 1056]: valid hash → snapshot used, replay only events after it
    def test_replay_stream_valid_snapshot_skips_replayed_events(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")  # seq 1
        store.append(_make_event(), stream_id="s1")  # seq 2
        store.save_snapshot("s1", {"balance": 100}, sequence_number=1)
        result = store.replay_stream("s1", use_snapshot=True)
        assert result["snapshot_used"] is True
        assert result["snapshot_hash_verified"] is True
        # only the event after seq 1 (i.e. seq 2) is applied
        assert result["applied_events"] == 1
        assert result["snapshot_sequence"] == 1
        assert isinstance(result["snapshot_age_seconds"], float)

    # branch [1050, 1068]: use_snapshot=False → snapshot ignored, full replay
    def test_replay_stream_flag_off_ignores_snapshot(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"x": 1}, 1)
        result = store.replay_stream("s1", use_snapshot=False)
        assert result["snapshot_used"] is False
        assert result["applied_events"] == 1

    # callback invoked once per replayed event with the underlying NeuroEvent
    def test_replay_stream_callback_receives_events(self) -> None:
        store = _make_store()
        store.append(_make_event("ev.a"), stream_id="s1")
        store.append(_make_event("ev.b"), stream_id="s1")
        received: list[str] = []
        store.replay_stream("s1", callback=lambda e: received.append(e.event_type))
        assert received == ["ev.a", "ev.b"]


# ---------------------------------------------------------------------------
# replay – lines 979-1027
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_counts_all_events(self) -> None:
        store = _make_store()
        store.append(_make_event())
        store.append(_make_event())
        assert store.replay() == 2

    def test_replay_stream_id_path_only_counts_stream(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s2")
        assert store.replay(stream_id="s1") == 1

    def test_replay_callback_invoked_per_event(self) -> None:
        store = _make_store()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        received: list[str] = []
        count = store.replay(callback=lambda e: received.append(e.event_type))
        assert count == 2
        assert received == ["a", "b"]

    # callback exception is swallowed and that event is NOT counted
    def test_replay_callback_exception_not_counted(self) -> None:
        store = _make_store()
        store.append(_make_event())
        store.append(_make_event())

        def bad(e):
            raise OSError("fail")

        assert store.replay(callback=bad) == 0

    def test_replay_event_type_filter(self) -> None:
        store = _make_store()
        store.append(_make_event("type.a"))
        store.append(_make_event("type.b"))
        received: list[str] = []
        count = store.replay(
            event_types=["type.a"], callback=lambda e: received.append(e.event_type)
        )
        assert count == 1
        assert received == ["type.a"]


# ---------------------------------------------------------------------------
# get_audit_log – lines 1093-1115
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    def test_audit_log_with_stream_includes_event_fields(self) -> None:
        store = _make_store()
        e = _make_event("audit.evt", {"amount": 5, "ccy": "USD"})
        store.append(e, stream_id="s1")
        log = store.get_audit_log(stream_id="s1")
        assert len(log) == 1
        entry = log[0]
        assert entry["event_type"] == "audit.evt"
        assert entry["event_id"] == e.metadata.event_id
        assert sorted(entry["payload_keys"]) == ["amount", "ccy"]

    def test_audit_log_no_stream_returns_all(self) -> None:
        store = _make_store()
        store.append(_make_event("a"))
        store.append(_make_event("b"))
        log = store.get_audit_log()
        assert [entry["event_type"] for entry in log] == ["a", "b"]


# ---------------------------------------------------------------------------
# get_stats – lines 1119-1218
# ---------------------------------------------------------------------------


class TestGetStats:
    # branch [1121, 1122]: SQLITE path aggregates by type and stream
    def test_get_stats_sqlite_aggregates(self, tmp_path) -> None:
        db = str(tmp_path / "stats.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("t.a"), stream_id="s1")
        store.append(_make_event("t.a"), stream_id="s1")
        store.append(_make_event("t.b"), stream_id="s2")
        stats = store.get_stats()
        assert stats["total_events"] == 3
        assert stats["by_event_type"] == {"t.a": 2, "t.b": 1}
        assert stats["by_stream"] == {"s1": 2, "s2": 1}
        assert stats["streams"] == 2

    # MEMORY path with events
    def test_get_stats_memory_with_events(self) -> None:
        store = _make_store()
        store.append(_make_event("t.a"), stream_id="s1")
        store.append(_make_event("t.b"), stream_id="s1")
        stats = store.get_stats()
        assert stats["total_events"] == 2
        assert stats["by_event_type"] == {"t.a": 1, "t.b": 1}
        assert stats["by_stream"] == {"s1": 2}
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None

    def test_get_stats_memory_empty(self) -> None:
        store = _make_store()
        stats = store.get_stats()
        assert stats["total_events"] == 0
        assert stats["by_event_type"] == {}
        assert stats["by_stream"] == {}
        assert stats["oldest_event"] is None
        assert stats["newest_event"] is None


# ---------------------------------------------------------------------------
# delete_stream – lines 1222-1263
# ---------------------------------------------------------------------------


class TestDeleteStream:
    # branch [1224, 1225]: SQLITE logical delete removes from active queries
    def test_delete_stream_sqlite_logical(self, tmp_path) -> None:
        db = str(tmp_path / "del.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        assert store.delete_stream("s1") == 2
        # logically deleted: no longer visible
        assert store.get_stream_events("s1") == []
        assert store.get_stats()["total_events"] == 0

    # MEMORY physical delete drops the events and the stream index
    def test_delete_stream_memory_physical(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        assert store.delete_stream("s1") == 2
        assert "s1" not in store._stream_events
        assert store._events == {}

    # branch [1259, 1260]: stream snapshots removed alongside events
    def test_delete_stream_memory_removes_snapshots(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"x": 1}, 1)
        store.delete_stream("s1")
        assert "s1" not in store._snapshots
        assert store.get_snapshot("s1") is None

    def test_delete_nonexistent_stream_returns_zero(self) -> None:
        store = _make_store()
        assert store.delete_stream("ghost") == 0


# ---------------------------------------------------------------------------
# clear – lines 1265-1279
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_memory_resets_state(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        store.save_snapshot("s1", {"x": 1}, 1)
        store.clear()
        assert store._events == {}
        assert store._stream_events == {}
        assert store._snapshots == {}
        assert store._sequence_counter == 0

    def test_clear_sqlite_empties_db(self, tmp_path) -> None:
        db = str(tmp_path / "clr.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event())
        store.save_snapshot("s1", {"x": 1}, 1)
        store.clear()
        assert store.get_stats()["total_events"] == 0
        assert store.get_snapshot("s1") is None
        assert store._sequence_counter == 0


# ---------------------------------------------------------------------------
# _cleanup_oldest – lines 1285-1324
# ---------------------------------------------------------------------------


class TestCleanupOldest:
    # branch [1292, 1293]: SQLITE logical-deletes the N oldest
    def test_cleanup_oldest_sqlite_keeps_newest(self, tmp_path) -> None:
        db = str(tmp_path / "cln.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event("old"))
        store.append(_make_event("new"))
        store._cleanup_oldest(count=1)
        remaining = [e.event.event_type for e in store.get_all()]
        assert remaining == ["new"]

    # branches [1319, 1322]: MEMORY removes oldest from both store and stream index
    def test_cleanup_oldest_memory_updates_stream_index(self) -> None:
        store = _make_store()
        store.append(_make_event("old"), stream_id="s1")
        store.append(_make_event("new"), stream_id="s1")
        store._cleanup_oldest(count=1)
        remaining = store.get_stream_events("s1")
        assert [e.event.event_type for e in remaining] == ["new"]
        # stream index no longer references the removed store_id
        assert len(store._stream_events["s1"]) == 1

    # MEMORY: event without a stream still gets removed cleanly
    def test_cleanup_oldest_memory_no_stream(self) -> None:
        store = _make_store()
        store.append(_make_event())
        store._cleanup_oldest(count=1)
        assert store._events == {}


# ---------------------------------------------------------------------------
# Global convenience functions – lines 1332-1353
# ---------------------------------------------------------------------------


class TestGlobalFunctions:
    # branch [1335, 1336]: get_event_store lazily creates a singleton
    def test_get_event_store_creates_and_caches_instance(self) -> None:
        import app.neuro_bus.event_store as es_mod

        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = None
            store = get_event_store()
            assert isinstance(store, EventStore)
            # cached: module global now points at the created instance
            assert es_mod._event_store_instance is store
        finally:
            es_mod._event_store_instance = original

    def test_get_event_store_returns_same_instance(self) -> None:
        assert get_event_store() is get_event_store()

    def test_store_event_shortcut_appends_to_global(self) -> None:
        import app.neuro_bus.event_store as es_mod

        store = _make_store()
        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = store
            sid = store_event(_make_event("shortcut.evt"))
            assert sid.startswith("evt-")
            assert store.get(sid).event.event_type == "shortcut.evt"
        finally:
            es_mod._event_store_instance = original

    def test_replay_events_shortcut_counts_global_events(self) -> None:
        import app.neuro_bus.event_store as es_mod

        store = _make_store()
        store.append(_make_event())
        store.append(_make_event())
        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = store
            assert replay_events() == 2
        finally:
            es_mod._event_store_instance = original

    def test_get_event_stats_shortcut_reads_global_stats(self) -> None:
        import app.neuro_bus.event_store as es_mod

        store = _make_store()
        store.append(_make_event("g.a"))
        original = es_mod._event_store_instance
        try:
            es_mod._event_store_instance = store
            stats = get_event_stats()
            assert stats["total_events"] == 1
            assert stats["by_event_type"] == {"g.a": 1}
        finally:
            es_mod._event_store_instance = original


# ---------------------------------------------------------------------------
# _row_to_stored_event with upcaster – lines 348-370
# ---------------------------------------------------------------------------


class TestRowToStoredEventUpcaster:
    # branch [354, 355]: registry present and stored version < current → upcast on read
    def test_row_read_applies_upcaster(self, tmp_path) -> None:
        db = str(tmp_path / "up.db")
        reg = UpcasterRegistry()
        reg.register(_UpV1toV2())
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db, upcaster_registry=reg)

        # Insert a raw v1 row directly so read-time upcasting is exercised
        e = _make_event("order.placed", {"x": 1})
        metadata = {"event_schema_version": 1}
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
        # upcaster v1->v2 set payload["v"] = 2 and bumped recorded schema version
        assert result.event.payload.get("v") == 2
        assert result.metadata["event_schema_version"] == 2

    # branch [359, 360]: no registry → payload read back verbatim, no schema bump
    def test_row_read_without_upcaster_is_verbatim(self, tmp_path) -> None:
        db = str(tmp_path / "no_up.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        sid = store.append(_make_event("plain", {"x": 9}))
        result = store.get(sid)
        assert result.event.payload == {"x": 9}
        assert "v" not in result.event.payload


# ---------------------------------------------------------------------------
# _get_stream_version – lines 401-410
# ---------------------------------------------------------------------------


class TestGetStreamVersion:
    def test_sqlite_stream_version_counts_undeleted(self, tmp_path) -> None:
        db = str(tmp_path / "sv.db")
        store = EventStore(mode=EventStoreMode.SQLITE, storage_path=db)
        store.append(_make_event(), stream_id="s1")
        store.append(_make_event(), stream_id="s1")
        assert store._get_stream_version("s1") == 2
        # logical delete drops the active count to 0
        store.delete_stream("s1")
        assert store._get_stream_version("s1") == 0

    def test_memory_stream_version(self) -> None:
        store = _make_store()
        store.append(_make_event(), stream_id="s1")
        assert store._get_stream_version("s1") == 1

    def test_memory_stream_version_nonexistent_is_zero(self) -> None:
        store = _make_store()
        assert store._get_stream_version("no-stream") == 0
