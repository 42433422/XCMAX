from __future__ import annotations

"""Branch-coverage tests for app.neuro_bus.dead_letter_queue.

Targets the missing branches listed in the task spec.  Tests are kept simple:
one test = one branch path.  No real DB connections — SQLite is used in
in-memory mode (:memory:) where persistence is needed, otherwise we work in
pure-memory (storage_path=None) mode.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta
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
from app.neuro_bus.events.events_base import NeuroEvent

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
# ReplayDeduplicator — branches 127-128 (conn not None → init table)
# ===========================================================================


class TestReplayDeduplicatorInit:
    def test_conn_none_no_init_sqlite_table(self) -> None:
        """Branch [127→128 NOT taken]: conn is None, skip _init_sqlite_table."""
        dedup = ReplayDeduplicator(conn=None)
        # Should work in memory-mode without any DB operations
        assert dedup._conn is None

    def test_conn_provided_init_sqlite_table(self) -> None:
        """Branch [127→128 taken]: conn is not None, _init_sqlite_table is called."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        # Table must exist
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='neuro_dlq_replay_log'"
        )
        assert cur.fetchone() is not None
        conn.close()


# ===========================================================================
# ReplayDeduplicator.is_replayed  — branches 157-158, 169-171, 172-173, 172-175
# ===========================================================================


class TestReplayDeduplicatorIsReplayed:
    def test_conn_not_none_branch_157_158(self) -> None:
        """Branch [157→158 taken]: conn is not None → SQLite path."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        result = dedup.is_replayed("entry-abc", 0)
        assert result is False
        conn.close()

    def test_memory_mode_none_record_169_171(self) -> None:
        """Branch [169→171]: record is None → return False immediately."""
        dedup = ReplayDeduplicator(conn=None)
        # No entries → record is None
        assert dedup.is_replayed("entry-xyz", 0) is False

    def test_memory_mode_expired_record_172_173(self) -> None:
        """Branch [172→173]: record exists but expired → delete and return False."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=0.001)
        dedup.mark_replayed("entry-e1", 0)
        # Wait for expiry
        time.sleep(0.05)
        # Should treat as expired
        result = dedup.is_replayed("entry-e1", 0)
        assert result is False
        # Also verify it was removed from memory log
        fp = ReplayDeduplicator.fingerprint("entry-e1", 0)
        assert fp not in dedup._memory_log

    def test_memory_mode_valid_record_172_175(self) -> None:
        """Branch [172→175 not taken]: record exists and not expired → return True."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=3600)
        dedup.mark_replayed("entry-v1", 0)
        assert dedup.is_replayed("entry-v1", 0) is True


# ===========================================================================
# ReplayDeduplicator.mark_replayed  — branch 183-184
# ===========================================================================


class TestMarkReplayed:
    def test_conn_not_none_183_184(self) -> None:
        """Branch [183→184 taken]: conn is not None → SQLite insert."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        dedup.mark_replayed("entry-m1", 0)
        cur = conn.execute("SELECT COUNT(*) FROM neuro_dlq_replay_log")
        assert cur.fetchone()[0] == 1
        conn.close()

    def test_conn_none_memory_path(self) -> None:
        """Branch [183→184 NOT taken]: conn is None → memory dict."""
        dedup = ReplayDeduplicator(conn=None)
        dedup.mark_replayed("entry-m2", 0)
        fp = ReplayDeduplicator.fingerprint("entry-m2", 0)
        assert fp in dedup._memory_log


# ===========================================================================
# ReplayDeduplicator.cleanup_expired — branches 202-203, 202-211, 214-215
# ===========================================================================


class TestCleanupExpired:
    def test_conn_not_none_202_203(self) -> None:
        """Branch [202→203 taken]: conn is not None → SQLite DELETE path."""
        conn = sqlite3.connect(":memory:")
        dedup = ReplayDeduplicator(conn=conn)
        count = dedup.cleanup_expired()
        assert count == 0
        conn.close()

    def test_conn_none_memory_202_211(self) -> None:
        """Branch [202→211 NOT taken]: memory path cleanup."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=0.001)
        dedup.mark_replayed("entry-c1", 0)
        time.sleep(0.05)
        count = dedup.cleanup_expired()
        assert count == 1

    def test_conn_none_no_expired_214_215(self) -> None:
        """Branch [214→215]: no expired entries in memory."""
        dedup = ReplayDeduplicator(conn=None, ttl_seconds=3600)
        dedup.mark_replayed("entry-c2", 0)
        count = dedup.cleanup_expired()
        assert count == 0


# ===========================================================================
# AlertSuppressor.record_and_check — branches 268-277, 277-278, 285-286,
#   293-301, 294-299
# ===========================================================================


class TestAlertSuppressor:
    def test_new_group_created_268_277(self) -> None:
        """Branch [268→277 NOT taken]: group is None → create new group."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type")
        assert count == 1

    def test_window_reset_277_278(self) -> None:
        """Branch [277→278 taken]: event outside window resets count."""
        sup = AlertSuppressor(suppress_window=0.001, threshold=1)
        sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type2")
        time.sleep(0.05)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type2")
        # count resets to 1 after window reset
        assert count == 1

    def test_global_silence_285_286(self) -> None:
        """Branch [285→286 taken]: silenced → suppressed increment, return False."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        sup.silence(3600)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type3")
        assert should_alert is False

    def test_below_threshold_293_301(self) -> None:
        """Branch [293→301]: count < threshold → suppressed."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=5)
        should_alert, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type4")
        assert should_alert is False
        stats = sup.get_stats()
        assert stats["groups"]["timeout:ev.type4"]["suppressed"] == 1

    def test_within_suppress_window_294_299(self) -> None:
        """Branch [294→299]: within window → suppressed."""
        sup = AlertSuppressor(suppress_window=300.0, threshold=1)
        sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type5")  # fires first alert
        should_alert, _ = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev.type5")  # suppressed
        assert should_alert is False


# ===========================================================================
# DeadLetterQueue init — branch 365-366 (storage_path not None)
# ===========================================================================


class TestDLQInit:
    def test_storage_path_none_365_366(self) -> None:
        """Branch [365→366 NOT taken]: storage_path=None → no SQLite init."""
        dlq = DeadLetterQueue(storage_path=None)
        assert dlq._conn is None

    def test_storage_path_provided_365_366(self, tmp_path) -> None:
        """Branch [365→366 taken]: storage_path set → SQLite init."""
        db_path = str(tmp_path / "dlq_test.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        assert dlq._conn is not None
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue._init_sqlite — branch 392-393 (parent.exists check)
# ===========================================================================


class TestInitSqlite:
    def test_parent_exists_no_mkdir(self, tmp_path) -> None:
        """Branch [392→393 NOT taken]: parent exists → no mkdir needed."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        assert dlq._conn is not None
        dlq._conn.close()

    def test_parent_not_exists_mkdir(self, tmp_path) -> None:
        """Branch [392→393 taken]: parent dir does not exist → mkdir."""
        db_path = str(tmp_path / "subdir" / "nested" / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        assert dlq._conn is not None
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.enqueue — branch 502-503 (sqlite vs memory), 532-533, 532-535
# ===========================================================================


class TestEnqueue:
    def test_enqueue_memory_mode_502_503(self) -> None:
        """Branch [502→503 NOT taken]: memory mode, entry stored in dict."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        assert eid in dlq._entries

    def test_enqueue_memory_at_capacity_532_533(self) -> None:
        """Branch [532→533 taken]: capacity reached → evict oldest."""
        dlq = make_dlq(max_size=2)
        eid1 = _enqueue(dlq, "ev.a")
        eid2 = _enqueue(dlq, "ev.b")
        assert len(dlq._entries) == 2
        # Third entry triggers eviction
        eid3 = _enqueue(dlq, "ev.c")
        assert len(dlq._entries) == 2
        assert eid3 in dlq._entries

    def test_enqueue_memory_below_capacity_532_535(self) -> None:
        """Branch [532→535 NOT taken]: below capacity → no eviction."""
        dlq = make_dlq(max_size=100)
        eid = _enqueue(dlq)
        assert eid in dlq._entries


# ===========================================================================
# DeadLetterQueue.dequeue — branches 560-561, 567-568, 567-569
# ===========================================================================


class TestDequeue:
    def test_conn_not_none_560_561(self, tmp_path) -> None:
        """Branch [560→561 taken]: SQLite path returns row."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        eid = _enqueue(dlq)
        entry = dlq.dequeue(eid)
        assert entry is not None
        dlq._conn.close()

    def test_conn_not_none_not_found_567_568(self, tmp_path) -> None:
        """Branch [567→568 taken]: SQLite row not found → return None."""
        db_path = str(tmp_path / "dlq2.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        entry = dlq.dequeue("nonexistent-id")
        assert entry is None
        dlq._conn.close()

    def test_conn_none_found_567_569(self) -> None:
        """Branch [567→569 NOT taken]: memory mode, entry found."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        entry = dlq.dequeue(eid)
        assert entry is not None


# ===========================================================================
# DeadLetterQueue.remove — branches 574-575
# ===========================================================================


class TestRemove:
    def test_remove_conn_not_none(self, tmp_path) -> None:
        """Branch [574→575 taken]: SQLite path for remove."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        eid = _enqueue(dlq)
        result = dlq.remove(eid)
        assert result is True
        dlq._conn.close()

    def test_remove_memory_entry_exists(self) -> None:
        """Branch [574→575 NOT taken]: memory mode, entry exists → True."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        assert dlq.remove(eid) is True

    def test_remove_memory_entry_missing(self) -> None:
        """Branch: memory mode, entry missing → False."""
        dlq = make_dlq()
        assert dlq.remove("no-such-id") is False


# ===========================================================================
# DeadLetterQueue.replay — branches 603-604
# ===========================================================================


class TestReplay:
    def test_replay_entry_not_found(self) -> None:
        """Branch: dequeue returns None → (False, 'entry_not_found')."""
        dlq = make_dlq()
        ok, reason = dlq.replay("no-such-id")
        assert ok is False
        assert reason == "entry_not_found"

    def test_replay_already_replayed_603_604(self) -> None:
        """Branch [603→604 taken]: deduplicator says already replayed."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        entry = dlq.dequeue(eid)
        assert entry is not None
        # Pre-mark as replayed
        dlq._deduplicator.mark_replayed(eid, entry.retry_count)
        ok, reason = dlq.replay(eid)
        assert ok is False
        assert reason == "already_replayed"

    def test_replay_success(self) -> None:
        """Successful replay path — callback triggered."""
        dlq = make_dlq()
        replayed_events: list[NeuroEvent] = []
        dlq.on_replay(replayed_events.append)
        eid = _enqueue(dlq)
        ok, reason = dlq.replay(eid)
        assert ok is True
        assert reason == ""
        assert len(replayed_events) == 1

    def test_replay_callback_exception_does_not_record_success(self) -> None:
        dlq = make_dlq()

        def bad_callback(event: NeuroEvent) -> None:
            raise ValueError("simulated callback failure")

        dlq.on_replay(bad_callback)
        eid = _enqueue(dlq)
        with pytest.raises(ValueError, match="simulated callback failure"):
            dlq.replay(eid)
        assert dlq.get_stats()["replayed"] == 0
        assert eid in {entry.entry_id for entry in dlq.get_all_entries()}


# ===========================================================================
# DeadLetterQueue._get_replay_candidates — branches 643-644, 645-646, 645-657,
#   653-654, 653-684, 655-653, 655-656, 657-658, 657-663, 663-664, 663-672,
#   667-668, 667-684, 669-667, 669-670, 679-680
# ===========================================================================


class TestGetReplayCandidates:
    """Use pure-memory mode to exercise the else branch at line 674."""

    def test_no_filter(self) -> None:
        """Branch [643→644 NOT taken and 674+]: memory mode, no filter."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.x")
        candidates = dlq._get_replay_candidates()
        assert len(candidates) == 1

    def test_event_type_filter_matches(self) -> None:
        """Branch [677]: event_type given, entry matches."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.match")
        _enqueue(dlq, "ev.other")
        candidates = dlq._get_replay_candidates(event_type="ev.match")
        assert candidates  # at least one match

    def test_event_type_filter_no_match_679_680(self) -> None:
        """Branch [677 taken / 679→680]: entry type doesn't match → continue (skip)."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.nomatch")
        candidates = dlq._get_replay_candidates(event_type="ev.wanted")
        assert candidates == []

    def test_max_age_filter_excluded(self) -> None:
        """Branch [679]: age too large → skip entry.

        The filter checks ``entry.age_seconds > max_age_seconds`` (and only
        runs when max_age_seconds is truthy).  We use a tiny positive value
        (1e-9) so that after a brief sleep the entry is always older.
        """
        dlq = make_dlq()
        _enqueue(dlq, "ev.old")
        time.sleep(0.02)  # ensure age_seconds > 1e-9
        candidates = dlq._get_replay_candidates(max_age_seconds=1e-9)
        assert candidates == []

    def test_max_age_filter_included(self) -> None:
        """Branch: entry within age → included."""
        dlq = make_dlq()
        _enqueue(dlq)
        candidates = dlq._get_replay_candidates(max_age_seconds=9999.0)
        assert len(candidates) == 1

    def test_both_filters_match(self) -> None:
        """Both event_type and max_age_seconds, entry passes both."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.both")
        candidates = dlq._get_replay_candidates(event_type="ev.both", max_age_seconds=9999.0)
        assert len(candidates) == 1

    def test_both_filters_age_excludes(self) -> None:
        """Both filters, but age too large → excluded."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.both2")
        time.sleep(0.02)  # ensure age_seconds > 1e-9
        candidates = dlq._get_replay_candidates(event_type="ev.both2", max_age_seconds=1e-9)
        assert candidates == []


class TestGetReplayCandidatesSqlite:
    """SQLite branches: 643→644, 645→646, 645→657, 657→658, 657→663, 663→664."""

    def _make_sqlite_dlq(self, tmp_path) -> DeadLetterQueue:
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        return dlq

    def test_sqlite_no_filter_643_644(self, tmp_path) -> None:
        """Branch [643→644 taken]: conn is not None, no filters → SELECT all."""
        dlq = self._make_sqlite_dlq(tmp_path)
        _enqueue(dlq, "ev.sql")
        candidates = dlq._get_replay_candidates()
        assert len(candidates) >= 1
        dlq._conn.close()

    def test_sqlite_event_type_only_657_658(self, tmp_path) -> None:
        """Branch [657→658]: event_type only, max_age_seconds None."""
        dlq = self._make_sqlite_dlq(tmp_path)
        _enqueue(dlq, "ev.et")
        candidates = dlq._get_replay_candidates(event_type="ev.et")
        assert len(candidates) >= 1
        dlq._conn.close()

    def test_sqlite_max_age_only_663_664(self, tmp_path) -> None:
        """Age-only selection excludes old entries without deleting them."""
        dlq = self._make_sqlite_dlq(tmp_path)
        old = _enqueue(dlq)
        young = _enqueue(dlq)
        dlq._conn.execute(
            "UPDATE neuro_dead_letters SET first_failure_time = ? WHERE entry_id = ?",
            ((datetime.now() - timedelta(hours=1)).isoformat(), old),
        )
        assert dlq._get_replay_candidates(max_age_seconds=60) == [young]
        assert {entry.entry_id for entry in dlq.get_all_entries()} == {old, young}
        dlq._conn.close()

    def test_sqlite_both_filters_645_646(self, tmp_path) -> None:
        """Type and age filters both apply, preserving all persisted entries."""
        dlq = self._make_sqlite_dlq(tmp_path)
        old = _enqueue(dlq, "ev.both")
        young = _enqueue(dlq, "ev.both")
        other = _enqueue(dlq, "ev.other")
        dlq._conn.execute(
            "UPDATE neuro_dead_letters SET first_failure_time = ? WHERE entry_id = ?",
            ((datetime.now() - timedelta(hours=1)).isoformat(), old),
        )
        assert dlq._get_replay_candidates(event_type="ev.both", max_age_seconds=60) == [young]
        assert {entry.entry_id for entry in dlq.get_all_entries()} == {old, young, other}
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.replay_all — branches 714-715, 719-723, 723-724, 724-712,
#   724-725
# ===========================================================================


class TestReplayAll:
    def test_replay_all_no_entries(self) -> None:
        """Empty queue → count=0."""
        dlq = make_dlq()
        count = dlq.replay_all()
        assert count == 0

    def test_replay_all_paused_714_715(self) -> None:
        """Branch [714→715 taken]: replay paused → break early."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.1")
        dlq.pause_replay()
        count = dlq.replay_all()
        assert count == 0

    def test_replay_all_replays_entry_719_723(self) -> None:
        """Branch [719→723 NOT taken]: replayed=True → increment count."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.rep")
        count = dlq.replay_all()
        assert count == 1

    def test_replay_all_batch_sleep_723_724(self) -> None:
        """Branch [723→724 taken]: batch_size=1 with 2 entries triggers sleep."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.b1")
        _enqueue(dlq, "ev.b2")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            count = dlq.replay_all(batch_size=1, rate_limit_qps=100.0)
        # sleep called once (after first batch, but not after last)
        mock_sleep.assert_called()

    def test_replay_all_no_sleep_if_no_more_entries_724_712(self) -> None:
        """Branch [724→712]: (i+1) == total, don't sleep."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.single")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            count = dlq.replay_all(batch_size=1, rate_limit_qps=100.0)
        # After last item, no sleep
        mock_sleep.assert_not_called()


# ===========================================================================
# DeadLetterQueue.replay_with_progress — branches 775-(-749), 775-777, 777-778,
#   777-781, 782-783, 782-785, 788-775, 788-789, 789-775, 789-790
# ===========================================================================


class TestReplayWithProgress:
    def test_empty_queue_no_yields(self) -> None:
        """Empty → generator yields nothing."""
        dlq = make_dlq()
        results = list(dlq.replay_with_progress())
        assert results == []

    def test_single_entry_yields_775_777(self) -> None:
        """Branch [775→777 NOT taken]: at least one iteration, not paused."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.rp")
        results = list(dlq.replay_with_progress())
        assert len(results) == 1

    def test_paused_during_progress_777_778(self) -> None:
        """Branch [777→778 taken]: paused → early return."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.pause1")
        dlq.pause_replay()
        results = list(dlq.replay_with_progress())
        assert results == []

    def test_success_increments_replayed_782_783(self) -> None:
        """Branch [782→783]: replay succeeds → replayed counter incremented."""
        dlq = make_dlq()
        _enqueue(dlq)
        results = list(dlq.replay_with_progress())
        assert results[0][0] == 1  # replayed=1

    def test_batch_sleep_in_progress_788_789(self) -> None:
        """Branch [788→789]: batch boundary → sleep called."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.p1")
        _enqueue(dlq, "ev.p2")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            results = list(dlq.replay_with_progress(batch_size=1, rate_limit_qps=100.0))
        mock_sleep.assert_called()

    def test_no_sleep_at_end_789_790(self) -> None:
        """Branch [789→790]: (i+1) == total → no sleep."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.last")
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            results = list(dlq.replay_with_progress(batch_size=1, rate_limit_qps=100.0))
        mock_sleep.assert_not_called()
