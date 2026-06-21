from __future__ import annotations

"""Targeted branch-coverage tests for app/neuro_bus/circuit_breaker.py.

Each test is intentionally narrow: one test = one missing branch.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    NeuroCircuitBreakerManager,
    RollingWindowCounter,
    get_circuit_breaker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cb(
    failure_threshold: int = 5,
    success_threshold: int = 3,
    timeout_seconds: float = 60.0,
    half_open_max_calls: int = 3,
    failure_rate_threshold: float = 0.5,
    minimum_number_of_calls: int = 20,
    slow_call_duration_threshold: float = 5.0,
    slow_call_rate_threshold: float = 0.8,
    fallback=None,
    fallback_timeout_seconds: float = 5.0,
    automatic_transition: bool = True,
    permitted_half_open: int = 10,
    min_half_open: int = 3,
) -> CircuitBreaker:
    cfg = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        success_threshold=success_threshold,
        timeout_seconds=timeout_seconds,
        half_open_max_calls=half_open_max_calls,
        failure_rate_threshold=failure_rate_threshold,
        minimum_number_of_calls=minimum_number_of_calls,
        slow_call_duration_threshold=slow_call_duration_threshold,
        slow_call_rate_threshold=slow_call_rate_threshold,
        fallback=fallback,
        fallback_timeout_seconds=fallback_timeout_seconds,
        automatic_transition_from_open_to_half_open=automatic_transition,
        permitted_number_of_calls_in_half_open_state=permitted_half_open,
        minimum_number_of_calls_in_half_open=min_half_open,
    )
    return CircuitBreaker("test", cfg)


# ---------------------------------------------------------------------------
# RollingWindowCounter.get_stats — while-loop body (stale bucket eviction)
# Branch [151, 152]: stale buckets exist when get_stats is called
# ---------------------------------------------------------------------------

class TestRollingWindowCounterGetStats:
    def test_get_stats_evicts_stale_buckets(self):
        """L151→L152: while-loop body taken when a stale bucket exists at get_stats time."""
        counter = RollingWindowCounter(window_size_seconds=0.05, bucket_size_seconds=0.01)
        counter.record_success()
        # Wait longer than the window so the bucket becomes stale
        time.sleep(0.1)
        stats = counter.get_stats()
        # After eviction the stale bucket is gone; totals reflect only current window
        assert stats["total"] == 0


# ---------------------------------------------------------------------------
# _transition_to — same-state early return
# Branch [261, 262]: old_state == new_state → immediate return
# ---------------------------------------------------------------------------

class TestTransitionTo:
    def test_same_state_no_op(self):
        """L261→L262: _transition_to with same state returns without side effects."""
        cb = _make_cb()
        cb._state_change_callbacks = []
        cb._transition_to(CircuitState.CLOSED)  # already CLOSED, no-op
        assert cb._state == CircuitState.CLOSED

    def test_callback_exception_swallowed(self):
        """L286→L287: callback that raises should be caught and logged, not re-raised."""
        cb = _make_cb()
        bad_callback = MagicMock(side_effect=RuntimeError("boom"))
        cb.on_state_change(bad_callback)
        # Transition to OPEN — should not raise even though callback raises
        cb._transition_to(CircuitState.OPEN)
        assert cb._state == CircuitState.OPEN
        bad_callback.assert_called_once()


# ---------------------------------------------------------------------------
# can_execute — OPEN state branches
# Branch [311, 324]: automatic_transition=False → returns False
# Branch [312, 324]: _last_failure_time is None → returns False
# Branch [326, 333]: HALF_OPEN quota exceeded → returns False
# ---------------------------------------------------------------------------

class TestCanExecute:
    def test_open_no_auto_transition_returns_false(self):
        """L311→L324: automatic_transition_from_open_to_half_open=False while OPEN."""
        cb = _make_cb(automatic_transition=False)
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic() - 9999.0
        result = cb.can_execute()
        assert result is False

    def test_open_last_failure_time_none_returns_false(self):
        """L312→L324: _last_failure_time is None while OPEN (automatic_transition=True)."""
        cb = _make_cb(automatic_transition=True)
        cb._state = CircuitState.OPEN
        cb._last_failure_time = None
        result = cb.can_execute()
        assert result is False

    def test_half_open_quota_exceeded_returns_false(self):
        """L326→L333: HALF_OPEN state with half_open_calls >= half_open_max_calls."""
        cb = _make_cb(half_open_max_calls=2)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_calls = 2  # already at max
        result = cb.can_execute()
        assert result is False

    def test_open_auto_transition_after_timeout_returns_true(self):
        """Timeout elapsed in OPEN → transitions to HALF_OPEN → returns True."""
        cb = _make_cb(timeout_seconds=0.01, automatic_transition=True)
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic() - 1.0
        result = cb.can_execute()
        assert result is True
        assert cb._state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# record_success — CLOSED with failure_count == 0 (no-op reset branch)
# Branch [359, -335]: CLOSED state and _failure_count == 0
# ---------------------------------------------------------------------------

class TestRecordSuccess:
    def test_closed_failure_count_zero_no_op(self):
        """L359→-335: CLOSED with _failure_count==0, the if-body is skipped."""
        cb = _make_cb()
        cb._failure_count = 0
        cb.record_success()
        assert cb._failure_count == 0

    def test_closed_failure_count_positive_resets(self):
        """CLOSED with _failure_count>0 → resets to 0."""
        cb = _make_cb()
        cb._failure_count = 3
        cb.record_success()
        assert cb._failure_count == 0


# ---------------------------------------------------------------------------
# record_failure — various branches
# Branch [388, -364]: OPEN state (not CLOSED, not HALF_OPEN) → no additional action
# Branch [407, 408]: total < minimum_number_of_calls false (window check skipped)
# Branch [408, 427]: failure_rate < threshold → slow_call_rate check
# Branch [427, -364]: slow_call_rate < threshold → no open transition
# Branch [427, 428]: slow_call_rate >= threshold → transition to OPEN
# ---------------------------------------------------------------------------

class TestRecordFailure:
    def test_open_state_records_failure_no_transition(self):
        """L388→-364: state is OPEN, neither HALF_OPEN nor CLOSED branches taken."""
        cb = _make_cb()
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic()
        old_state = cb._state
        cb.record_failure()
        # Still OPEN (no transition triggered by this path)
        assert cb._state == old_state

    def test_total_below_minimum_skips_window_check(self):
        """L407→L408 false: total < minimum_number_of_calls, window checks skipped."""
        cb = _make_cb(minimum_number_of_calls=100, failure_threshold=1000)
        # Only a handful of calls — below minimum_number_of_calls
        cb._window.record_success()
        cb._window.record_success()
        cb.record_failure()
        # Should still be CLOSED (no fast-fail either, threshold=1000)
        assert cb._state == CircuitState.CLOSED

    def test_failure_rate_below_threshold_checks_slow_call_rate(self):
        """L408→L427: failure_rate < threshold, falls through to slow_call_rate check."""
        # low failure_rate_threshold so we get past the minimum check
        # but failure_rate will be below slow_call check
        cb = _make_cb(
            minimum_number_of_calls=2,
            failure_rate_threshold=0.99,  # very high threshold, won't trip
            slow_call_rate_threshold=0.99,  # also high, won't trip
            failure_threshold=1000,
        )
        # Put enough calls in the window to pass minimum_number_of_calls
        for _ in range(5):
            cb._window.record_success()
        cb.record_failure()
        # failure_rate < 0.99 and slow_call_rate < 0.99 → stays CLOSED
        assert cb._state == CircuitState.CLOSED

    def test_slow_call_rate_above_threshold_opens_breaker(self):
        """L427→L428: slow_call_rate >= slow_call_rate_threshold → OPEN."""
        cb = _make_cb(
            minimum_number_of_calls=2,
            failure_rate_threshold=0.99,  # won't trip on failure_rate
            slow_call_rate_threshold=0.1,  # very low, will trip on slow_call_rate
            failure_threshold=1000,
        )
        # Put calls in window: mostly slow
        for _ in range(5):
            cb._window.record_success()
            cb._window.record_slow_call()
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    def test_slow_call_rate_below_threshold_no_transition(self):
        """L427→-364: slow_call_rate < threshold → stays CLOSED."""
        cb = _make_cb(
            minimum_number_of_calls=2,
            failure_rate_threshold=0.99,
            slow_call_rate_threshold=0.99,
            failure_threshold=1000,
        )
        for _ in range(5):
            cb._window.record_success()
        # No slow calls → slow_call_rate = 0 < 0.99
        cb.record_failure()
        assert cb._state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# record_slow_call — non-HALF_OPEN and HALF_OPEN paths
# Branch [453, -444]: not HALF_OPEN, only window recorded
# Branch [453, 454]: HALF_OPEN, half_open_window also recorded
# ---------------------------------------------------------------------------

class TestRecordSlowCall:
    def test_closed_state_only_main_window_updated(self):
        """L453→-444: CLOSED state, half_open_window NOT updated."""
        cb = _make_cb()
        before = cb._half_open_window.get_stats()["slow_call"]
        cb.record_slow_call()
        after = cb._half_open_window.get_stats()["slow_call"]
        assert after == before  # half_open_window unchanged

    def test_half_open_state_both_windows_updated(self):
        """L453→L454: HALF_OPEN state, half_open_window also updated."""
        cb = _make_cb()
        cb._state = CircuitState.HALF_OPEN
        before = cb._half_open_window.get_stats()["slow_call"]
        cb.record_slow_call()
        after = cb._half_open_window.get_stats()["slow_call"]
        assert after == before + 1


# ---------------------------------------------------------------------------
# _release_execution_slot — guard _concurrent_executions == 0
# Branch [464, -461]: guard prevents decrement below 0
# ---------------------------------------------------------------------------

class TestReleaseExecutionSlot:
    def test_release_when_zero_does_not_go_negative(self):
        """L464→-461: _concurrent_executions == 0, decrement skipped."""
        cb = _make_cb()
        assert cb._concurrent_executions == 0
        cb._release_execution_slot()
        assert cb._concurrent_executions == 0


# ---------------------------------------------------------------------------
# _call_fallback_sync — various paths
# Branch [475, 476]: fallback is None → raises CircuitBreakerOpen
# Branch [491, 493]: thread is alive (timeout path)
# Branch [491, 496]: thread finished but exc is not None
# Branch [496, 500]: exc is None → success path
# ---------------------------------------------------------------------------

class TestCallFallbackSync:
    def test_fallback_none_raises_circuit_open(self):
        """L475→L476: no fallback configured → CircuitBreakerOpen raised."""
        cb = _make_cb(fallback=None)
        with pytest.raises(CircuitBreakerOpen):
            cb._call_fallback_sync()

    def test_fallback_timeout_raises_timeout_error(self):
        """L491→L493: fallback thread still alive after timeout → TimeoutError."""
        barrier = threading.Event()

        def slow_fallback():
            barrier.wait(timeout=10)
            return "late"

        cb = _make_cb(fallback=slow_fallback, fallback_timeout_seconds=0.05)
        try:
            with pytest.raises(TimeoutError):
                cb._call_fallback_sync()
        finally:
            barrier.set()
        assert cb._fallback_failure_count == 1

    def test_fallback_raises_exception_propagates(self):
        """L496→L497: fallback raises → exc[0] is not None → re-raises."""
        def bad_fallback():
            raise ValueError("fallback error")

        cb = _make_cb(fallback=bad_fallback)
        with pytest.raises(ValueError, match="fallback error"):
            cb._call_fallback_sync()
        assert cb._fallback_failure_count == 1

    def test_fallback_success_returns_result(self):
        """L496→L500: fallback succeeds → result returned, success count incremented."""
        cb = _make_cb(fallback=lambda: "ok")
        result = cb._call_fallback_sync()
        assert result == "ok"
        assert cb._fallback_success_count == 1


# ---------------------------------------------------------------------------
# _call_fallback_async — various paths
# Branch [512, 513]: fallback is None → raises CircuitBreakerOpen
# Branch [517, 521]: fallback returns non-coroutine (sync fallback in async context)
# ---------------------------------------------------------------------------

class TestCallFallbackAsync:
    async def test_fallback_none_raises_circuit_open(self):
        """L512→L513: no async fallback → CircuitBreakerOpen raised."""
        cb = _make_cb(fallback=None)
        with pytest.raises(CircuitBreakerOpen):
            await cb._call_fallback_async()

    async def test_sync_fallback_in_async_context(self):
        """L517→L521: fallback() returns non-coroutine value, used directly."""
        cb = _make_cb(fallback=lambda: "sync_result")
        result = await cb._call_fallback_async()
        assert result == "sync_result"
        assert cb._fallback_success_count == 1

    async def test_async_fallback_success(self):
        """Async coroutine fallback succeeds normally."""
        async def async_fb():
            return "async_ok"

        cb = _make_cb(fallback=async_fb)
        result = await cb._call_fallback_async()
        assert result == "async_ok"
        assert cb._fallback_success_count == 1

    async def test_async_fallback_failure_increments_count(self):
        """Async fallback raises → fallback_failure_count incremented."""
        async def bad_fb():
            raise ValueError("async error")

        cb = _make_cb(fallback=bad_fb)
        with pytest.raises(ValueError):
            await cb._call_fallback_async()
        assert cb._fallback_failure_count == 1


# ---------------------------------------------------------------------------
# execute — missing branches
# Branch [554, 555]: can_execute() False with fallback → calls fallback
# Branch [563, 564]: slow_call in success path
# Branch [569, 570]: slow_call in failure path
# Branch [572, 573]: fallback after failure
# ---------------------------------------------------------------------------

class TestExecute:
    def test_open_with_fallback_calls_fallback(self):
        """L554→L555: can_execute()=False and fallback present → fallback called."""
        cb = _make_cb(fallback=lambda: "fallback_val", half_open_max_calls=0)
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic()
        result = cb.execute(lambda: "never")
        assert result == "fallback_val"

    def test_success_slow_call_recorded(self):
        """L563→L564: function succeeds but takes longer than slow_call_duration_threshold."""
        cb = _make_cb(slow_call_duration_threshold=0.0)  # 0s threshold → always slow

        def slow_fn():
            time.sleep(0.01)
            return "slow_ok"

        result = cb.execute(slow_fn)
        assert result == "slow_ok"
        stats = cb._window.get_stats()
        assert stats["slow_call"] >= 1

    def test_failure_slow_call_recorded(self):
        """L569→L570: function fails but took longer than slow_call_duration_threshold."""
        cb = _make_cb(slow_call_duration_threshold=0.0, failure_threshold=1000)

        def slow_failing_fn():
            time.sleep(0.01)
            raise OSError("slow fail")

        with pytest.raises(OSError):
            cb.execute(slow_failing_fn)
        stats = cb._window.get_stats()
        assert stats["slow_call"] >= 1

    def test_failure_with_fallback_returns_fallback(self):
        """L572→L573: function fails and fallback is present → fallback result returned."""
        cb = _make_cb(fallback=lambda: "fb_on_fail", failure_threshold=1000)

        def failing_fn():
            raise OSError("oops")

        result = cb.execute(failing_fn)
        assert result == "fb_on_fail"


# ---------------------------------------------------------------------------
# execute_async — missing branches
# Branch [602, 603]: can_execute() False with fallback
# Branch [611, 612]: slow_call in success path
# Branch [617, 618/619]: slow_call in failure path
# Branch [620, 621/622]: fallback in failure path
# ---------------------------------------------------------------------------

class TestExecuteAsync:
    async def test_open_with_fallback_calls_fallback(self):
        """L602→L603: can_execute()=False and async fallback present."""
        cb = _make_cb(fallback=lambda: "async_fb", half_open_max_calls=0)
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic()
        result = await cb.execute_async(lambda: asyncio.coroutine(lambda: "never")())
        assert result == "async_fb"

    async def test_async_success_slow_call_recorded(self):
        """L611→L612: async fn succeeds but is slow."""
        cb = _make_cb(slow_call_duration_threshold=0.0)

        async def slow_fn():
            await asyncio.sleep(0.01)
            return "slow_async"

        result = await cb.execute_async(slow_fn)
        assert result == "slow_async"
        stats = cb._window.get_stats()
        assert stats["slow_call"] >= 1

    async def test_async_failure_slow_call_recorded(self):
        """L617→L618/619: async fn fails and is slow."""
        cb = _make_cb(slow_call_duration_threshold=0.0, failure_threshold=1000)

        async def slow_failing():
            await asyncio.sleep(0.01)
            raise OSError("async slow fail")

        with pytest.raises(OSError):
            await cb.execute_async(slow_failing)
        stats = cb._window.get_stats()
        assert stats["slow_call"] >= 1

    async def test_async_failure_with_fallback_returns_fallback(self):
        """L620→L621/622: async fn fails with fallback present."""
        cb = _make_cb(fallback=lambda: "async_fb_on_fail", failure_threshold=1000)

        async def failing():
            raise OSError("async fail")

        result = await cb.execute_async(failing)
        assert result == "async_fb_on_fail"


# ---------------------------------------------------------------------------
# get_prometheus_metrics — empty breakers loop
# Branch [801, 819]: no breakers → loop body never entered
# ---------------------------------------------------------------------------

class TestGetPrometheusMetrics:
    def test_empty_manager_returns_header_only(self):
        """L801→L819: no breakers → for-loop body not taken, only headers output."""
        manager = NeuroCircuitBreakerManager()
        output = manager.get_prometheus_metrics()
        assert "circuit_breaker_state" in output
        # No actual metric lines (no {name=...} label lines)
        assert 'name="' not in output

    def test_manager_with_breaker_includes_metrics(self):
        """L801→L802: at least one breaker → loop body taken."""
        manager = NeuroCircuitBreakerManager()
        manager.get_breaker("payment", "order")
        output = manager.get_prometheus_metrics()
        assert 'name="payment:order"' in output


# ---------------------------------------------------------------------------
# get_circuit_breaker — singleton paths
# Branch [828, 829]: singleton not yet created → creates new one
# Branch [828, 830]: singleton already exists → returns existing
# ---------------------------------------------------------------------------

class TestGetCircuitBreaker:
    def test_singleton_created_on_first_call(self):
        """L828→L829: _neuro_circuit_manager is None → creates new instance."""
        import app.neuro_bus.circuit_breaker as cb_module
        original = cb_module._neuro_circuit_manager
        try:
            cb_module._neuro_circuit_manager = None
            mgr = get_circuit_breaker()
            assert isinstance(mgr, NeuroCircuitBreakerManager)
        finally:
            cb_module._neuro_circuit_manager = original

    def test_singleton_returned_on_subsequent_calls(self):
        """L828→L830: _neuro_circuit_manager already set → returns existing instance."""
        import app.neuro_bus.circuit_breaker as cb_module
        original = cb_module._neuro_circuit_manager
        try:
            fake_mgr = NeuroCircuitBreakerManager()
            cb_module._neuro_circuit_manager = fake_mgr
            result = get_circuit_breaker()
            assert result is fake_mgr
        finally:
            cb_module._neuro_circuit_manager = original
