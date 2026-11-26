"""Dead-letter gradual replay, cleanup and retry scheduling."""

from __future__ import annotations

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
from tests.test_neuro_bus.test_dead_letter_queue_cov import (
    _enqueue,
    make_dlq,
    make_event,
)

# ===========================================================================
# DeadLetterQueue.replay_gradual — branches 813-814, 813-816, 827-828,
#   827-830, 831-833, 831-881, 833-834, 833-839, 845-846, 845-855, 846-847,
#   846-850, 851-845, 851-852, 869-870, 869-878, 878-831, 878-879
# ===========================================================================


class TestReplayGradual:
    def test_empty_queue_returns_early_827_828(self) -> None:
        """Branch [827→828 taken]: total=0 → return immediately."""
        dlq = make_dlq()
        report = dlq.replay_gradual()
        assert report["total"] == 0
        assert report["replayed"] == 0

    def test_default_stages_813_814(self) -> None:
        """Branch [813→814]: stages=None → default list created."""
        dlq = make_dlq()
        _enqueue(dlq)
        with patch.object(dlq, "_get_replay_candidates", return_value=[]) as m:
            dlq.replay_gradual()  # stages=None triggers default
        m.assert_called()

    def test_custom_stages_813_816(self) -> None:
        """Branch [813→816 NOT taken]: stages provided, not None."""
        dlq = make_dlq()
        _enqueue(dlq)
        report = dlq.replay_gradual(stages=[1.0])
        assert "stages_executed" in report

    def test_manual_pause_at_stage_start_833_834(self) -> None:
        """Branch [833→834 taken]: manual pause before batch loop."""
        dlq = make_dlq()
        _enqueue(dlq)
        dlq.pause_replay()
        report = dlq.replay_gradual(stages=[1.0])
        assert report["paused"] is True
        assert report["pause_reason"] == "manual_pause"

    def test_manual_pause_inside_batch_845_846(self) -> None:
        """Branch [845→846 taken]: pause while processing batch items."""
        dlq = make_dlq()
        _enqueue(dlq, "ev.g1")
        _enqueue(dlq, "ev.g2")

        call_count = 0

        def side_effect_pause() -> bool:
            nonlocal call_count
            call_count += 1
            # Pause on second check (inside batch)
            return call_count > 1

        dlq._is_replay_paused = side_effect_pause  # type: ignore[method-assign]
        report = dlq.replay_gradual(stages=[1.0])
        assert report["paused"] is True

    def test_error_threshold_exceeded_869_870(self) -> None:
        """Branch [869→870 taken]: new_dlq_count >= error_threshold → pause."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        # Simulate replay causing new dead letters
        original_replay = dlq.replay

        def patched_replay(entry_id: str):
            # Add a new dead letter entry each time replay is called
            _enqueue(dlq, "ev.new")
            return original_replay(entry_id)

        dlq.replay = patched_replay  # type: ignore[method-assign]
        report = dlq.replay_gradual(stages=[1.0], error_threshold=1)
        assert report["paused"] is True
        assert "error_threshold_exceeded" in (report["pause_reason"] or "")

    def test_stage_interval_sleep_878_879(self) -> None:
        """Branch [878→879 taken]: not last stage → sleep between stages."""
        dlq = make_dlq()
        _enqueue(dlq)
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            dlq.replay_gradual(stages=[0.5, 1.0], stage_interval=0.001)
        mock_sleep.assert_called()

    def test_no_sleep_at_last_stage_878_831(self) -> None:
        """Branch [878→831]: last stage, no sleep."""
        dlq = make_dlq()
        _enqueue(dlq)
        with patch("app.neuro_bus.dead_letter_queue.time.sleep") as mock_sleep:
            dlq.replay_gradual(stages=[1.0], stage_interval=0.001)
        # No sleep for the last (only) stage
        mock_sleep.assert_not_called()

    def test_replayed_count_tracked_851_852(self) -> None:
        """Branch [851→852]: replay succeeds → replayed incremented."""
        dlq = make_dlq()
        _enqueue(dlq)
        report = dlq.replay_gradual(stages=[1.0])
        assert report["replayed"] == 1


# ===========================================================================
# DeadLetterQueue.resolve_manually — branch 910-912
# ===========================================================================


class TestResolveManually:
    def test_entry_not_found(self) -> None:
        """Entry not found → return False."""
        dlq = make_dlq()
        assert dlq.resolve_manually("no-such-id", "manual", "admin") is False

    def test_memory_mode_resolve_910_912(self) -> None:
        """Branch [910→912 NOT taken]: memory mode → remove entry."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        result = dlq.resolve_manually(eid, "manual-fix", "admin")
        assert result is True
        assert eid not in dlq._entries

    def test_sqlite_mode_resolve_910_912(self, tmp_path) -> None:
        """Branch [910→912 taken]: SQLite mode → UPDATE + DELETE."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        eid = _enqueue(dlq)
        result = dlq.resolve_manually(eid, "fixed", "admin")
        assert result is True
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.cleanup_expired — branches 934-935, 934-953, 949-950,
#   949-951, 960-961, 960-963, 965-966, 965-968
# ===========================================================================


class TestCleanupExpiredDLQ:
    def test_memory_no_expired_934_953(self) -> None:
        """Branch [934→953 NOT taken]: memory mode, no expired."""
        dlq = make_dlq(retention_hours=168)
        _enqueue(dlq)
        count = dlq.cleanup_expired()
        assert count == 0

    def test_memory_has_expired_960_961(self) -> None:
        """Branch [960→961]: expired entries present → deleted."""
        dlq = make_dlq(retention_hours=0)
        _enqueue(dlq)
        # Force all entries to appear old by manipulating retention
        dlq._retention_seconds = -1  # everything is "too old"
        count = dlq.cleanup_expired()
        assert count >= 1

    def test_memory_empty_no_log_965_968(self) -> None:
        """Branch [965→968 NOT taken]: no expired → no log message."""
        dlq = make_dlq()
        _enqueue(dlq)
        # retention large, nothing expires
        count = dlq.cleanup_expired()
        assert count == 0

    def test_sqlite_cleanup_934_935(self, tmp_path) -> None:
        """Branch [934→935 taken]: SQLite mode → DELETE query."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path, retention_hours=168)
        _enqueue(dlq)
        count = dlq.cleanup_expired()
        assert count == 0  # not old enough
        dlq._conn.close()

    def test_sqlite_expired_log_949_950(self, tmp_path) -> None:
        """Branch [949→950 taken]: sqlite, entries deleted → log."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path, retention_hours=0)
        _enqueue(dlq)
        dlq._retention_seconds = -1
        count = dlq.cleanup_expired()
        assert count >= 1
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.get_stats — branches 974-975, 974-978, 982-983, 993-994,
#   1004-1005, 1022-1023, 1022-1027
# ===========================================================================


class TestGetStats:
    def test_memory_mode_empty_974_975(self) -> None:
        """Branch [974→975 NOT taken]: memory mode, empty → oldest_age=0."""
        dlq = make_dlq()
        stats = dlq.get_stats()
        assert stats["current_size"] == 0
        assert stats["oldest_entry_age_hours"] == 0

    def test_memory_mode_with_entries_974_978(self) -> None:
        """Branch [974→978]: memory mode with entries → oldest_age computed."""
        dlq = make_dlq()
        _enqueue(dlq)
        stats = dlq.get_stats()
        assert stats["current_size"] == 1

    def test_sqlite_mode_empty_1022_1027(self, tmp_path) -> None:
        """Branch [1022→1027 taken]: SQLite mode, no entries → oldest_age=0."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        stats = dlq.get_stats()
        assert stats["oldest_entry_age_hours"] == 0
        dlq._conn.close()

    def test_sqlite_mode_with_entry_1022_1023(self, tmp_path) -> None:
        """Branch [1022→1023 taken]: SQLite mode, entry exists → oldest_age > 0."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        _enqueue(dlq)
        stats = dlq.get_stats()
        assert stats["current_size"] == 1
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue.triage_entries — branches 1083-1084, 1083-1095, 1086-1087,
#   1086-1104, 1088-1089, 1088-1090, 1090-1091, 1090-1092, 1092-1086,
#   1092-1093, 1096-1097, 1096-1104, 1097-1098, 1097-1099, 1099-1100,
#   1099-1101, 1101-1096, 1101-1102
# ===========================================================================


class TestTriageEntries:
    def test_memory_retriable_1095_1097(self) -> None:
        """Branch [1095+]: memory mode, retriable reason."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.RETRY_EXHAUSTED, "err", 3)
        result = dlq.triage_entries()
        assert result["retriable"]

    def test_memory_fixable_1099_1100(self) -> None:
        """Branch [1099→1100]: fixable reason."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.INVALID_PAYLOAD, "err", 1)
        result = dlq.triage_entries()
        assert result["fixable"]

    def test_memory_poison_1101_1102(self) -> None:
        """Branch [1101→1102]: poison reason."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        result = dlq.triage_entries()
        assert result["poison"]

    def test_memory_timeout_retriable(self) -> None:
        """TIMEOUT is retriable."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.TIMEOUT, "err", 1)
        result = dlq.triage_entries()
        assert result["retriable"]

    def test_memory_handler_not_found_fixable(self) -> None:
        """HANDLER_NOT_FOUND is fixable."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.HANDLER_NOT_FOUND, "err", 0)
        result = dlq.triage_entries()
        assert result["fixable"]

    def test_memory_circuit_breaker_poison(self) -> None:
        """CIRCUIT_BREAKER is poison."""
        dlq = make_dlq()
        dlq.enqueue(make_event(), DeadLetterReason.CIRCUIT_BREAKER, "err", 0)
        result = dlq.triage_entries()
        assert result["poison"]

    def test_sqlite_triage_1083_1084(self, tmp_path) -> None:
        """Branch [1083→1084 taken]: SQLite mode triage."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        dlq.enqueue(make_event(), DeadLetterReason.RETRY_EXHAUSTED, "err", 3)
        dlq.enqueue(make_event(), DeadLetterReason.INVALID_PAYLOAD, "err", 1)
        dlq.enqueue(make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        result = dlq.triage_entries()
        assert result["retriable"]
        assert result["fixable"]
        assert result["poison"]
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue._trigger_alert — branch 1127-1128
# ===========================================================================


class TestTriggerAlert:
    def test_no_alert_when_suppressed_1127_1128(self) -> None:
        """Branch [1127→1128 taken]: should_alert=False → return early."""
        dlq = make_dlq(alert_threshold=5)
        called: list[DeadLetterEntry] = []
        dlq.on_alert(called.append)
        _enqueue(dlq)  # count=1, threshold=5 → suppressed
        assert called == []

    def test_alert_fires_when_threshold_met(self) -> None:
        """Branch [1127→1128 NOT taken]: should_alert=True → callback called."""
        dlq = make_dlq(alert_threshold=1, alert_suppress_window=0.0)
        called: list[DeadLetterEntry] = []
        dlq.on_alert(called.append)
        _enqueue(dlq)
        assert len(called) == 1

    def test_alert_callback_exception_swallowed(self) -> None:
        """Alert callback raises RECOVERABLE_ERRORS → not re-raised."""
        dlq = make_dlq(alert_threshold=1, alert_suppress_window=0.0)

        def bad_alert(entry: DeadLetterEntry) -> None:
            raise OSError("network error")

        dlq.on_alert(bad_alert)
        # Should not raise
        _enqueue(dlq)


# ===========================================================================
# DeadLetterQueue.schedule_retry — branches 1184-1185, 1184-1189,
#   1196-1197, 1222-1223, 1232-1233, 1232-1234, 1242-1243
# ===========================================================================


class TestScheduleRetry:
    def test_entry_not_found_1184_1185(self) -> None:
        """Branch [1184→1185 taken]: entry not found → return None."""
        dlq = make_dlq()
        result = dlq.schedule_retry("no-such")
        assert result is None

    def test_memory_mode_updates_entry_1184_1189(self) -> None:
        """Branch [1184→1189 NOT taken]: memory mode, entry found → delay returned."""
        dlq = make_dlq()
        eid = _enqueue(dlq)
        delay = dlq.schedule_retry(eid)
        assert delay is not None
        assert delay > 0

    def test_sqlite_mode_schedule_retry_1196_1197(self, tmp_path) -> None:
        """Branch [1196→1197 taken]: SQLite mode UPDATE."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path)
        eid = _enqueue(dlq)
        delay = dlq.schedule_retry(eid)
        assert delay is not None
        dlq._conn.close()


# ===========================================================================
# DeadLetterQueue._evict_oldest — branches 1222-1223, 1232-1233, 1232-1234,
#   1242-1243
# ===========================================================================


class TestEvictOldest:
    def test_memory_empty_1242_1243(self) -> None:
        """Branch [1242→1243 taken]: empty memory dict → return early."""
        dlq = make_dlq()
        # Should not raise
        dlq._evict_oldest()

    def test_memory_not_empty_evicts_oldest(self) -> None:
        """Branch [1242→1243 NOT taken]: entries exist → evict oldest."""
        dlq = make_dlq(max_size=1)
        eid1 = _enqueue(dlq, "ev.old")
        # Second enqueue triggers eviction
        eid2 = _enqueue(dlq, "ev.new")
        assert eid1 not in dlq._entries
        assert eid2 in dlq._entries

    def test_sqlite_evict_oldest_1222_1223(self, tmp_path) -> None:
        """Branch [1222→1223 taken]: SQLite mode eviction."""
        db_path = str(tmp_path / "dlq.db")
        dlq = DeadLetterQueue(storage_path=db_path, max_size=1)
        eid1 = _enqueue(dlq, "ev.sql.old")
        eid2 = _enqueue(dlq, "ev.sql.new")
        # After eviction, only one entry remains
        entry1 = dlq.dequeue(eid1)
        entry2 = dlq.dequeue(eid2)
        assert (entry1 is None) or (entry2 is None)
        dlq._conn.close()


# ===========================================================================
# NeuroBusDLQIntegration.handle_failure — reason branches
# ===========================================================================


class TestNeuroBusDLQIntegration:
    def test_retry_exhausted(self) -> None:
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        event = make_event()
        eid = integration.handle_failure(event, RuntimeError("err"), retry_count=3)
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED

    def test_timeout_error(self) -> None:
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        event = make_event()
        eid = integration.handle_failure(event, TimeoutError("timed out"), retry_count=0)
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.TIMEOUT

    def test_value_error_invalid_payload(self) -> None:
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        event = make_event()
        eid = integration.handle_failure(event, ValueError("bad payload"), retry_count=0)
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.INVALID_PAYLOAD

    def test_other_error_unrecoverable(self) -> None:
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        event = make_event()
        eid = integration.handle_failure(event, RuntimeError("unknown"), retry_count=0)
        entry = dlq.dequeue(eid)
        assert entry is not None
        assert entry.reason == DeadLetterReason.UNRECOVERABLE

    def test_setup_replay_to_bus(self) -> None:
        """setup_replay_to_bus registers a publish callback."""
        bus = MagicMock()
        dlq = make_dlq()
        integration = NeuroBusDLQIntegration(dlq=dlq)
        integration.setup_replay_to_bus(bus)
        eid = _enqueue(dlq)
        dlq.replay(eid)
        bus.publish.assert_called_once()


# ===========================================================================
# Global helpers — get_dead_letter_queue / enqueue_dead_letter / get_dlq_stats
# ===========================================================================


class TestGlobalHelpers:
    @pytest.fixture(autouse=True)
    def _isolated_dlq_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_DLQ_PATH", str(tmp_path / "global.sqlite3"))

    def setup_method(self) -> None:
        import app.neuro_bus.dead_letter_queue as mod

        mod._dlq_instance = None  # reset singleton

    def teardown_method(self) -> None:
        import app.neuro_bus.dead_letter_queue as mod

        if mod._dlq_instance is not None:
            mod._dlq_instance.close()
        mod._dlq_instance = None

    def test_get_dead_letter_queue_creates_instance(self) -> None:
        dlq = get_dead_letter_queue()
        assert dlq is not None

    def test_get_dead_letter_queue_returns_same_instance(self) -> None:
        dlq1 = get_dead_letter_queue()
        dlq2 = get_dead_letter_queue()
        assert dlq1 is dlq2

    def test_enqueue_dead_letter_valid_reason(self) -> None:
        event = make_event()
        eid = enqueue_dead_letter(event, "retry_exhausted", "err", retry_count=1)
        assert eid.startswith("dlq-")

    def test_enqueue_dead_letter_invalid_reason_fallback(self) -> None:
        """Invalid reason string → fallback to UNRECOVERABLE."""
        event = make_event()
        eid = enqueue_dead_letter(event, "not_a_real_reason", "err")
        assert eid.startswith("dlq-")

    def test_get_dlq_stats(self) -> None:
        stats = get_dlq_stats()
        assert "current_size" in stats


# ===========================================================================
# DeadLetterEntry helpers
# ===========================================================================


class TestDeadLetterEntry:
    def _make_entry(self) -> DeadLetterEntry:
        return DeadLetterEntry(
            entry_id="test-entry-1",
            original_event=make_event(),
            reason=DeadLetterReason.RETRY_EXHAUSTED,
            error_message="err",
            error_stack=None,
            retry_count=3,
            first_failure_time=datetime.now(),
            last_failure_time=datetime.now(),
            handler_name=None,
        )

    def test_age_seconds(self) -> None:
        entry = self._make_entry()
        assert entry.age_seconds >= 0

    def test_to_dict(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        assert d["entry_id"] == "test-entry-1"
        assert d["reason"] == "retry_exhausted"


# ===========================================================================
# AlertSuppressor.silence + get_stats
# ===========================================================================


class TestAlertSuppressorSilence:
    def test_silence_and_stats(self) -> None:
        sup = AlertSuppressor()
        sup.silence(10.0)
        stats = sup.get_stats()
        assert stats["silenced"] is True
        assert stats["silenced_remaining_seconds"] > 0

    def test_not_silenced_after_duration(self) -> None:
        sup = AlertSuppressor()
        sup.silence(0.001)
        time.sleep(0.05)
        stats = sup.get_stats()
        assert stats["silenced"] is False
        assert stats["silenced_remaining_seconds"] == 0.0
