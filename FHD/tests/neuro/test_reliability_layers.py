"""NeuroBus 可靠性层测试：熔断器、去重器、限流器、死信队列、保命通道、SLA、追踪器、重试。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from app.neuro_bus.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    NeuroCircuitBreakerManager,
)
from app.neuro_bus.dead_letter_queue import (
    DeadLetterEntry,
    DeadLetterQueue,
    DeadLetterReason,
    NeuroBusDLQIntegration,
    enqueue_dead_letter,
    get_dead_letter_queue,
    get_dlq_stats,
)
from app.neuro_bus.deduplicator import (
    EventDeduplicator,
    NeuroBusDeduplicator,
    get_deduplicator,
)
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent
from app.neuro_bus.lifeline import (
    CRITICAL_PATH_DOMAINS,
    CRITICAL_PATH_EVENTS,
    Lifeline,
    NeuroLifeline,
    SystemLoad,
    is_critical_path,
)
from app.neuro_bus.rate_limiter import (
    DynamicRateLimiter,
    NeuroRateLimiter,
    RateLimitConfig,
    SlidingWindowCounter,
)
from app.neuro_bus.retry_handler import (
    NeuroRetryHandler,
    RetryConfig,
    RetryContext,
    RetryHandler,
    get_retry_handler,
)
from app.neuro_bus.sla_controller import (
    SLAConfig,
    SLAController,
    SLALevel,
    SLAMonitor,
    SLAViolation,
    with_sla,
)
from app.neuro_bus.tracer import (
    NeuroTracer,
    Span,
    SpanStatus,
    TraceContext,
    current_span,
    current_trace,
)


def _make_event(
    event_type: str = "test.event",
    priority: EventPriority = EventPriority.NORMAL,
    domain: str = "global",
    payload: dict | None = None,
) -> NeuroEvent:
    return NeuroEvent(
        event_type=event_type,
        payload=payload or {"key": "val"},
        priority=priority,
        metadata=EventMetadata(domain=domain),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    def test_can_execute_closed(self):
        cb = CircuitBreaker("test")
        assert cb.can_execute() is True

    def test_opens_after_failures(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_half_open_after_timeout(self):
        config = CircuitBreakerConfig(failure_threshold=2, timeout_seconds=0.01)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_after_successes(self):
        config = CircuitBreakerConfig(
            failure_threshold=2, success_threshold=2, timeout_seconds=0.01
        )
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.can_execute()  # transition to HALF_OPEN
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        config = CircuitBreakerConfig(failure_threshold=2, timeout_seconds=0.01)
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.can_execute()  # HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_max_calls(self):
        config = CircuitBreakerConfig(
            failure_threshold=1, timeout_seconds=0.01, half_open_max_calls=1
        )
        cb = CircuitBreaker("test", config)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.can_execute() is True  # transition to HALF_OPEN, returns True
        assert cb.can_execute() is True  # first HALF_OPEN call (half_open_calls=0 < 1)
        assert cb.can_execute() is False  # second HALF_OPEN call blocked (half_open_calls=1 >= 1)

    def test_execute_success(self):
        cb = CircuitBreaker("test")
        result = cb.execute(lambda: 42)
        assert result == 42

    def test_execute_open_raises(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        with pytest.raises(CircuitBreakerOpen):
            cb.execute(lambda: 1)

    def test_execute_failure_propagates(self):
        cb = CircuitBreaker("test")
        with pytest.raises(ValueError):
            cb.execute(lambda: (_ for _ in ()).throw(ValueError("boom")))

    @pytest.mark.asyncio
    async def test_execute_async_success(self):
        cb = CircuitBreaker("test")

        async def coro():
            return "ok"

        result = await cb.execute_async(coro)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_execute_async_open_raises(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()

        async def coro():
            return "ok"

        with pytest.raises(CircuitBreakerOpen):
            await cb.execute_async(coro)

    def test_record_success_resets_failures_in_closed(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        assert cb.get_stats()["failure_count"] == 2
        cb.record_success()
        # success in CLOSED resets the consecutive-failure counter
        assert cb.get_stats()["failure_count"] == 0
        # two more failures (total would be 4 without reset) stay below threshold=3
        cb.record_failure()
        cb.record_failure()
        assert cb.get_stats()["failure_count"] == 2
        assert cb.state == CircuitState.CLOSED
        # the 3rd consecutive failure now trips the breaker
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_get_stats(self):
        cb = CircuitBreaker("test")
        stats = cb.get_stats()
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0
        assert stats["last_failure"] is None
        assert stats["total_calls"] == 0

    def test_get_stats_reflects_recorded_calls(self):
        cb = CircuitBreaker("billing")
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["name"] == "billing"
        assert stats["successful_calls"] == 2
        assert stats["failed_calls"] == 1
        assert stats["total_calls"] == 3
        # 1 failure out of 3 calls = ~0.333 failure rate
        assert stats["failure_rate"] == pytest.approx(1 / 3)
        # last_failure is only stamped on the transition to OPEN, not on each
        # failure recorded while CLOSED, so it stays None below the threshold.
        assert stats["last_failure"] is None

    def test_last_failure_stamped_only_when_opened(self):
        cb = CircuitBreaker("billing", CircuitBreakerConfig(failure_threshold=2))
        cb.record_failure()
        assert cb.get_stats()["last_failure"] is None  # still CLOSED
        cb.record_failure()  # trips OPEN -> timestamp recorded
        assert cb.state == CircuitState.OPEN
        assert cb.get_stats()["last_failure"] is not None


class TestNeuroCircuitBreakerManager:
    def test_get_breaker_creates_with_domain_config(self):
        mgr = NeuroCircuitBreakerManager()
        b = mgr.get_breaker("payment")
        # payment domain has a tuned config (failure_threshold=3, timeout=30s)
        assert b._config.failure_threshold == 3
        assert b._config.timeout_seconds == 30.0
        # event_type appended to the breaker key
        b2 = mgr.get_breaker("payment", "charge.created")
        assert b2.get_stats()["name"] == "payment:charge.created"

    def test_get_breaker_unknown_domain_uses_default(self):
        mgr = NeuroCircuitBreakerManager()
        b = mgr.get_breaker("totally_unknown")
        assert b._config.failure_threshold == CircuitBreakerConfig().failure_threshold

    def test_get_breaker_cached(self):
        mgr = NeuroCircuitBreakerManager()
        b1 = mgr.get_breaker("payment")
        b2 = mgr.get_breaker("payment")
        assert b1 is b2

    def test_check_delegates(self):
        mgr = NeuroCircuitBreakerManager()
        assert mgr.check("wechat") is True
        # after enough failures the same domain breaker opens and check() returns False
        for _ in range(mgr.DOMAIN_CONFIGS["wechat"].failure_threshold):
            mgr.record_failure("wechat")
        assert mgr.check("wechat") is False

    def test_record_success_resets_failure_count(self):
        mgr = NeuroCircuitBreakerManager()
        mgr.record_failure("intent")
        mgr.record_failure("intent")
        assert mgr.get_all_stats()["intent"]["failure_count"] == 2
        mgr.record_success("intent")
        assert mgr.get_all_stats()["intent"]["failure_count"] == 0

    def test_get_all_stats_aggregates_each_breaker(self):
        mgr = NeuroCircuitBreakerManager()
        mgr.record_success("wechat")
        mgr.record_failure("payment")
        stats = mgr.get_all_stats()
        assert set(stats.keys()) == {"wechat", "payment"}
        assert stats["wechat"]["successful_calls"] == 1
        assert stats["payment"]["failed_calls"] == 1

    def test_get_prometheus_metrics_format(self):
        mgr = NeuroCircuitBreakerManager()
        mgr.record_success("wechat")
        text = mgr.get_prometheus_metrics()
        assert "# TYPE circuit_breaker_state gauge" in text
        # closed breaker exports state gauge 0
        assert 'circuit_breaker_state{name="wechat"} 0' in text
        # open breaker exports state gauge 2
        for _ in range(mgr.DOMAIN_CONFIGS["payment"].failure_threshold):
            mgr.record_failure("payment")
        text = mgr.get_prometheus_metrics()
        assert 'circuit_breaker_state{name="payment"} 2' in text


# ══════════════════════════════════════════════════════════════════════════════
# Deduplicator
# ══════════════════════════════════════════════════════════════════════════════


class TestEventDeduplicator:
    def test_new_event_not_duplicate(self):
        dedup = EventDeduplicator()
        event = _make_event()
        assert dedup.is_duplicate(event) is False

    def test_same_event_is_duplicate(self):
        dedup = EventDeduplicator()
        event = _make_event()
        dedup.mark_processing(event)
        assert dedup.is_duplicate(event) is True

    def test_mark_processing_new(self):
        dedup = EventDeduplicator()
        event = _make_event()
        assert dedup.mark_processing(event) is True

    def test_mark_processing_duplicate(self):
        dedup = EventDeduplicator()
        event = _make_event()
        dedup.mark_processing(event)
        assert dedup.mark_processing(event) is False

    def test_mark_processed(self):
        dedup = EventDeduplicator()
        event = _make_event()
        dedup.mark_processing(event)
        dedup.mark_processed(event, result="ok")
        # After processed, mark_processing returns False (already processed)
        assert dedup.mark_processing(event) is False

    def test_get_result(self):
        dedup = EventDeduplicator()
        event = _make_event()
        dedup.mark_processing(event)
        dedup.mark_processed(event, result="done")
        assert dedup.get_result(event) == "done"

    def test_get_result_not_processed(self):
        dedup = EventDeduplicator()
        event = _make_event()
        dedup.mark_processing(event)
        assert dedup.get_result(event) is None

    def test_remove(self):
        dedup = EventDeduplicator()
        event = _make_event()
        dedup.mark_processing(event)
        dedup.remove(event)
        assert dedup.is_duplicate(event) is False

    def test_ttl_expiry(self):
        dedup = EventDeduplicator(ttl_seconds=0.01)
        event = _make_event()
        dedup.mark_processing(event)
        time.sleep(0.02)
        assert dedup.is_duplicate(event) is False

    def test_max_entries_eviction(self):
        dedup = EventDeduplicator(max_entries=2)
        e1 = _make_event("a")
        e2 = _make_event("b")
        e3 = _make_event("c")
        dedup.mark_processing(e1)
        dedup.mark_processing(e2)
        dedup.mark_processing(e3)  # capacity hit -> evicts oldest (e1)
        # cap is enforced exactly at max_entries
        assert dedup.get_stats()["total_entries"] == 2
        # e1 (oldest) was evicted, so it is no longer a duplicate
        assert dedup.is_duplicate(e1) is False
        # e2/e3 survive and are still seen as duplicates
        assert dedup.is_duplicate(e2) is True
        assert dedup.is_duplicate(e3) is True

    def test_get_stats(self):
        dedup = EventDeduplicator()
        e1 = _make_event("a")
        e2 = _make_event("b")
        dedup.mark_processing(e1)
        dedup.mark_processing(e2)
        dedup.mark_processed(e1, result="r")
        stats = dedup.get_stats()
        assert stats["total_entries"] == 2
        assert stats["processing"] == 1  # only e2 still in-flight
        assert stats["processed"] == 1  # e1 done
        assert stats["max_entries"] == 10000


class TestNeuroBusDeduplicator:
    def test_check_and_acquire(self):
        dedup = NeuroBusDeduplicator()
        event = _make_event()
        assert dedup.check_and_acquire(event) is True
        assert dedup.check_and_acquire(event) is False

    def test_release(self):
        dedup = NeuroBusDeduplicator()
        event = _make_event()
        dedup.check_and_acquire(event)
        dedup.release(event, result="ok")
        assert dedup.get_cached_result(event) == "ok"

    def test_is_duplicate(self):
        dedup = NeuroBusDeduplicator()
        event = _make_event()
        assert dedup.is_duplicate(event) is False
        dedup.check_and_acquire(event)
        assert dedup.is_duplicate(event) is True


# ══════════════════════════════════════════════════════════════════════════════
# Rate Limiter
# ══════════════════════════════════════════════════════════════════════════════


class TestSlidingWindowCounter:
    def test_add_and_count(self):
        counter = SlidingWindowCounter(window_size=1.0)
        counter.add()
        counter.add()
        assert counter.count() == 2

    def test_reset(self):
        counter = SlidingWindowCounter()
        counter.add()
        counter.reset()
        assert counter.count() == 0

    def test_expiry(self):
        counter = SlidingWindowCounter(window_size=0.01)
        counter.add()
        time.sleep(0.02)
        assert counter.count() == 0


class TestDynamicRateLimiter:
    def test_allow_normal(self):
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        event = _make_event()
        assert limiter.allow(event) is True

    def test_reject_over_burst(self):
        # burst_size=2, low rps so tokens don't refill within the test
        config = RateLimitConfig(burst_size=2, requests_per_second=0.001)
        limiter = DynamicRateLimiter(default_config=config)
        results = [limiter.allow(_make_event()) for _ in range(3)]
        # exactly the first 2 pass (burst), the 3rd is rejected
        assert results == [True, True, False]
        stats = limiter.get_stats()
        assert stats["allowed"] == 2
        assert stats["rejected"] == 1

    def test_priority_whitelist(self):
        config = RateLimitConfig(burst_size=1)
        limiter = DynamicRateLimiter(default_config=config)
        # CRITICAL events should always pass
        for _ in range(5):
            assert limiter.allow(_make_event(priority=EventPriority.CRITICAL)) is True

    def test_domain_limit(self):
        config = RateLimitConfig(burst_size=1)
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        limiter.set_domain_limit("payment", config)
        # First passes
        assert limiter.allow(_make_event(domain="payment")) is True
        # Second should be rejected
        assert limiter.allow(_make_event(domain="payment")) is False

    def test_event_type_limit(self):
        config = RateLimitConfig(burst_size=1)
        limiter = DynamicRateLimiter(default_config=RateLimitConfig(burst_size=100))
        limiter.set_event_limit("test.event", config)
        assert limiter.allow(_make_event("test.event")) is True
        assert limiter.allow(_make_event("test.event")) is False

    def test_get_stats(self):
        limiter = DynamicRateLimiter()
        limiter.allow(_make_event("a.evt", domain="d1"))
        stats = limiter.get_stats()
        assert stats["allowed"] == 1
        assert stats["rejected"] == 0
        # the buckets touched by the call are recorded in stats
        assert "d1" in stats["domains"]
        assert "a.evt" in stats["event_types"]


class TestNeuroRateLimiter:
    def test_check_rate(self):
        limiter = NeuroRateLimiter()
        event = _make_event()
        assert limiter.check_rate(event) is True

    def test_payment_domain_stricter_than_intent(self):
        # NeuroRateLimiter pre-configures payment (burst 10) stricter than intent (burst 100).
        limiter = NeuroRateLimiter()
        # exhaust payment domain burst (10) -> 11th rejected
        payment_results = [
            limiter.check_rate(_make_event("payment.charge", domain="payment")) for _ in range(11)
        ]
        assert payment_results.count(True) == 10
        assert payment_results[-1] is False

    def test_get_stats(self):
        limiter = NeuroRateLimiter()
        limiter.check_rate(_make_event(domain="wechat"))
        stats = limiter.get_stats()
        assert stats["allowed"] == 1
        assert stats["rejected"] == 0
        assert stats["config_snapshot"]["burst_size"] == 40  # default domain burst


# ══════════════════════════════════════════════════════════════════════════════
# Dead Letter Queue
# ══════════════════════════════════════════════════════════════════════════════


class TestDeadLetterQueue:
    def test_enqueue(self):
        dlq = DeadLetterQueue()
        event = _make_event("order.failed")
        entry_id = dlq.enqueue(
            event, DeadLetterReason.RETRY_EXHAUSTED, "max retries", retry_count=3
        )
        assert entry_id.startswith("dlq-")
        entry = dlq.dequeue(entry_id)
        assert entry.entry_id == entry_id
        assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED
        assert entry.error_message == "max retries"
        assert entry.retry_count == 3
        assert entry.original_event.event_type == "order.failed"
        assert dlq.get_stats()["current_size"] == 1

    def test_dequeue_not_found(self):
        dlq = DeadLetterQueue()
        assert dlq.dequeue("nonexistent") is None

    def test_remove(self):
        dlq = DeadLetterQueue()
        event = _make_event()
        eid = dlq.enqueue(event, DeadLetterReason.UNRECOVERABLE, "err", 0)
        assert dlq.remove(eid) is True
        assert dlq.remove(eid) is False

    def test_replay(self):
        dlq = DeadLetterQueue()
        replayed = []
        dlq.on_replay(lambda e: replayed.append(e))
        event = _make_event()
        eid = dlq.enqueue(event, DeadLetterReason.TIMEOUT, "timeout", 1)
        assert dlq.replay(eid) == (True, "")
        assert len(replayed) == 1

    def test_replay_not_found(self):
        dlq = DeadLetterQueue()
        assert dlq.replay("nonexistent") == (False, "entry_not_found")

    def test_replay_all(self):
        dlq = DeadLetterQueue()
        dlq.on_replay(lambda e: None)
        dlq.enqueue(_make_event("a"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.enqueue(_make_event("b"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        count = dlq.replay_all()
        assert count == 2

    def test_replay_all_with_filter(self):
        dlq = DeadLetterQueue()
        dlq.on_replay(lambda e: None)
        dlq.enqueue(_make_event("order.created"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.enqueue(_make_event("payment.process"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        count = dlq.replay_all(event_type="order.created")
        assert count == 1

    def test_resolve_manually(self):
        dlq = DeadLetterQueue()
        event = _make_event()
        eid = dlq.enqueue(event, DeadLetterReason.UNRECOVERABLE, "err", 0)
        assert dlq.resolve_manually(eid, "fixed", "admin") is True
        assert dlq.dequeue(eid) is None

    def test_resolve_manually_not_found(self):
        dlq = DeadLetterQueue()
        assert dlq.resolve_manually("nonexistent", "fixed", "admin") is False

    def test_get_entries_by_reason(self):
        dlq = DeadLetterQueue()
        dlq.enqueue(_make_event(), DeadLetterReason.TIMEOUT, "timeout", 1)
        dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        entries = dlq.get_entries_by_reason(DeadLetterReason.TIMEOUT)
        assert len(entries) == 1

    def test_get_entries_by_event_type(self):
        dlq = DeadLetterQueue()
        dlq.enqueue(_make_event("order.created"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.enqueue(_make_event("payment.process"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        entries = dlq.get_entries_by_event_type("order.created")
        assert len(entries) == 1

    def test_get_stats(self):
        dlq = DeadLetterQueue()
        dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.enqueue(_make_event(), DeadLetterReason.TIMEOUT, "slow", 1)
        stats = dlq.get_stats()
        assert stats["current_size"] == 3
        assert stats["total_entries"] == 3
        # by_reason counts grouped by enum value
        assert stats["by_reason"]["unrecoverable"] == 2
        assert stats["by_reason"]["timeout"] == 1

    def test_alert_callback(self):
        dlq = DeadLetterQueue()
        alerts = []
        dlq.on_alert(lambda e: alerts.append(e))
        eid = dlq.enqueue(_make_event("order.fail"), DeadLetterReason.UNRECOVERABLE, "boom", 0)
        # callback fires exactly once and receives the enqueued entry
        assert len(alerts) == 1
        assert alerts[0].entry_id == eid
        assert alerts[0].error_message == "boom"
        # alert envelope carries the in-window failure count
        assert alerts[0].metadata["alert_count_in_window"] == 1

    def test_alert_callback_suppressed_for_same_group(self):
        # default suppress window is 5 min, threshold 1: a 2nd same-group failure
        # within the window is suppressed (no second alert).
        dlq = DeadLetterQueue()
        alerts = []
        dlq.on_alert(lambda e: alerts.append(e))
        dlq.enqueue(_make_event("order.fail"), DeadLetterReason.UNRECOVERABLE, "1", 0)
        dlq.enqueue(_make_event("order.fail"), DeadLetterReason.UNRECOVERABLE, "2", 0)
        assert len(alerts) == 1

    def test_max_size_eviction(self):
        dlq = DeadLetterQueue(max_size=1)
        eid_a = dlq.enqueue(_make_event("a"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        eid_b = dlq.enqueue(_make_event("b"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        # capacity is exactly 1: the older entry (a) is evicted, the newer (b) kept
        assert dlq.get_stats()["current_size"] == 1
        assert dlq.dequeue(eid_a) is None
        assert dlq.dequeue(eid_b) is not None

    def test_entry_to_dict(self):
        dlq = DeadLetterQueue()
        event = _make_event("payment.declined", payload={"amount": 9})
        eid = dlq.enqueue(event, DeadLetterReason.UNRECOVERABLE, "err", retry_count=2)
        d = dlq.dequeue(eid).to_dict()
        assert d["entry_id"] == eid
        assert d["reason"] == "unrecoverable"  # enum -> value
        assert d["retry_count"] == 2
        assert d["error_message"] == "err"
        assert d["original_event"]["event_type"] == "payment.declined"
        assert d["original_event"]["payload"] == {"amount": 9}

    def test_entry_age_seconds_increases(self):
        dlq = DeadLetterQueue()
        eid = dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        entry = dlq.dequeue(eid)
        age1 = entry.age_seconds
        time.sleep(0.02)
        age2 = entry.age_seconds
        # age is monotonically non-decreasing and reflects elapsed wall-clock
        assert age1 >= 0
        assert age2 > age1


class TestNeuroBusDLQIntegration:
    def test_handle_failure_retry_exhausted(self):
        dlq = DeadLetterQueue()
        integration = NeuroBusDLQIntegration(dlq)
        event = _make_event()
        # retry_count >= max_retries (3) classifies as RETRY_EXHAUSTED regardless of error type
        eid = integration.handle_failure(event, Exception("fail"), retry_count=3)
        entry = dlq.dequeue(eid)
        assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED
        assert entry.retry_count == 3
        assert entry.error_message == "fail"

    def test_handle_failure_unrecoverable_default(self):
        dlq = DeadLetterQueue()
        integration = NeuroBusDLQIntegration(dlq)
        # generic error below retry limit -> UNRECOVERABLE
        eid = integration.handle_failure(_make_event(), RuntimeError("boom"), retry_count=0)
        entry = dlq.dequeue(eid)
        assert entry.reason == DeadLetterReason.UNRECOVERABLE

    def test_handle_failure_timeout(self):
        dlq = DeadLetterQueue()
        integration = NeuroBusDLQIntegration(dlq)
        eid = integration.handle_failure(_make_event(), TimeoutError("slow"), retry_count=0)
        entry = dlq.dequeue(eid)
        assert entry.reason == DeadLetterReason.TIMEOUT

    def test_handle_failure_invalid_payload(self):
        dlq = DeadLetterQueue()
        integration = NeuroBusDLQIntegration(dlq)
        eid = integration.handle_failure(_make_event(), ValueError("bad"), retry_count=0)
        entry = dlq.dequeue(eid)
        assert entry.reason == DeadLetterReason.INVALID_PAYLOAD

    def test_setup_replay_to_bus(self):
        dlq = DeadLetterQueue()
        integration = NeuroBusDLQIntegration(dlq)
        mock_bus = MagicMock()
        integration.setup_replay_to_bus(mock_bus)
        event = _make_event("payment.retry")
        dlq.enqueue(event, DeadLetterReason.UNRECOVERABLE, "err", 0)
        count = dlq.replay_all()
        assert count == 1
        # the exact original event is republished to the bus
        mock_bus.publish.assert_called_once_with(event)


class TestDLQGlobals:
    def test_enqueue_dead_letter(self, monkeypatch):
        import app.neuro_bus.dead_letter_queue as dlq_mod

        monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
        eid = enqueue_dead_letter(_make_event(), "timeout", "err", 2)
        assert eid.startswith("dlq-")
        # the global singleton now holds the entry with the parsed reason
        entry = get_dead_letter_queue().dequeue(eid)
        assert entry.reason == DeadLetterReason.TIMEOUT
        assert entry.retry_count == 2

    def test_enqueue_dead_letter_bad_reason_falls_back(self, monkeypatch):
        import app.neuro_bus.dead_letter_queue as dlq_mod

        monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
        # unknown reason string falls back to UNRECOVERABLE (does not raise)
        eid = enqueue_dead_letter(_make_event(), "not_a_real_reason", "err", 0)
        entry = get_dead_letter_queue().dequeue(eid)
        assert entry.reason == DeadLetterReason.UNRECOVERABLE

    def test_get_dlq_stats(self, monkeypatch):
        import app.neuro_bus.dead_letter_queue as dlq_mod

        monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
        enqueue_dead_letter(_make_event(), "unrecoverable", "err", 0)
        stats = get_dlq_stats()
        assert stats["current_size"] == 1
        assert stats["by_reason"]["unrecoverable"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Lifeline
# ══════════════════════════════════════════════════════════════════════════════


class TestLifeline:
    def test_normal_load_allows_all(self):
        ll = Lifeline()
        assert (
            ll.should_process(_make_event(priority=EventPriority.BACKGROUND), queue_depth=0) is True
        )

    def test_emergency_drops_low_priority(self):
        ll = Lifeline(
            queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80
        )
        ll._last_check = 0  # bypass check interval
        ll.check_system_load(queue_depth=200)  # EMERGENCY
        assert ll.should_process(_make_event(priority=EventPriority.LOW), queue_depth=200) is False
        assert (
            ll.should_process(_make_event(priority=EventPriority.CRITICAL), queue_depth=200) is True
        )

    def test_load_change_callback(self):
        ll = Lifeline(
            queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80
        )
        ll._last_check = 0  # bypass check interval
        changes = []
        ll.set_load_change_callback(lambda old, new: changes.append((old, new)))
        ll.check_system_load(queue_depth=200)
        assert len(changes) == 1
        assert changes[0][1] == SystemLoad.EMERGENCY

    def test_check_system_load_normal(self):
        ll = Lifeline()
        assert ll.check_system_load(queue_depth=0) == SystemLoad.NORMAL

    def test_check_system_load_elevated(self):
        ll = Lifeline(
            queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80
        )
        ll._last_check = 0  # bypass check interval
        result = ll.check_system_load(queue_depth=40)
        assert result == SystemLoad.ELEVATED

    def test_get_emergency_recommendations(self):
        ll = Lifeline()
        # NORMAL -> no recommendations
        assert ll.get_emergency_recommendations() == []
        # HIGH -> scaling guidance
        ll._current_load = SystemLoad.HIGH
        assert "Scale up worker instances" in ll.get_emergency_recommendations()
        # EMERGENCY -> only-critical messaging
        ll._current_load = SystemLoad.EMERGENCY
        recs = ll.get_emergency_recommendations()
        assert "CRITICAL: Emergency response needed" in recs
        assert "Only critical events are being processed" in recs

    def test_get_stats_tracks_dropped_and_protected(self):
        ll = Lifeline(
            queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80
        )
        ll._last_check = 0
        ll.check_system_load(queue_depth=200)  # EMERGENCY: only CRITICAL survives
        # a low-priority event gets dropped, a critical one protected
        ll.should_process(_make_event("low.evt", priority=EventPriority.LOW), queue_depth=200)
        ll.should_process(_make_event("crit.evt", priority=EventPriority.CRITICAL), queue_depth=200)
        stats = ll.get_stats()
        assert stats["current_load"] == "emergency"
        assert stats["dropped_events"]["low.evt"] == 1
        assert stats["protected_events"]["crit.evt"] == 1
        assert stats["total_dropped"] == 1
        assert stats["total_protected"] == 1


class TestNeuroLifeline:
    def test_no_queue_provider_allows(self):
        nl = NeuroLifeline()
        assert nl.check_event(_make_event()) is True

    def test_with_queue_provider(self):
        nl = NeuroLifeline()
        nl.set_queue_depth_provider(lambda: 0)
        assert nl.check_event(_make_event()) is True

    def test_with_queue_provider_drops_low_priority_when_overloaded(self):
        nl = NeuroLifeline()
        nl.set_queue_depth_provider(lambda: 100_000)  # massively overloaded -> EMERGENCY
        nl._lifeline._last_check = 0
        # low priority dropped, critical passes through
        assert nl.check_event(_make_event(priority=EventPriority.LOW)) is False
        assert nl.check_event(_make_event(priority=EventPriority.CRITICAL)) is True

    def test_critical_only_mode(self):
        nl = NeuroLifeline()
        assert nl.check_critical_only_mode() is False
        # push load to EMERGENCY -> critical-only mode engages
        nl.set_queue_depth_provider(lambda: 100_000)
        nl._lifeline._last_check = 0
        nl.check_event(_make_event(priority=EventPriority.CRITICAL))
        assert nl.check_critical_only_mode() is True

    def test_get_recommendations_empty_when_normal(self):
        nl = NeuroLifeline()
        # NORMAL load yields no emergency recommendations
        assert nl.get_recommendations() == []

    def test_get_recommendations_nonempty_under_high_load(self):
        nl = NeuroLifeline()
        nl._lifeline._current_load = SystemLoad.EMERGENCY
        recs = nl.get_recommendations()
        assert "CRITICAL: Emergency response needed" in recs


class TestIsCriticalPath:
    def test_critical_domain(self):
        event = _make_event(domain="safety")
        assert is_critical_path(event) is True

    def test_critical_event_type(self):
        event = _make_event("payment.process")
        assert is_critical_path(event) is True

    def test_critical_priority(self):
        event = _make_event(priority=EventPriority.CRITICAL)
        assert is_critical_path(event) is True

    def test_non_critical(self):
        event = _make_event(priority=EventPriority.LOW)
        assert is_critical_path(event) is False


# ══════════════════════════════════════════════════════════════════════════════
# SLA Controller
# ══════════════════════════════════════════════════════════════════════════════


class TestSLAConfig:
    def test_get_for_level(self):
        assert SLAConfig.get_for_level(SLALevel.REFLEX).target_ms == 1.0
        assert SLAConfig.get_for_level(SLALevel.SUBCONSCIOUS).target_ms == 10.0
        assert SLAConfig.get_for_level(SLALevel.CONSCIOUS).target_ms == 200.0


class TestSLAMonitor:
    def test_check_ok(self):
        monitor = SLAMonitor(SLAConfig.REFLEX, "test_op")
        result = monitor.check()
        assert result["status"] == "ok"
        assert result["operation"] == "test_op"
        assert result["target_ms"] == 1.0
        assert result["max_ms"] == 5.0
        assert result["elapsed_ms"] >= 0

    def test_finish_returns_report(self):
        monitor = SLAMonitor(SLAConfig.REFLEX, "test_op")
        result = monitor.finish()
        # finishing immediately is within the 5ms REFLEX budget
        assert result["status"] == "ok"
        assert result["operation"] == "test_op"
        assert result["elapsed_ms"] < SLAConfig.REFLEX.max_ms

    def test_finish_violated_when_slow(self):
        # REFLEX max_ms = 5ms; back-date the start so elapsed >> max
        monitor = SLAMonitor(SLAConfig.REFLEX, "slow_op")
        monitor._start_time -= 1.0  # 1s ago -> ~1000ms elapsed
        result = monitor.finish()
        assert result["status"] == "violated"
        assert monitor.is_violated() is True

    def test_is_violated(self):
        monitor = SLAMonitor(SLAConfig.REFLEX, "test_op")
        assert monitor.is_violated() is False


class TestSLAController:
    def test_determine_sla_level_reflex(self):
        ctrl = SLAController()
        event = _make_event("intent.reflex_triggered")
        assert ctrl.determine_sla_level(event) == SLALevel.REFLEX

    def test_determine_sla_level_subconscious(self):
        ctrl = SLAController()
        event = _make_event("background.task", priority=EventPriority.LOW)
        assert ctrl.determine_sla_level(event) == SLALevel.SUBCONSCIOUS

    def test_determine_sla_level_conscious(self):
        ctrl = SLAController()
        event = _make_event("order.process")
        assert ctrl.determine_sla_level(event) == SLALevel.CONSCIOUS

    def test_start_and_finish_monitoring(self):
        ctrl = SLAController()
        event = _make_event("order.process", domain="sales")
        monitor = ctrl.start_monitoring(event)
        # CONSCIOUS level (default) sets event timeout to its max_ms
        assert monitor._operation_name == "order.process@sales"
        assert event.metadata.timeout_ms == int(SLAConfig.CONSCIOUS.max_ms)
        # one active monitor while in flight
        assert ctrl.get_stats()["active_monitors"] == 1
        result = ctrl.finish_monitoring(event.metadata.event_id)
        assert result["status"] == "ok"
        # finishing removes it from the active set
        assert ctrl.get_stats()["active_monitors"] == 0

    def test_finish_monitoring_not_found(self):
        ctrl = SLAController()
        assert ctrl.finish_monitoring("nonexistent") is None

    def test_finish_monitoring_violation_increments_count(self):
        ctrl = SLAController()
        event = _make_event("intent.reflex_triggered")  # REFLEX, 5ms budget
        ctrl.start_monitoring(event)
        # back-date so the monitor is well past its max
        ctrl._active_monitors[event.metadata.event_id]._start_time -= 1.0
        result = ctrl.finish_monitoring(event.metadata.event_id)
        assert result["status"] == "violated"
        assert ctrl.get_stats()["total_violations"] == 1

    def test_check_violations_lists_active_breaches(self):
        ctrl = SLAController()
        ok_event = _make_event("order.process")
        bad_event = _make_event("intent.reflex_triggered")
        ctrl.start_monitoring(ok_event)
        ctrl.start_monitoring(bad_event)
        # only the back-dated reflex monitor is violating right now
        ctrl._active_monitors[bad_event.metadata.event_id]._start_time -= 1.0
        violations = ctrl.check_violations()
        assert len(violations) == 1
        assert violations[0]["event_id"] == bad_event.metadata.event_id

    def test_get_stats(self):
        ctrl = SLAController()
        stats = ctrl.get_stats()
        assert stats["active_monitors"] == 0
        assert stats["total_violations"] == 0
        assert stats["total_warnings"] == 0


class TestWithSLADecorator:
    @pytest.mark.asyncio
    async def test_within_sla(self):
        @with_sla(SLALevel.CONSCIOUS)
        async def fast_op():
            return "done"

        result = await fast_op()
        assert result == "done"

    @pytest.mark.asyncio
    async def test_sla_violation(self):
        @with_sla(SLALevel.REFLEX)
        async def slow_op():
            await asyncio.sleep(0.1)
            return "done"

        with pytest.raises(SLAViolation):
            await slow_op()

    @pytest.mark.asyncio
    async def test_sla_with_fallback(self):
        @with_sla(SLALevel.REFLEX, fallback=lambda: "fallback")
        async def slow_op():
            await asyncio.sleep(0.1)
            return "done"

        result = await slow_op()
        assert result == "fallback"


# ══════════════════════════════════════════════════════════════════════════════
# Tracer
# ══════════════════════════════════════════════════════════════════════════════


class TestSpan:
    def test_finish(self):
        span = Span(span_id="s1", trace_id="t1", parent_id=None, name="op", start_time=time.time())
        span.finish(SpanStatus.OK)
        assert span.end_time is not None
        assert span.status == SpanStatus.OK

    def test_add_event(self):
        span = Span(span_id="s1", trace_id="t1", parent_id=None, name="op", start_time=time.time())
        span.add_event("test_event", {"key": "val"})
        assert len(span.events) == 1

    def test_set_tag(self):
        span = Span(span_id="s1", trace_id="t1", parent_id=None, name="op", start_time=time.time())
        span.set_tag("env", "test")
        assert span.tags["env"] == "test"

    def test_duration_ms(self):
        span = Span(span_id="s1", trace_id="t1", parent_id=None, name="op", start_time=time.time())
        assert span.duration_ms is None
        span.finish()
        assert span.duration_ms is not None
        assert span.duration_ms >= 0

    def test_to_dict(self):
        span = Span(span_id="s1", trace_id="t1", parent_id="p1", name="op", start_time=time.time())
        span.set_tag("env", "test")
        span.add_event("started")
        span.finish(SpanStatus.ERROR)
        d = span.to_dict()
        assert d["span_id"] == "s1"
        assert d["trace_id"] == "t1"
        assert d["parent_id"] == "p1"
        assert d["name"] == "op"
        assert d["status"] == "error"  # enum serialized to its value
        assert d["tags"] == {"env": "test"}
        assert d["duration_ms"] is not None
        assert len(d["events"]) == 1


class TestTraceContext:
    def test_context_manager(self):
        previous_trace = current_trace.get()
        previous_span = current_span.get()
        with TraceContext(trace_id="t1", span_id="s1") as ctx:
            assert current_trace.get() == "t1"
            assert current_span.get() == "s1"
        assert current_trace.get() == previous_trace
        assert current_span.get() == previous_span


class TestNeuroTracer:
    def test_start_span(self):
        tracer = NeuroTracer()
        span = tracer.start_span("test_op")
        assert span.name == "test_op"
        assert span.trace_id is not None

    def test_start_span_with_parent(self):
        tracer = NeuroTracer()
        parent = tracer.start_span("parent")
        child = tracer.start_span("child", trace_id=parent.trace_id, parent_id=parent.span_id)
        assert child.parent_id == parent.span_id
        assert child.trace_id == parent.trace_id

    def test_end_span(self):
        tracer = NeuroTracer()
        span = tracer.start_span("test_op")
        tracer.end_span(span.span_id, SpanStatus.OK)
        assert tracer.get_span(span.span_id).status == SpanStatus.OK

    def test_end_span_sets_status_and_end_time(self):
        tracer = NeuroTracer()
        span = tracer.start_span("op")
        assert span.end_time is None
        tracer.end_span(span.span_id, SpanStatus.ERROR)
        stored = tracer.get_span(span.span_id)
        assert stored.status == SpanStatus.ERROR
        assert stored.end_time is not None

    def test_end_span_not_found_is_noop(self):
        tracer = NeuroTracer()
        # ending an unknown span must not raise and must not create a span
        tracer.end_span("nonexistent", SpanStatus.OK)
        assert tracer.get_span("nonexistent") is None
        assert tracer.get_stats()["total_spans"] == 0

    def test_get_trace(self):
        tracer = NeuroTracer()
        s1 = tracer.start_span("op1")
        s2 = tracer.start_span("op2", trace_id=s1.trace_id)
        trace = tracer.get_trace(s1.trace_id)
        assert len(trace) == 2

    def test_trace_event(self):
        tracer = NeuroTracer()
        event = _make_event()
        span = tracer.trace_event(event, "process")
        assert span.name == "test.event.process"

    def test_inject_trace_context(self):
        tracer = NeuroTracer()
        with TraceContext(trace_id="t1", span_id="s1"):
            event = _make_event()
            tracer.inject_trace_context(event)
            assert event.metadata.trace_id == "t1"

    def test_get_current_trace_id(self):
        from app.neuro_bus.tracer import current_trace

        current_trace.set(None)  # reset any leaked context
        tracer = NeuroTracer()
        assert tracer.get_current_trace_id() is None
        with TraceContext(trace_id="t1"):
            assert tracer.get_current_trace_id() == "t1"

    def test_get_stats(self):
        tracer = NeuroTracer()
        tracer.start_span("op1")
        stats = tracer.get_stats()
        assert stats["total_spans"] == 1
        assert stats["active_spans"] == 1

    def test_max_spans_cleanup_evicts_oldest(self):
        tracer = NeuroTracer(max_spans=5)
        spans = [tracer.start_span(f"op_{i}") for i in range(10)]
        total = tracer.get_stats()["total_spans"]
        # cleanup keeps the count bounded (well under the 10 created)
        assert total < 10
        assert total <= 6  # max_spans (5) + at most one over before cleanup fires
        # the most recently created span is always retained
        assert tracer.get_span(spans[-1].span_id) is not None
        # the very first span was evicted by the oldest-first cleanup
        assert tracer.get_span(spans[0].span_id) is None


# ══════════════════════════════════════════════════════════════════════════════
# Retry Handler
# ══════════════════════════════════════════════════════════════════════════════


class TestRetryConfig:
    def test_defaults(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 0.1
        assert config.exponential_base == 2.0
        assert config.jitter is True
        # default retryable set covers transient transport errors
        assert ConnectionError in config.retryable_exceptions
        assert TimeoutError in config.retryable_exceptions
        assert ValueError not in config.retryable_exceptions


class TestRetryContext:
    def test_should_retry_within_limit(self):
        ctx = RetryContext(RetryConfig(max_retries=3), "test")
        assert ctx.should_retry(ConnectionError("fail")) is True

    def test_should_retry_exhausted(self):
        ctx = RetryContext(RetryConfig(max_retries=1), "test")
        ctx.should_retry(ConnectionError("fail"))
        assert ctx.should_retry(ConnectionError("fail")) is False

    def test_should_retry_non_retryable(self):
        ctx = RetryContext(RetryConfig(), "test")
        assert ctx.should_retry(ValueError("bad")) is False

    def test_get_delay_exponential_no_jitter(self):
        ctx = RetryContext(RetryConfig(base_delay=0.1, exponential_base=2.0, jitter=False), "test")
        # 1st retry: attempt becomes 1 -> base * 2^0 = 0.1
        ctx.should_retry(ConnectionError("fail"))
        assert ctx.get_delay() == pytest.approx(0.1)
        # 2nd retry: attempt becomes 2 -> base * 2^1 = 0.2
        ctx.should_retry(ConnectionError("fail"))
        assert ctx.get_delay() == pytest.approx(0.2)

    def test_get_delay_capped_at_max(self):
        ctx = RetryContext(
            RetryConfig(base_delay=10.0, max_delay=15.0, max_retries=5, jitter=False), "test"
        )
        # attempt 1 -> 10.0; attempt 2 -> 20.0 capped to 15.0
        ctx.should_retry(ConnectionError("x"))
        ctx.should_retry(ConnectionError("x"))
        assert ctx.get_delay() == pytest.approx(15.0)

    def test_get_report_success_path(self):
        rc = RetryContext(RetryConfig(), "test")
        rc.should_retry(ConnectionError("fail"))  # attempt -> 1
        rc.record_success()
        report = rc.get_report()
        assert report["operation"] == "test"
        assert report["success"] is True
        # attempts = _attempt (1) + 1 for the successful call = 2
        assert report["attempts"] == 2
        assert report["max_retries"] == 3
        assert report["last_error"] == "fail"

    def test_get_report_no_attempts(self):
        rc = RetryContext(RetryConfig(), "fresh")
        report = rc.get_report()
        assert report["success"] is False
        assert report["attempts"] == 0
        assert report["last_error"] is None
        assert report["total_delay_sec"] == 0.0


class TestRetryHandler:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        handler = RetryHandler()

        async def op():
            return 42

        result = await handler.execute(op, operation_name="test")
        assert result == 42

    @pytest.mark.asyncio
    async def test_execute_retry_then_success(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "ok"

        handler = RetryHandler(RetryConfig(max_retries=5, base_delay=0.01, jitter=False))
        result = await handler.execute(flaky, operation_name="flaky")
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_execute_exhausted(self):
        async def always_fail():
            raise ConnectionError("fail")

        handler = RetryHandler(RetryConfig(max_retries=2, base_delay=0.01))
        with pytest.raises(ConnectionError):
            await handler.execute(always_fail, operation_name="always_fail")

    def test_execute_sync_success(self):
        handler = RetryHandler(RetryConfig(base_delay=0.01))
        result = handler.execute_sync(lambda: 42, operation_name="test")
        assert result == 42

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        retries = []
        errors = []

        async def fail():
            raise ConnectionError("fail")

        handler = RetryHandler(RetryConfig(max_retries=2, base_delay=0.01))
        with pytest.raises(ConnectionError):
            await handler.execute(
                fail,
                operation_name="test",
                on_retry=lambda e, n: (retries.append(n), errors.append(e)),
            )
        # max_retries=2 -> callback invoked for attempt 1 and 2 (then exhausted, re-raises)
        assert retries == [1, 2]
        assert all(isinstance(e, ConnectionError) for e in errors)
        assert [str(e) for e in errors] == ["fail", "fail"]


class TestNeuroRetryHandler:
    def test_get_handler_uses_domain_config(self):
        handler = NeuroRetryHandler()
        h = handler.get_handler("payment")
        # payment domain config: max_retries=2 (fast-fail)
        assert h._config.max_retries == 2
        assert h._config.base_delay == 0.5
        # cached: same instance returned on repeat
        assert handler.get_handler("payment") is h

    def test_get_handler_unknown_domain_uses_default(self):
        handler = NeuroRetryHandler()
        h = handler.get_handler("unknown_domain")
        # default config has max_retries=3
        assert h._config.max_retries == 3

    def test_get_handler_ai_service_more_retries(self):
        handler = NeuroRetryHandler()
        h = handler.get_handler("ai_service")
        assert h._config.max_retries == 5
        assert h._config.max_delay == 30.0

    @pytest.mark.asyncio
    async def test_execute_for_event(self):
        handler = NeuroRetryHandler()

        async def op():
            return "ok"

        result = await handler.execute_for_event("wechat", op)
        assert result == "ok"
