from __future__ import annotations

"""Behavior tests for app.neuro_bus.dead_letter_queue.

These tests exercise both the in-memory and SQLite-backed code paths and
assert on concrete return values / observable state changes (not just
non-emptiness).  SQLite uses on-disk temp files (tmp_path) so the
``check_same_thread=False`` connection from the production code works; pure
memory mode (storage_path=None) is used elsewhere.
"""

import sqlite3
import time
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.dead_letter_queue import (
    AlertSuppressor,
    DeadLetterEntry,
    DeadLetterQueue,
    DeadLetterReason,
    NeuroBusDLQIntegration,
    ReplayDeduplicator,
    enqueue_dead_letter,
    get_dead_letter_queue,
    get_dlq_stats,
)
from app.neuro_bus.events.base import NeuroEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(event_type: str = "test.event", payload: dict | None = None) -> NeuroEvent:
    return NeuroEvent(event_type=event_type, payload=payload or {"k": "v"})


def make_dlq(**kwargs: Any) -> DeadLetterQueue:
    """Return a pure-memory DLQ (no filesystem/SQLite persistence)."""
    return DeadLetterQueue(**kwargs)


def _enqueue(dlq: DeadLetterQueue, event_type: str = "test.event") -> str:
    return dlq.enqueue(
        event=make_event(event_type),
        reason=DeadLetterReason.RETRY_EXHAUSTED,
        error_message="boom",
        retry_count=3,
    )


# ===========================================================================
# ReplayDeduplicator.fingerprint / init
# ===========================================================================


class TestReplayDeduplicatorInit:
    def test_fingerprint_is_deterministic_sha256(self) -> None:
        """fingerprint() = sha256(entry_id:replay_count), stable + collision-distinct."""
        fp_a = ReplayDeduplicator.fingerprint("entry-abc", 0)
        fp_a2 = ReplayDeduplicator.fingerprint("entry-abc", 0)
        fp_b = ReplayDeduplicator.fingerprint("entry-abc", 1)
        assert fp_a == fp_a2  # deterministic
        assert fp_a != fp_b  # replay_count is part of the key
        assert len(fp_a) == 64  # sha256 hex digest
        assert all(c in "0123456789abcdef" for c in fp_a)

    def test_conn_none_uses_memory_backend(self) -> None:
        """conn is None → no SQLite handle, empty in-memory log."""
        dedup = ReplayDeduplicator(conn=None)
        assert dedup._conn is None
        assert dedup._memory_log == {}

    def test_conn_provided_creates_replay_log_table(self) -> None:
        """conn is not None → _init_sqlite_table creates the replay-log table + index."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        assert dedup._conn is conn
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='neuro_dlq_replay_log'"
        ).fetchone()
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_dlq_replay_expires'"
        ).fetchone()
        assert table == ("neuro_dlq_replay_log",)
        assert index == ("idx_dlq_replay_expires",)
        conn.close()


# ===========================================================================
# ReplayDeduplicator.is_replayed
# ===========================================================================


class TestReplayDeduplicatorIsReplayed:
    def test_sqlite_unknown_fingerprint_returns_false(self) -> None:
        """SQLite path: fingerprint absent → False."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        assert dedup.is_replayed("entry-abc", 0) is False
        conn.close()

    def test_sqlite_marked_then_replayed_returns_true(self) -> None:
        """SQLite path: mark then check → True (round-trip through the table)."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn, ttl_seconds=3600)
        dedup.mark_replayed("entry-abc", 2)
        assert dedup.is_replayed("entry-abc", 2) is True
        # Different replay_count → different fingerprint → not replayed
        assert dedup.is_replayed("entry-abc", 3) is False
        conn.close()

    def test_memory_unknown_fingerprint_returns_false(self) -> None:
        """Memory path: record is None → False."""
        dedup = ReplayDeduplicator(conn=None)
        assert dedup.is_replayed("entry-xyz", 0) is False

    def test_memory_expired_record_is_evicted_and_false(self) -> None:
        """Memory path: record exists but TTL elapsed → delete + False."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=0.001)
        dedup.mark_replayed("entry-e1", 0)
        fp = ReplayDeduplicator.fingerprint("entry-e1", 0)
        assert fp in dedup._memory_log  # present before expiry
        time.sleep(0.05)
        assert dedup.is_replayed("entry-e1", 0) is False
        assert fp not in dedup._memory_log  # lazily evicted on read

    def test_memory_valid_record_returns_true(self) -> None:
        """Memory path: record exists, not expired → True."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=3600)
        dedup.mark_replayed("entry-v1", 0)
        assert dedup.is_replayed("entry-v1", 0) is True


# ===========================================================================
# ReplayDeduplicator.mark_replayed
# ===========================================================================


class TestMarkReplayed:
    def test_sqlite_insert_persists_row_with_fingerprint(self) -> None:
        """SQLite path: mark_replayed writes exactly one row keyed by fingerprint."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        dedup.mark_replayed("entry-m1", 0)
        fp = ReplayDeduplicator.fingerprint("entry-m1", 0)
        rows = conn.execute("SELECT fingerprint, entry_id FROM neuro_dlq_replay_log").fetchall()
        assert rows == [(fp, "entry-m1")]
        conn.close()

    def test_sqlite_mark_is_idempotent_insert_or_replace(self) -> None:
        """SQLite path: marking the same fingerprint twice keeps a single row."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        dedup.mark_replayed("entry-dup", 0)
        dedup.mark_replayed("entry-dup", 0)
        count = conn.execute("SELECT COUNT(*) FROM neuro_dlq_replay_log").fetchone()[0]
        assert count == 1
        conn.close()

    def test_memory_stores_entry_id_and_expiry(self) -> None:
        """Memory path: stores (entry_id, expires_at) under the fingerprint."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=3600)
        before = time.time()
        dedup.mark_replayed("entry-m2", 5)
        fp = ReplayDeduplicator.fingerprint("entry-m2", 5)
        stored_entry_id, expires_at = dedup._memory_log[fp]
        assert stored_entry_id == "entry-m2"
        assert expires_at >= before + 3600  # TTL applied to expiry timestamp


# ===========================================================================
# ReplayDeduplicator.cleanup_expired
# ===========================================================================


class TestCleanupExpired:
    def test_sqlite_no_expired_returns_zero(self) -> None:
        """SQLite path: nothing expired → 0 rows deleted."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn, ttl_seconds=3600)
        dedup.mark_replayed("entry-keep", 0)
        assert dedup.cleanup_expired() == 0
        # The non-expired row survives
        assert conn.execute("SELECT COUNT(*) FROM neuro_dlq_replay_log").fetchone()[0] == 1
        conn.close()

    def test_sqlite_expired_row_deleted(self) -> None:
        """SQLite path: an already-expired fingerprint is deleted and counted."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn, ttl_seconds=0.001)
        dedup.mark_replayed("entry-old", 0)
        time.sleep(0.05)
        deleted = dedup.cleanup_expired()
        assert deleted == 1
        assert conn.execute("SELECT COUNT(*) FROM neuro_dlq_replay_log").fetchone()[0] == 0
        conn.close()

    def test_memory_expired_only_removed(self) -> None:
        """Memory path: only expired fingerprints are removed; fresh ones remain."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=0.02)
        dedup.mark_replayed("entry-c1", 0)  # will expire
        time.sleep(0.05)
        dedup.mark_replayed("entry-c2", 0)  # fresh
        fp_fresh = ReplayDeduplicator.fingerprint("entry-c2", 0)
        removed = dedup.cleanup_expired()
        assert removed == 1
        assert list(dedup._memory_log.keys()) == [fp_fresh]

    def test_memory_no_expired_returns_zero(self) -> None:
        """Memory path: nothing expired → 0 and log untouched."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=3600)
        dedup.mark_replayed("entry-c2", 0)
        assert dedup.cleanup_expired() == 0
        assert len(dedup._memory_log) == 1


# ===========================================================================
# AlertSuppressor.record_and_check
# ===========================================================================


class TestAlertSuppressor:
    def test_first_event_at_threshold_one_fires_alert(self) -> None:
        """New group, count reaches threshold=1 immediately → should_alert True, count 1."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type")
        assert (should_alert, count) == (True, 1)
        assert sup.get_stats()["groups"]["timeout:ev.type"]["fired"] == 1

    def test_window_expiry_resets_event_count(self) -> None:
        """Event past suppress_window resets count back to 1 (window reset branch)."""
        sup = AlertSuppressor(suppress_window=0.01, threshold=1)
        _, c1 = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type2")
        assert c1 == 1
        time.sleep(0.05)
        should_alert, c2 = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type2")
        assert c2 == 1  # counter reset by window expiry, not 2
        assert should_alert is True  # last_alert_ts also outside window again

    def test_global_silence_suppresses_and_counts(self) -> None:
        """While silenced → should_alert False and the suppressed stat increments."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        sup.silence(3600)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type3")
        assert should_alert is False
        assert count == 1
        assert sup.get_stats()["groups"]["timeout:ev.type3"]["suppressed"] == 1
        assert sup.get_stats()["groups"]["timeout:ev.type3"]["fired"] == 0

    def test_below_threshold_suppressed(self) -> None:
        """count < threshold → suppressed, no fire, suppressed stat == 1."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=5)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type4")
        assert (should_alert, count) == (False, 1)
        stats = sup.get_stats()["groups"]["timeout:ev.type4"]
        assert stats == {"suppressed": 1, "fired": 0, "total": 1}

    def test_second_event_within_window_is_suppressed(self) -> None:
        """First fires; a second within the window is suppressed (last_alert_ts guard)."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        first_alert, _ = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type5")
        second_alert, second_count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type5")
        assert first_alert is True
        assert second_alert is False
        assert second_count == 2  # event still counted
        stats = sup.get_stats()["groups"]["timeout:ev.type5"]
        assert stats == {"suppressed": 1, "fired": 1, "total": 2}

    def test_reason_and_event_type_form_distinct_groups(self) -> None:
        """Different (reason, event_type) keys are tracked independently."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.a")
        sup.record_and_check(DeadLetterReason.UNRECOVERABLE, "ev.a")
        groups = sup.get_stats()["groups"]
        assert set(groups) == {"timeout:ev.a", "unrecoverable:ev.a"}


# ===========================================================================
# DeadLetterQueue init
# ===========================================================================


class TestDLQInit:
    def test_memory_mode_no_sqlite_connection(self) -> None:
        """storage_path=None → no SQLite connection, empty entry map."""
        dlq = DeadLetterQueue(storage_path=None)
        assert dlq._conn is None
        assert dlq._entries == {}

    def test_storage_path_opens_connection_and_table(self, tmp_path) -> None:
        """storage_path set → SQLite connection with neuro_dead_letters table."""
        db_path = str(tmp_path / "dlq_test.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        assert dlq._conn is not None
        table = dlq._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='neuro_dead_letters'"
        ).fetchone()
        assert table["name"] == "neuro_dead_letters"
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue._init_sqlite (parent dir handling)
# ===========================================================================


class TestInitSqlite:
    def test_existing_parent_dir_opens_db(self, tmp_path) -> None:
        """Parent dir already exists → DB opens, file created."""
        db_path = tmp_path / "dlq.db"
        dlq = DeadLetterQueue(storage_path=str(db_path))
        assert dlq._conn is not None
        assert db_path.exists()
        dlq._conn.close()

    def test_missing_parent_dir_is_created(self, tmp_path) -> None:
        """Parent dir absent → mkdir(parents=True) then DB opens."""
        nested = tmp_path / "subdir" / "nested"
        db_path = nested / "dlq.db"
        assert not nested.exists()
        dlq = DeadLetterQueue(storage_path=str(db_path))
        assert nested.exists()
        assert db_path.exists()
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.enqueue
# ===========================================================================


class TestEnqueue:
    def test_memory_enqueue_stores_entry_with_metadata(self) -> None:
        """Memory mode: entry stored under returned id, reason/retry/metadata populated."""
        dlq = make_dlq()
        event = make_event("svc.fail")
        eid = dlq.enqueue(event, DeadLetterReason.TIMEOUT, "boom", retry_count=2)
        assert eid.startswith("dlq-")
        assert eid in dlq._entries
        entry = dlq._entries[eid]
        assert entry.reason == DeadLetterReason.TIMEOUT
        assert entry.error_message == "boom"
        assert entry.retry_count == 2
        assert entry.original_event is event
        # enqueue envelope metadata captured from the original event
        assert entry.metadata["original_event_id"] == event.metadata.event_id
        assert entry.metadata["original_domain"] == event.metadata.domain
        # stats bumped
        assert dlq.get_stats()["total_entries"] == 1

    def test_memory_at_capacity_evicts_oldest_keeps_newest(self) -> None:
        """At max_size, a new enqueue evicts the oldest and keeps size constant."""
        dlq = make_dlq(max_size=2)
        eid1 = _enqueue(dlq, "ev.a")
        eid2 = _enqueue(dlq, "ev.b")
        assert set(dlq._entries) == {eid1, eid2}
        eid3 = _enqueue(dlq, "ev.c")
        assert len(dlq._entries) == 2
        assert eid1 not in dlq._entries  # oldest evicted
        assert {eid2, eid3} <= set(dlq._entries)

    def test_memory_below_capacity_no_eviction(self) -> None:
        """Below capacity → all entries retained."""
        dlq = make_dlq(max_size=100)
        ids = [_enqueue(dlq, f"ev.{i}") for i in range(3)]
        assert set(dlq._entries) == set(ids)

    def test_sqlite_enqueue_persists_row(self, tmp_path) -> None:
        """SQLite mode: enqueue writes a queryable row with the right columns."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        eid = dlq.enqueue(make_event("ev.sql"), DeadLetterReason.INVALID_PAYLOAD, "bad", 1)
        row = dlq._conn.execute(
            "SELECT event_type, reason, retry_count, is_resolved FROM neuro_dead_letters WHERE entry_id = ?",
            (eid,),
        ).fetchone()
        assert row["event_type"] == "ev.sql"
        assert row["reason"] == "invalid_payload"
        assert row["retry_count"] == 1
        assert row["is_resolved"] == 0
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.dequeue
# ===========================================================================


class TestDequeue:
    def test_sqlite_roundtrip_returns_equivalent_entry(self, tmp_path) -> None:
        """SQLite mode: dequeue reconstructs the entry from the row."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        eid = _enqueue(dlq, "ev.persist")
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.entry_id == eid
        assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED
        assert entry.retry_count == 3
        assert entry.original_event.event_type == "ev.persist"
        dlq._conn.close()

    def test_sqlite_missing_id_returns_none(self, tmp_path) -> None:
        """SQLite mode: unknown id → None."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq2.db"))
        assert dlq.dequeue("nonexistent-id") is None
        dlq._conn.close()

    def test_memory_returns_same_object(self) -> None:
        """Memory mode: dequeue returns the stored object identity (no copy)."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        entry = dlq.dequeue(eid)
        assert entry is dlq._entries[eid]


# ===========================================================================
# DeadLetterQueue.remove
# ===========================================================================


class TestRemove:
    def test_sqlite_remove_deletes_row(self, tmp_path) -> None:
        """SQLite mode: remove returns True and the row is gone."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        eid = _enqueue(dlq)
        assert dlq.remove(eid) is True
        assert dlq.dequeue(eid) is None
        # second remove of the same id → False (rowcount 0)
        assert dlq.remove(eid) is False
        dlq._conn.close()

    def test_memory_remove_existing_returns_true(self) -> None:
        """Memory mode: existing entry removed → True and gone from dict."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        assert dlq.remove(eid) is True
        assert eid not in dlq._entries

    def test_memory_remove_missing_returns_false(self) -> None:
        """Memory mode: unknown id → False."""
        dlq = make_dlq()
        assert dlq.remove("no-such-id") is False


# ===========================================================================
# DeadLetterQueue.replay
# ===========================================================================


class TestReplay:
    def test_entry_not_found_reason(self) -> None:
        """Unknown id → (False, 'entry_not_found')."""
        dlq = make_dlq()
        assert dlq.replay("no-such-id") == (False, "entry_not_found")

    def test_already_replayed_is_deduped(self) -> None:
        """Pre-marked fingerprint → (False, 'already_replayed'); callbacks not re-run."""
        dlq = make_dlq()
        seen: list[NeuroEvent] = []
        dlq.on_replay(seen.append)
        eid = _enqueue(dlq)
        entry = dlq.dequeue(eid)
        assert entry is not None
        dlq._deduplicator.mark_replayed(eid, entry.retry_count)
        assert dlq.replay(eid) == (False, "already_replayed")
        assert seen == []  # callback skipped because deduped
        assert dlq.get_stats()["replayed"] == 0

    def test_success_invokes_callbacks_marks_fingerprint_and_counts(self) -> None:
        """Success → (True, ''), callback fired with original event, replay counted, fp marked."""
        dlq = make_dlq()
        replayed_events: list[NeuroEvent] = []
        dlq.on_replay(replayed_events.append)
        event = make_event("ev.replay")
        eid = dlq.enqueue(event, DeadLetterReason.RETRY_EXHAUSTED, "boom", 3)
        ok, reason = dlq.replay(eid)
        assert (ok, reason) == (True, "")
        assert replayed_events == [event]  # callback got the actual original event
        assert dlq.get_stats()["replayed"] == 1
        # fingerprint now marked → re-replay is deduped
        assert dlq.replay(eid) == (False, "already_replayed")

    def test_callback_recoverable_error_is_swallowed_still_success(self) -> None:
        """A callback raising a RECOVERABLE error is logged, replay still succeeds + counts."""
        dlq = make_dlq()
        calls: list[str] = []

        def bad_callback(event: NeuroEvent) -> None:
            calls.append("bad")
            raise ConnectionError("simulated callback failure")

        def good_callback(event: NeuroEvent) -> None:
            calls.append("good")

        dlq.on_replay(bad_callback)
        dlq.on_replay(good_callback)
        eid = _enqueue(dlq)
        ok, reason = dlq.replay(eid)
        assert (ok, reason) == (True, "")
        assert calls == ["bad", "good"]  # later callbacks still run
        assert dlq.get_stats()["replayed"] == 1


# ===========================================================================
# DeadLetterQueue._get_replay_candidates  (memory mode)
# ===========================================================================


class TestGetReplayCandidates:
    def test_no_filter_returns_all_ids(self) -> None:
        """No filter → every enqueued id is a candidate."""
        dlq = make_dlq()
        ids = {_enqueue(dlq, "ev.x"), _enqueue(dlq, "ev.y")}
        assert set(dlq._get_replay_candidates()) == ids

    def test_event_type_filter_selects_only_matches(self) -> None:
        """event_type filter returns only entries of that type."""
        dlq = make_dlq()
        match_id = _enqueue(dlq, "ev.match")
        _enqueue(dlq, "ev.other")
        assert dlq._get_replay_candidates(event_type="ev.match") == [match_id]

    def test_event_type_filter_no_match_returns_empty(self) -> None:
        """event_type with no matching entry → empty list (continue/skip path)."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.nomatch")
        assert dlq._get_replay_candidates(event_type="ev.wanted") == []

    def test_max_age_filter_excludes_old_entries(self) -> None:
        """age_seconds > max_age_seconds → excluded."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.old")
        time.sleep(0.02)
        assert dlq._get_replay_candidates(max_age_seconds=1e-9) == []

    def test_max_age_filter_includes_recent_entries(self) -> None:
        """age within max_age → included."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        assert dlq._get_replay_candidates(max_age_seconds=9999.0) == [eid]

    def test_both_filters_pass(self) -> None:
        """event_type + max_age both satisfied → included."""
        dlq = make_dlq()
        eid = _enqueue(dlq, "ev.both")
        assert dlq._get_replay_candidates(event_type="ev.both", max_age_seconds=9999.0) == [eid]

    def test_both_filters_age_excludes(self) -> None:
        """event_type matches but age too large → excluded."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.both2")
        time.sleep(0.02)
        assert dlq._get_replay_candidates(event_type="ev.both2", max_age_seconds=1e-9) == []


class TestGetReplayCandidatesSqlite:
    def _make_sqlite_dlq(self, tmp_path) -> DeadLetterQueue:
        return DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))

    def test_sqlite_no_filter_returns_all(self, tmp_path) -> None:
        """SQLite, no filters → SELECT all ids."""
        dlq = self._make_sqlite_dlq(tmp_path)
        eid = _enqueue(dlq, "ev.sql")
        assert dlq._get_replay_candidates() == [eid]
        dlq._conn.close()

    def test_sqlite_event_type_only_filters(self, tmp_path) -> None:
        """SQLite, event_type only → only matching rows."""
        dlq = self._make_sqlite_dlq(tmp_path)
        match_id = _enqueue(dlq, "ev.et")
        _enqueue(dlq, "ev.nope")
        assert dlq._get_replay_candidates(event_type="ev.et") == [match_id]
        dlq._conn.close()

    def test_sqlite_max_age_only_is_broken_raises_indexerror(self, tmp_path) -> None:
        """SOURCE BUG: SQLite max_age_seconds path SELECTs only (entry_id,
        first_failure_time) but _row_to_entry needs all columns → IndexError.
        The max_age filter is therefore unusable in SQLite mode."""
        dlq = self._make_sqlite_dlq(tmp_path)
        _enqueue(dlq)
        with pytest.raises(IndexError):
            dlq._get_replay_candidates(max_age_seconds=9999.0)
        dlq._conn.close()

    def test_sqlite_both_filters_is_broken_raises_indexerror(self, tmp_path) -> None:
        """SOURCE BUG: SQLite event_type+max_age path has the same partial-SELECT
        defect → IndexError from _row_to_entry."""
        dlq = self._make_sqlite_dlq(tmp_path)
        _enqueue(dlq, "ev.both")
        with pytest.raises(IndexError):
            dlq._get_replay_candidates(event_type="ev.both", max_age_seconds=9999.0)
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.replay_all
# ===========================================================================


class TestReplayAll:
    def test_empty_queue_replays_nothing(self) -> None:
        """Empty queue → count 0."""
        dlq = make_dlq()
        assert dlq.replay_all() == 0

    def test_paused_breaks_before_replaying(self) -> None:
        """Paused → loop breaks immediately, nothing replayed, entry stays unreplayed."""
        dlq = make_dlq()
        eid = _enqueue(dlq, "ev.1")
        dlq.pause_replay()
        assert dlq.replay_all() == 0
        assert dlq.get_stats()["replayed"] == 0
        # still not deduped → can replay after resume
        dlq.resume_replay()
        assert dlq.replay(eid)[0] is True

    def test_replays_all_candidates_and_counts(self) -> None:
        """Two entries → both replayed, count 2, stats reflect it."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.r1")
        _enqueue(dlq, "ev.r2")
        assert dlq.replay_all() == 2
        assert dlq.get_stats()["replayed"] == 2

    def test_batch_boundary_sleeps_between_batches(self) -> None:
        """batch_size=1 with 2 entries → sleep once (after first, not after last)."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.b1")
        _enqueue(dlq, "ev.b2")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            count = dlq.replay_all(batch_size=1, rate_limit_qps=100.0)
        assert count == 2
        assert mock_sleep.call_count == 1
        # sleep duration == batch_size / qps == 1/100
        assert mock_sleep.call_args.args[0] == pytest.approx(0.01)

    def test_no_sleep_when_single_entry(self) -> None:
        """Single entry → no inter-batch sleep (i+1 == total)."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.single")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            assert dlq.replay_all(batch_size=1, rate_limit_qps=100.0) == 1
        mock_sleep.assert_not_called()


# ===========================================================================
# DeadLetterQueue.replay_with_progress
# ===========================================================================


class TestReplayWithProgress:
    def test_empty_queue_yields_nothing(self) -> None:
        """Empty → generator produces no items."""
        dlq = make_dlq()
        assert list(dlq.replay_with_progress()) == []

    def test_single_entry_yields_progress_tuple(self) -> None:
        """One entry → one yield of (replayed=1, total=1, entry_id)."""
        dlq = make_dlq()
        eid = _enqueue(dlq, "ev.rp")
        results = list(dlq.replay_with_progress())
        assert results == [(1, 1, eid)]

    def test_paused_returns_before_any_yield(self) -> None:
        """Paused before iteration → no yields, nothing replayed."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.pause1")
        dlq.pause_replay()
        assert list(dlq.replay_with_progress()) == []
        assert dlq.get_stats()["replayed"] == 0

    def test_progress_counts_increment_across_entries(self) -> None:
        """Two entries → replayed counter climbs 1 then 2, total fixed at 2."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.a")
        _enqueue(dlq, "ev.b")
        results = list(dlq.replay_with_progress())
        replayed_seq = [r[0] for r in results]
        totals = {r[1] for r in results}
        assert replayed_seq == [1, 2]
        assert totals == {2}

    def test_batch_boundary_sleeps(self) -> None:
        """batch_size=1, 2 entries → sleep once between batches."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.p1")
        _enqueue(dlq, "ev.p2")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            results = list(dlq.replay_with_progress(batch_size=1, rate_limit_qps=100.0))
        assert len(results) == 2
        assert mock_sleep.call_count == 1

    def test_no_sleep_at_final_entry(self) -> None:
        """Single entry → no sleep at the end."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.last")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            list(dlq.replay_with_progress(batch_size=1, rate_limit_qps=100.0))
        mock_sleep.assert_not_called()


# ===========================================================================
# DeadLetterQueue.replay_gradual
# ===========================================================================


class TestReplayGradual:
    def test_empty_queue_returns_zeroed_report(self) -> None:
        """total=0 → early return with zeroed report, no pause."""
        dlq = make_dlq()
        report = dlq.replay_gradual()
        assert report["total"] == 0
        assert report["replayed"] == 0
        assert report["paused"] is False
        assert report["stages_executed"] == []

    def test_default_stages_used_when_none(self) -> None:
        """stages=None → the default [0.01, 0.1, 0.5, 1.0] ramp is executed in order."""
        dlq = make_dlq()
        _enqueue(dlq)
        report = dlq.replay_gradual(stage_interval=0.0)
        fractions = [s["fraction"] for s in report["stages_executed"]]
        assert fractions == [0.01, 0.1, 0.5, 1.0]

    def test_custom_single_stage_replays_all(self) -> None:
        """stages=[1.0] replays the whole queue in one stage."""
        dlq = make_dlq()
        _enqueue(dlq)
        report = dlq.replay_gradual(stages=[1.0])
        assert report["total"] == 1
        assert report["replayed"] == 1
        assert len(report["stages_executed"]) == 1
        assert report["stages_executed"][0]["stage"] == 0

    def test_manual_pause_before_stage_loop(self) -> None:
        """Paused before the stage loop → paused report, nothing replayed."""
        dlq = make_dlq()
        _enqueue(dlq)
        dlq.pause_replay()
        report = dlq.replay_gradual(stages=[1.0])
        assert report["paused"] is True
        assert report["pause_reason"] == "manual_pause"
        assert report["replayed"] == 0

    def test_manual_pause_inside_batch(self) -> None:
        """Pause toggled mid-batch → paused with manual_pause reason, partial replay.

        Checks fire: 1) stage-entry guard, 2) before item-1, 3) before item-2.
        We let the first two pass and pause before item-2 so exactly one entry
        is replayed before the in-batch pause branch fires.
        """
        dlq = make_dlq()
        _enqueue(dlq, "ev.g1")
        _enqueue(dlq, "ev.g2")
        call_count = 0

        def side_effect_pause() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count > 2  # pass stage-entry + item-1 checks, pause before item-2

        dlq._is_replay_paused = side_effect_pause  # type: ignore[method-assign]
        report = dlq.replay_gradual(stages=[1.0])
        assert report["paused"] is True
        assert report["pause_reason"] == "manual_pause"
        assert report["replayed"] == 1  # only the first item went through before pause

    def test_error_threshold_exceeded_auto_pauses(self) -> None:
        """new_dlq_count >= error_threshold → auto-pause with reason text + pause flag set."""
        dlq = make_dlq()
        _enqueue(dlq)
        original_replay = dlq.replay

        def patched_replay(entry_id: str):
            _enqueue(dlq, "ev.new")  # each replay spawns a new dead letter
            return original_replay(entry_id)

        dlq.replay = patched_replay  # type: ignore[method-assign]
        report = dlq.replay_gradual(stages=[1.0], error_threshold=1)
        assert report["paused"] is True
        assert report["pause_reason"].startswith("error_threshold_exceeded")
        assert dlq._is_replay_paused() is True  # pause_replay() was called

    def test_sleeps_between_non_final_stages(self) -> None:
        """Multiple stages → sleep(stage_interval) between them, not after the last."""
        dlq = make_dlq()
        _enqueue(dlq)
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            dlq.replay_gradual(stages=[0.5, 1.0], stage_interval=0.001)
        # exactly one sleep (between the 2 stages, not after the last)
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args.args[0] == pytest.approx(0.001)

    def test_no_sleep_for_single_stage(self) -> None:
        """Single stage → no inter-stage sleep."""
        dlq = make_dlq()
        _enqueue(dlq)
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            dlq.replay_gradual(stages=[1.0], stage_interval=0.001)
        mock_sleep.assert_not_called()

    def test_replayed_count_reflected_in_report(self) -> None:
        """Successful replay increments the report's replayed count."""
        dlq = make_dlq()
        _enqueue(dlq)
        report = dlq.replay_gradual(stages=[1.0])
        assert report["replayed"] == 1


# ===========================================================================
# DeadLetterQueue.resolve_manually
# ===========================================================================


class TestResolveManually:
    def test_missing_entry_returns_false(self) -> None:
        """Unknown id → False, resolved-counter untouched."""
        dlq = make_dlq()
        assert dlq.resolve_manually("no-such-id", "manual", "admin") is False
        assert dlq.get_stats()["manually_resolved"] == 0

    def test_memory_resolve_removes_and_counts(self) -> None:
        """Memory mode: resolve removes entry from queue and bumps the stat."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        assert dlq.resolve_manually(eid, "manual-fix", "admin") is True
        assert eid not in dlq._entries
        assert dlq.get_stats()["manually_resolved"] == 1

    def test_sqlite_resolve_deletes_row_and_counts(self, tmp_path) -> None:
        """SQLite mode: resolve deletes the active row and bumps the stat."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        eid = _enqueue(dlq)
        assert dlq.resolve_manually(eid, "fixed", "admin") is True
        assert dlq.dequeue(eid) is None  # removed from active queue
        assert dlq.get_stats()["manually_resolved"] == 1
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.cleanup_expired
# ===========================================================================


class TestCleanupExpiredDLQ:
    def test_memory_nothing_expired_returns_zero(self) -> None:
        """Long retention → nothing expires, entry survives."""
        dlq = make_dlq(retention_hours=168)
        eid = _enqueue(dlq)
        assert dlq.cleanup_expired() == 0
        assert eid in dlq._entries

    def test_memory_expired_entries_deleted_and_counted(self) -> None:
        """Negative retention makes everything 'too old' → deleted, expired stat bumped."""
        dlq = make_dlq(retention_hours=0)
        _enqueue(dlq)
        _enqueue(dlq, "ev.2")
        dlq._retention_seconds = -1  # everything older than this
        count = dlq.cleanup_expired()
        assert count == 2
        assert dlq._entries == {}
        assert dlq.get_stats()["expired"] == 2

    def test_sqlite_nothing_expired_returns_zero(self, tmp_path) -> None:
        """SQLite, fresh entry, long retention → DELETE removes nothing."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"), retention_hours=168)
        eid = _enqueue(dlq)
        assert dlq.cleanup_expired() == 0
        assert dlq.dequeue(eid) is not None
        dlq._conn.close()

    def test_sqlite_expired_rows_deleted_and_counted(self, tmp_path) -> None:
        """SQLite, negative retention → expired rows deleted, count returned, stat bumped."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"), retention_hours=0)
        eid = _enqueue(dlq)
        dlq._retention_seconds = -1
        count = dlq.cleanup_expired()
        assert count == 1
        assert dlq.dequeue(eid) is None
        assert dlq.get_stats()["expired"] == 1
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.get_stats
# ===========================================================================


class TestGetStats:
    def test_memory_empty_stats_shape(self) -> None:
        """Memory mode, empty → defined shape with zeros."""
        dlq = make_dlq(max_size=42)
        stats = dlq.get_stats()
        assert stats["current_size"] == 0
        assert stats["max_size"] == 42
        assert stats["oldest_entry_age_hours"] == 0
        assert stats["by_reason"] == {}
        assert stats["replayed"] == 0

    def test_memory_with_entries_by_reason_and_age(self) -> None:
        """Memory mode, mixed reasons → by_reason counts + oldest age > 0."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.TIMEOUT, "e", 1)
        dlq.enqueue(make_event(), DeadLetterReason.TIMEOUT, "e", 1)
        dlq.enqueue(make_event(), DeadLetterReason.INVALID_PAYLOAD, "e", 1)
        time.sleep(0.01)
        stats = dlq.get_stats()
        assert stats["current_size"] == 3
        assert stats["by_reason"] == {"timeout": 2, "invalid_payload": 1}
        assert stats["oldest_entry_age_hours"] > 0

    def test_sqlite_empty_oldest_age_zero(self, tmp_path) -> None:
        """SQLite mode, no entries → MIN() is NULL → oldest age 0."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        stats = dlq.get_stats()
        assert stats["current_size"] == 0
        assert stats["oldest_entry_age_hours"] == 0
        dlq._conn.close()

    def test_sqlite_with_entry_counts_and_groups(self, tmp_path) -> None:
        """SQLite mode, entries present → current_size + by_reason from GROUP BY."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        dlq.enqueue(make_event(), DeadLetterReason.RETRY_EXHAUSTED, "e", 3)
        dlq.enqueue(make_event(), DeadLetterReason.RETRY_EXHAUSTED, "e", 3)
        stats = dlq.get_stats()
        assert stats["current_size"] == 2
        assert stats["by_reason"] == {"retry_exhausted": 2}
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.triage_entries
# ===========================================================================


class TestTriageEntries:
    @pytest.mark.parametrize(
        "reason,bucket",
        [
            (DeadLetterReason.RETRY_EXHAUSTED, "retriable"),
            (DeadLetterReason.TIMEOUT, "retriable"),
            (DeadLetterReason.INVALID_PAYLOAD, "fixable"),
            (DeadLetterReason.HANDLER_NOT_FOUND, "fixable"),
            (DeadLetterReason.UNRECOVERABLE, "poison"),
            (DeadLetterReason.CIRCUIT_BREAKER, "poison"),
        ],
    )
    def test_memory_reason_maps_to_expected_bucket(self, reason, bucket) -> None:
        """Each reason lands in exactly its triage bucket (memory mode)."""
        dlq = make_dlq()
        eid = dlq.enqueue(make_event(), reason, "err", 0)
        result = dlq.triage_entries()
        buckets = {"retriable", "fixable", "poison"}
        assert result[bucket] == [eid]
        for other in buckets - {bucket}:
            assert result[other] == []

    def test_sqlite_triage_partitions_all_three_buckets(self, tmp_path) -> None:
        """SQLite mode: a mix of reasons partitions into the three buckets."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        r_id = dlq.enqueue(make_event(), DeadLetterReason.RETRY_EXHAUSTED, "e", 3)
        f_id = dlq.enqueue(make_event(), DeadLetterReason.INVALID_PAYLOAD, "e", 1)
        p_id = dlq.enqueue(make_event(), DeadLetterReason.UNRECOVERABLE, "e", 0)
        result = dlq.triage_entries()
        assert result["retriable"] == [r_id]
        assert result["fixable"] == [f_id]
        assert result["poison"] == [p_id]
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue._trigger_alert (via enqueue)
# ===========================================================================


class TestTriggerAlert:
    def test_below_threshold_suppresses_alert(self) -> None:
        """alert_threshold=5, single enqueue → suppressed, no callback."""
        dlq = make_dlq(alert_threshold=5)
        called: list[DeadLetterEntry] = []
        dlq.on_alert(called.append)
        _enqueue(dlq)
        assert called == []

    def test_threshold_met_fires_alert_with_count_metadata(self) -> None:
        """threshold=1 → alert fires with the entry and count metadata attached."""
        dlq = make_dlq(alert_threshold=1, alert_suppress_window=0.0)
        called: list[DeadLetterEntry] = []
        dlq.on_alert(called.append)
        eid = _enqueue(dlq)
        assert len(called) == 1
        fired = called[0]
        assert fired.entry_id == eid
        assert fired.metadata["alert_count_in_window"] == 1

    def test_alert_callback_recoverable_error_swallowed(self) -> None:
        """An alert callback raising a recoverable error doesn't break enqueue."""
        dlq = make_dlq(alert_threshold=1, alert_suppress_window=0.0)
        good_called: list[str] = []

        def bad_alert(entry: DeadLetterEntry) -> None:
            raise OSError("network error")

        def good_alert(entry: DeadLetterEntry) -> None:
            good_called.append(entry.entry_id)

        dlq.on_alert(bad_alert)
        dlq.on_alert(good_alert)
        eid = _enqueue(dlq)  # must not raise
        assert good_called == [eid]  # later callback still ran


# ===========================================================================
# DeadLetterQueue.schedule_retry
# ===========================================================================


class TestScheduleRetry:
    def test_missing_entry_returns_none(self) -> None:
        """Unknown id → None."""
        dlq = make_dlq()
        assert dlq.schedule_retry("no-such") is None

    def test_memory_returns_capped_jittered_delay_and_bumps_retry(self) -> None:
        """Memory mode: delay within [exp*0.5, exp*1.0] and retry_count incremented in place."""
        dlq = make_dlq()
        # retry_count=3 → exponential = min(0.5 * 2**3, 30) = 4.0; jitter 0.5..1.0
        eid = _enqueue(dlq)
        delay = dlq.schedule_retry(eid, base=0.5, cap=30.0)
        assert delay is not None
        assert 4.0 * 0.5 <= delay <= 4.0 * 1.0
        assert dlq._entries[eid].retry_count == 4  # incremented from 3

    def test_memory_delay_capped_by_cap(self) -> None:
        """Very high retry_count → exponential capped, delay never exceeds cap."""
        dlq = make_dlq()
        eid = dlq.enqueue(make_event(), DeadLetterReason.RETRY_EXHAUSTED, "e", retry_count=50)
        delay = dlq.schedule_retry(eid, base=0.5, cap=30.0)
        assert delay is not None
        assert delay <= 30.0
        assert delay >= 15.0  # cap * 0.5 lower jitter bound

    def test_sqlite_updates_retry_count_in_db(self, tmp_path) -> None:
        """SQLite mode: schedule_retry persists incremented retry_count."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"))
        eid = _enqueue(dlq)  # retry_count=3
        delay = dlq.schedule_retry(eid)
        assert delay is not None and delay > 0
        row = dlq._conn.execute(
            "SELECT retry_count FROM neuro_dead_letters WHERE entry_id = ?", (eid,)
        ).fetchone()
        assert row["retry_count"] == 4
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue._evict_oldest
# ===========================================================================


class TestEvictOldest:
    def test_memory_empty_is_noop(self) -> None:
        """Empty memory dict → no error, dict stays empty."""
        dlq = make_dlq()
        dlq._evict_oldest()
        assert dlq._entries == {}

    def test_memory_evicts_oldest_by_first_failure_time(self) -> None:
        """max_size=1 → second enqueue evicts the first (oldest)."""
        dlq = make_dlq(max_size=1)
        eid_old = _enqueue(dlq, "ev.old")
        eid_new = _enqueue(dlq, "ev.new")
        assert eid_old not in dlq._entries
        assert list(dlq._entries) == [eid_new]

    def test_sqlite_evicts_oldest_row(self, tmp_path) -> None:
        """SQLite max_size=1 → second enqueue evicts the oldest row."""
        dlq = DeadLetterQueue(storage_path=str(tmp_path / "dlq.db"), max_size=1)
        eid_old = _enqueue(dlq, "ev.sql.old")
        eid_new = _enqueue(dlq, "ev.sql.new")
        assert dlq.dequeue(eid_old) is None  # evicted
        assert dlq.dequeue(eid_new) is not None  # kept
        assert dlq.get_stats()["current_size"] == 1
        dlq._conn.close()


# ===========================================================================
# NeuroBusDLQIntegration.handle_failure (reason classification)
# ===========================================================================


class TestNeuroBusDLQIntegration:
    @pytest.mark.parametrize(
        "error,retry_count,expected",
        [
            (RuntimeError("err"), 3, DeadLetterReason.RETRY_EXHAUSTED),  # retries exhausted first
            (TimeoutError("timed out"), 0, DeadLetterReason.TIMEOUT),
            (ValueError("bad payload"), 0, DeadLetterReason.INVALID_PAYLOAD),
            (Exception("unknown"), 0, DeadLetterReason.UNRECOVERABLE),
        ],
    )
    def test_handle_failure_classifies_reason(self, error, retry_count, expected) -> None:
        """Reason is derived from retry count + exception type, then enqueued."""
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        event = make_event("svc.x")
        eid = integration.handle_failure(event, error, retry_count=retry_count)
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.reason == expected
        assert entry.error_message == str(error)
        assert entry.error_stack is not None  # traceback captured

    def test_retry_exhausted_takes_priority_over_value_error(self) -> None:
        """retry_count >= max_retries wins even for a ValueError."""
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        eid = integration.handle_failure(make_event(), ValueError("bad"), retry_count=5)
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED

    def test_setup_replay_to_bus_publishes_replayed_event(self) -> None:
        """setup_replay_to_bus → replay() publishes the original event to the bus."""
        bus = MagicMock()
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        integration.setup_replay_to_bus(bus)
        event = make_event("ev.bus")
        eid = dlq.enqueue(event, DeadLetterReason.RETRY_EXHAUSTED, "e", 3)
        dlq.replay(eid)
        bus.publish.assert_called_once_with(event)

    def test_default_integration_creates_own_dlq(self) -> None:
        """No dlq passed → integration builds its own DeadLetterQueue."""
        integration = NeuroBusDLQIntegration()
        assert isinstance(integration.dlq, DeadLetterQueue)


# ===========================================================================
# Global helpers — get_dead_letter_queue / enqueue_dead_letter / get_dlq_stats
# ===========================================================================


class TestGlobalHelpers:
    def setup_method(self) -> None:
        import app.neuro_bus.dead_letter_queue as mod

        mod._dlq_instance = None  # reset singleton

    def teardown_method(self) -> None:
        import app.neuro_bus.dead_letter_queue as mod

        mod._dlq_instance = None

    def test_get_dead_letter_queue_is_singleton(self) -> None:
        """Repeated calls return the same global instance."""
        dlq1 = get_dead_letter_queue()
        dlq2 = get_dead_letter_queue()
        assert isinstance(dlq1, DeadLetterQueue)
        assert dlq1 is dlq2

    def test_enqueue_dead_letter_valid_reason_string(self) -> None:
        """A valid reason string is parsed to the matching enum and enqueued."""
        event = make_event("ev.helper")
        eid = enqueue_dead_letter(event, "retry_exhausted", "err", retry_count=1)
        assert eid.startswith("dlq-")
        entry = get_dead_letter_queue().dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED
        assert entry.retry_count == 1

    def test_enqueue_dead_letter_invalid_reason_falls_back_to_unrecoverable(self) -> None:
        """An unparseable reason string falls back to UNRECOVERABLE (no crash)."""
        event = make_event()
        eid = enqueue_dead_letter(event, "not_a_real_reason", "err")
        entry = get_dead_letter_queue().dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.UNRECOVERABLE

    def test_get_dlq_stats_reflects_singleton_state(self) -> None:
        """get_dlq_stats reports the live size of the global queue."""
        enqueue_dead_letter(make_event(), "timeout", "err")
        stats = get_dlq_stats()
        assert stats["current_size"] == 1
        assert stats["by_reason"] == {"timeout": 1}


# ===========================================================================
# DeadLetterEntry helpers
# ===========================================================================


class TestDeadLetterEntry:
    def _make_entry(self, **overrides) -> DeadLetterEntry:
        base = {
            "entry_id": "test-entry-1",
            "original_event": make_event("ev.entry", {"a": 1}),
            "reason": DeadLetterReason.RETRY_EXHAUSTED,
            "error_message": "err",
            "error_stack": "trace",
            "retry_count": 3,
            "first_failure_time": datetime.now(),
            "last_failure_time": datetime.now(),
            "handler_name": "h",
        }
        base.update(overrides)
        return DeadLetterEntry(**base)

    def test_age_seconds_nonnegative_and_grows(self) -> None:
        """age_seconds is non-negative and increases over time."""
        entry = self._make_entry(first_failure_time=datetime.now())
        a1 = entry.age_seconds
        time.sleep(0.02)
        a2 = entry.age_seconds
        assert a1 >= 0
        assert a2 > a1

    def test_to_dict_serializes_full_structure(self) -> None:
        """to_dict emits reason.value, nested original_event, retry_count and age."""
        entry = self._make_entry()
        d = entry.to_dict()
        assert d["entry_id"] == "test-entry-1"
        assert d["reason"] == "retry_exhausted"  # enum -> value
        assert d["retry_count"] == 3
        assert d["error_message"] == "err"
        assert d["handler_name"] == "h"
        assert d["original_event"]["event_type"] == "ev.entry"
        assert d["original_event"]["payload"] == {"a": 1}
        assert isinstance(d["age_seconds"], float)
        # timestamps serialized as ISO strings
        datetime.fromisoformat(d["first_failure_time"])
        datetime.fromisoformat(d["last_failure_time"])


# ===========================================================================
# AlertSuppressor.silence + get_stats
# ===========================================================================


class TestAlertSuppressorSilence:
    def test_silence_marks_silenced_with_remaining_time(self) -> None:
        """silence(d) → silenced True and remaining seconds in (0, d]."""
        sup = AlertSuppressor()
        sup.silence(10.0)
        stats = sup.get_stats()
        assert stats["silenced"] is True
        assert 0.0 < stats["silenced_remaining_seconds"] <= 10.0

    def test_silence_expires_after_duration(self) -> None:
        """After the silence duration elapses → not silenced, remaining 0.0."""
        sup = AlertSuppressor()
        sup.silence(0.001)
        time.sleep(0.05)
        stats = sup.get_stats()
        assert stats["silenced"] is False
        assert stats["silenced_remaining_seconds"] == 0.0

    def test_get_stats_exposes_config(self) -> None:
        """get_stats surfaces the configured window + threshold."""
        sup = AlertSuppressor(suppress_window=123.0, threshold=7)
        stats = sup.get_stats()
        assert stats["suppress_window"] == 123.0
        assert stats["threshold"] == 7
