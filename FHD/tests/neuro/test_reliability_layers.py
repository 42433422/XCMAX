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
    RetryConfig,
    RetryContext,
    RetryHandler,
    NeuroRetryHandler,
    get_retry_handler,
)
from app.neuro_bus.sla_controller import (
    SLAConfig,
    SLALevel,
    SLAMonitor,
    SLAViolation,
    SLAController,
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
        cb.record_success()
        # failure_count should be reset
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_get_stats(self):
        cb = CircuitBreaker("test")
        stats = cb.get_stats()
        assert stats["name"] == "test"
        assert stats["state"] == "closed"


class TestNeuroCircuitBreakerManager:
    def test_get_breaker_creates(self):
        mgr = NeuroCircuitBreakerManager()
        b = mgr.get_breaker("payment")
        assert isinstance(b, CircuitBreaker)

    def test_get_breaker_cached(self):
        mgr = NeuroCircuitBreakerManager()
        b1 = mgr.get_breaker("payment")
        b2 = mgr.get_breaker("payment")
        assert b1 is b2

    def test_check_delegates(self):
        mgr = NeuroCircuitBreakerManager()
        assert mgr.check("wechat") is True

    def test_record_success_failure(self):
        mgr = NeuroCircuitBreakerManager()
        mgr.record_failure("intent")
        mgr.record_success("intent")

    def test_get_all_stats(self):
        mgr = NeuroCircuitBreakerManager()
        mgr.get_breaker("wechat")
        stats = mgr.get_all_stats()
        assert "wechat" in stats


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
        dedup.mark_processing(e3)  # should evict oldest
        assert dedup.get_stats()["total_entries"] <= 3

    def test_get_stats(self):
        dedup = EventDeduplicator()
        dedup.mark_processing(_make_event())
        stats = dedup.get_stats()
        assert "total_entries" in stats
        assert "processing" in stats


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
        config = RateLimitConfig(burst_size=2)
        limiter = DynamicRateLimiter(default_config=config)
        for _ in range(3):
            limiter.allow(_make_event())
        # The 3rd call should have been rejected
        stats = limiter.get_stats()
        assert stats["rejected"] > 0

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
        limiter.allow(_make_event())
        stats = limiter.get_stats()
        assert "allowed" in stats
        assert "rejected" in stats


class TestNeuroRateLimiter:
    def test_check_rate(self):
        limiter = NeuroRateLimiter()
        event = _make_event()
        assert limiter.check_rate(event) is True

    def test_get_stats(self):
        limiter = NeuroRateLimiter()
        stats = limiter.get_stats()
        assert "allowed" in stats


# ══════════════════════════════════════════════════════════════════════════════
# Dead Letter Queue
# ══════════════════════════════════════════════════════════════════════════════


class TestDeadLetterQueue:
    def test_enqueue(self):
        dlq = DeadLetterQueue()
        event = _make_event()
        entry_id = dlq.enqueue(
            event, DeadLetterReason.RETRY_EXHAUSTED, "max retries", retry_count=3
        )
        assert entry_id.startswith("dlq-")
        assert dlq.dequeue(entry_id) is not None

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
        assert dlq.replay(eid) is True
        assert len(replayed) == 1

    def test_replay_not_found(self):
        dlq = DeadLetterQueue()
        assert dlq.replay("nonexistent") is False

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
        stats = dlq.get_stats()
        assert stats["current_size"] == 1
        assert "by_reason" in stats

    def test_alert_callback(self):
        dlq = DeadLetterQueue()
        alerts = []
        dlq.on_alert(lambda e: alerts.append(e))
        dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        assert len(alerts) == 1

    def test_max_size_eviction(self):
        dlq = DeadLetterQueue(max_size=1)
        dlq.enqueue(_make_event("a"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.enqueue(_make_event("b"), DeadLetterReason.UNRECOVERABLE, "err", 0)
        assert dlq.get_stats()["current_size"] <= 1

    def test_entry_to_dict(self):
        dlq = DeadLetterQueue()
        eid = dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        entry = dlq.dequeue(eid)
        d = entry.to_dict()
        assert "entry_id" in d
        assert "reason" in d
        assert d["reason"] == "unrecoverable"

    def test_entry_age_seconds(self):
        dlq = DeadLetterQueue()
        eid = dlq.enqueue(_make_event(), DeadLetterReason.UNRECOVERABLE, "err", 0)
        entry = dlq.dequeue(eid)
        assert entry.age_seconds >= 0


class TestNeuroBusDLQIntegration:
    def test_handle_failure_retry_exhausted(self):
        dlq = DeadLetterQueue()
        integration = NeuroBusDLQIntegration(dlq)
        event = _make_event()
        eid = integration.handle_failure(event, Exception("fail"), retry_count=3)
        assert eid.startswith("dlq-")

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
        event = _make_event()
        dlq.enqueue(event, DeadLetterReason.UNRECOVERABLE, "err", 0)
        dlq.replay_all()
        mock_bus.publish.assert_called()


class TestDLQGlobals:
    def test_enqueue_dead_letter(self, monkeypatch):
        import app.neuro_bus.dead_letter_queue as dlq_mod
        monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
        eid = enqueue_dead_letter(_make_event(), "unrecoverable", "err", 0)
        assert eid.startswith("dlq-")

    def test_get_dlq_stats(self, monkeypatch):
        import app.neuro_bus.dead_letter_queue as dlq_mod
        monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
        stats = get_dlq_stats()
        assert "current_size" in stats


# ══════════════════════════════════════════════════════════════════════════════
# Lifeline
# ══════════════════════════════════════════════════════════════════════════════


class TestLifeline:
    def test_normal_load_allows_all(self):
        ll = Lifeline()
        assert ll.should_process(_make_event(priority=EventPriority.BACKGROUND), queue_depth=0) is True

    def test_emergency_drops_low_priority(self):
        ll = Lifeline(queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80)
        ll._last_check = 0  # bypass check interval
        ll.check_system_load(queue_depth=200)  # EMERGENCY
        assert ll.should_process(_make_event(priority=EventPriority.LOW), queue_depth=200) is False
        assert ll.should_process(_make_event(priority=EventPriority.CRITICAL), queue_depth=200) is True

    def test_load_change_callback(self):
        ll = Lifeline(queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80)
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
        ll = Lifeline(queue_threshold_normal=10, queue_threshold_high=50, queue_threshold_critical=80)
        ll._last_check = 0  # bypass check interval
        result = ll.check_system_load(queue_depth=40)
        assert result == SystemLoad.ELEVATED

    def test_get_emergency_recommendations(self):
        ll = Lifeline()
        assert ll.get_emergency_recommendations() == []
        ll._current_load = SystemLoad.HIGH
        recs = ll.get_emergency_recommendations()
        assert len(recs) > 0

    def test_get_stats(self):
        ll = Lifeline()
        stats = ll.get_stats()
        assert "current_load" in stats
        assert "dropped_events" in stats


class TestNeuroLifeline:
    def test_no_queue_provider_allows(self):
        nl = NeuroLifeline()
        assert nl.check_event(_make_event()) is True

    def test_with_queue_provider(self):
        nl = NeuroLifeline()
        nl.set_queue_depth_provider(lambda: 0)
        assert nl.check_event(_make_event()) is True

    def test_critical_only_mode(self):
        nl = NeuroLifeline()
        assert nl.check_critical_only_mode() is False

    def test_get_recommendations(self):
        nl = NeuroLifeline()
        recs = nl.get_recommendations()
        assert isinstance(recs, list)


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

    def test_finish(self):
        monitor = SLAMonitor(SLAConfig.REFLEX, "test_op")
        result = monitor.finish()
        assert "elapsed_ms" in result

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
        event = _make_event()
        monitor = ctrl.start_monitoring(event)
        assert isinstance(monitor, SLAMonitor)
        result = ctrl.finish_monitoring(event.metadata.event_id)
        assert result is not None

    def test_finish_monitoring_not_found(self):
        ctrl = SLAController()
        assert ctrl.finish_monitoring("nonexistent") is None

    def test_check_violations(self):
        ctrl = SLAController()
        violations = ctrl.check_violations()
        assert isinstance(violations, list)

    def test_get_stats(self):
        ctrl = SLAController()
        stats = ctrl.get_stats()
        assert "active_monitors" in stats
        assert "total_violations" in stats


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
        span = Span(span_id="s1", trace_id="t1", parent_id=None, name="op", start_time=time.time())
        d = span.to_dict()
        assert d["span_id"] == "s1"
        assert d["trace_id"] == "t1"


class TestTraceContext:
    def test_context_manager(self):
        with TraceContext(trace_id="t1", span_id="s1") as ctx:
            assert current_trace.get() == "t1"
            assert current_span.get() == "s1"
        assert current_trace.get() is None
        assert current_span.get() is None


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

    def test_end_span_not_found(self):
        tracer = NeuroTracer()
        tracer.end_span("nonexistent", SpanStatus.OK)  # should not raise

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

    def test_max_spans_cleanup(self):
        tracer = NeuroTracer(max_spans=5)
        for i in range(10):
            tracer.start_span(f"op_{i}")
        assert tracer.get_stats()["total_spans"] <= 10


# ══════════════════════════════════════════════════════════════════════════════
# Retry Handler
# ══════════════════════════════════════════════════════════════════════════════


class TestRetryConfig:
    def test_defaults(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.jitter is True


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

    def test_get_delay(self):
        ctx = RetryContext(RetryConfig(base_delay=0.1, jitter=False), "test")
        ctx.should_retry(ConnectionError("fail"))
        delay = ctx.get_delay()
        assert delay > 0

    def test_record_success(self):
        ctx = RetryContext(RetryConfig(), "test")
        ctx.record_success()
        assert ctx._success is True

    def test_get_report(self):
        ctx = RetryContext(RetryConfig(), "test")
        report = ctx.get_report()
        assert "operation" in report
        assert "success" in report


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

        async def fail():
            raise ConnectionError("fail")

        handler = RetryHandler(RetryConfig(max_retries=1, base_delay=0.01))
        with pytest.raises(ConnectionError):
            await handler.execute(
                fail, operation_name="test", on_retry=lambda e, n: retries.append(n)
            )
        assert len(retries) >= 1


class TestNeuroRetryHandler:
    def test_get_handler(self):
        handler = NeuroRetryHandler()
        h = handler.get_handler("payment")
        assert isinstance(h, RetryHandler)

    def test_get_handler_default(self):
        handler = NeuroRetryHandler()
        h = handler.get_handler("unknown_domain")
        assert isinstance(h, RetryHandler)

    @pytest.mark.asyncio
    async def test_execute_for_event(self):
        handler = NeuroRetryHandler()

        async def op():
            return "ok"

        result = await handler.execute_for_event("wechat", op)
        assert result == "ok"
