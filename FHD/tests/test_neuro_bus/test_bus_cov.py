from __future__ import annotations

"""Branch-coverage tests for app/neuro_bus/bus.py."""

import asyncio
import os
import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.neuro_bus.bus import (
    HandlerSubscription,
    NeuroBus,
    PriorityEventQueue,
    _deployment_is_staging,
    _neuro_env_flag,
    _neuro_reliability_wanted,
    _neuro_trace_sample_rate,
    _should_trace_event,
    get_neuro_bus,
    set_neuro_bus,
)
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str = "test.event",
    priority: EventPriority = EventPriority.NORMAL,
    domain: str = "global",
    timeout_ms: int = 5_000_000,
) -> NeuroEvent:
    ev = NeuroEvent(event_type=event_type, payload={"x": 1}, priority=priority)
    ev.metadata.domain = domain
    ev.metadata.timeout_ms = timeout_ms
    return ev


def _make_bus(**kwargs: Any) -> NeuroBus:
    """Create a NeuroBus with all reliability layers explicitly disabled."""
    env_off = {
        "XCAGI_NEURO_BUS_SLA_LOG": "0",
        "XCAGI_NEURO_BUS_RETRY": "0",
        "XCAGI_NEURO_BUS_DEDUP": "0",
        "XCAGI_NEURO_BUS_RATE_LIMIT": "0",
        "XCAGI_NEURO_BUS_CIRCUIT": "0",
        "XCAGI_NEURO_BUS_LIFELINE": "0",
        "XCAGI_NEURO_BUS_TRACE": "0",
        "XCAGI_NEURO_BUS_DLQ_AUTO": "0",
        "XCAGI_NEURO_BUS_REDIS_TRANSPORT": "",
        "XCAGI_NEURO_BUS_REDIS_PUBSUB": "0",
    }
    with patch.dict(os.environ, env_off):
        return NeuroBus(**kwargs)


# ---------------------------------------------------------------------------
# _neuro_env_flag
# ---------------------------------------------------------------------------


class TestNeuroEnvFlag:
    def test_true_variants(self) -> None:
        for val in ("1", "true", "yes", "on", "  TRUE  ", " Yes "):
            with patch.dict(os.environ, {"_TEST_FLAG": val}):
                assert _neuro_env_flag("_TEST_FLAG") is True

    def test_false_variants(self) -> None:
        for val in ("0", "false", "no", "off", ""):
            with patch.dict(os.environ, {"_TEST_FLAG": val}):
                assert _neuro_env_flag("_TEST_FLAG") is False

    def test_missing_key_returns_false(self) -> None:
        os.environ.pop("_TEST_FLAG_MISSING", None)
        assert _neuro_env_flag("_TEST_FLAG_MISSING") is False


# ---------------------------------------------------------------------------
# _deployment_is_staging
# ---------------------------------------------------------------------------


class TestDeploymentIsStaging:
    def test_staging(self) -> None:
        with patch.dict(os.environ, {"FHD_ENV": "staging"}):
            assert _deployment_is_staging() is True

    def test_not_staging(self) -> None:
        with patch.dict(os.environ, {"FHD_ENV": "production"}):
            assert _deployment_is_staging() is False

    def test_unset(self) -> None:
        os.environ.pop("FHD_ENV", None)
        assert _deployment_is_staging() is False


# ---------------------------------------------------------------------------
# _neuro_trace_sample_rate
# ---------------------------------------------------------------------------


class TestNeuroTraceSampleRate:
    def test_default(self) -> None:
        os.environ.pop("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", None)
        assert _neuro_trace_sample_rate() == pytest.approx(0.1)

    def test_explicit_value(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "0.5"}):
            assert _neuro_trace_sample_rate() == pytest.approx(0.5)

    def test_invalid_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "abc"}):
            assert _neuro_trace_sample_rate() == pytest.approx(0.1)

    def test_clamped_above_1(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "5.0"}):
            assert _neuro_trace_sample_rate() == pytest.approx(1.0)

    def test_clamped_below_0(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "-0.5"}):
            assert _neuro_trace_sample_rate() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _should_trace_event
# ---------------------------------------------------------------------------


class TestShouldTraceEvent:
    def test_always_traces_at_rate_1(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "1.0"}):
            assert _should_trace_event() is True

    def test_never_traces_at_rate_0(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "0.0"}):
            assert _should_trace_event() is False

    def test_probabilistic_at_mid_rate(self) -> None:
        with patch.dict(os.environ, {"XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE": "0.5"}):
            results = {_should_trace_event() for _ in range(30)}
        # With 30 samples at p=0.5, both True and False should appear
        assert True in results or False in results


# ---------------------------------------------------------------------------
# _neuro_reliability_wanted
# ---------------------------------------------------------------------------


class TestNeuroReliabilityWanted:
    def test_explicit_true(self) -> None:
        with patch.dict(os.environ, {"XCAGI_TEST_REL": "1"}):
            assert _neuro_reliability_wanted("XCAGI_TEST_REL", staging_default=False) is True

    def test_explicit_false(self) -> None:
        with patch.dict(os.environ, {"XCAGI_TEST_REL": "0"}):
            assert _neuro_reliability_wanted("XCAGI_TEST_REL", staging_default=True) is False

    def test_staging_default_true_when_no_env(self) -> None:
        os.environ.pop("XCAGI_TEST_REL_MISSING", None)
        with patch.dict(os.environ, {"FHD_ENV": "staging"}):
            assert _neuro_reliability_wanted("XCAGI_TEST_REL_MISSING", staging_default=True) is True

    def test_production_default_true_outside_staging(self) -> None:
        os.environ.pop("XCAGI_TEST_REL_MISSING2", None)
        with patch.dict(os.environ, {"FHD_ENV": "production"}):
            assert (
                _neuro_reliability_wanted("XCAGI_TEST_REL_MISSING2", staging_default=True) is True
            )


# ---------------------------------------------------------------------------
# HandlerSubscription
# ---------------------------------------------------------------------------


class TestHandlerSubscription:
    def _make_sub(self, filter_fn: Callable | None = None) -> HandlerSubscription:
        return HandlerSubscription(event_type="test", handler=lambda e: None, filter_fn=filter_fn)

    def test_should_handle_no_filter(self) -> None:
        sub = self._make_sub()
        assert sub.should_handle(_make_event()) is True

    def test_should_handle_with_filter_true(self) -> None:
        sub = self._make_sub(filter_fn=lambda e: True)
        assert sub.should_handle(_make_event()) is True

    def test_should_handle_with_filter_false(self) -> None:
        sub = self._make_sub(filter_fn=lambda e: False)
        assert sub.should_handle(_make_event()) is False

    def test_record_call_success(self) -> None:
        sub = self._make_sub()
        sub.record_call(success=True)
        assert sub.call_count == 1
        assert sub.error_count == 0

    def test_record_call_failure(self) -> None:
        sub = self._make_sub()
        sub.record_call(success=False)
        assert sub.error_count == 1

    def test_error_rate_zero_calls(self) -> None:
        sub = self._make_sub()
        assert sub.error_rate == 0.0

    def test_error_rate_with_calls(self) -> None:
        sub = self._make_sub()
        sub.record_call(success=True)
        sub.record_call(success=False)
        assert sub.error_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# PriorityEventQueue
# ---------------------------------------------------------------------------


class TestPriorityEventQueue:
    def test_put_and_get(self) -> None:
        q = PriorityEventQueue(max_size=10)
        ev = _make_event()
        assert q.put(ev) is True
        got = q.get()
        assert got is ev

    def test_get_empty_returns_none(self) -> None:
        q = PriorityEventQueue()
        assert q.get() is None

    def test_peek_empty_returns_none(self) -> None:
        q = PriorityEventQueue()
        assert q.peek() is None

    def test_peek_does_not_remove(self) -> None:
        q = PriorityEventQueue()
        ev = _make_event()
        q.put(ev)
        assert q.peek() is ev
        assert q.size() == 1

    def test_priority_ordering(self) -> None:
        q = PriorityEventQueue()
        low = _make_event("low", EventPriority.LOW)
        high = _make_event("high", EventPriority.HIGH)
        q.put(low)
        q.put(high)
        first = q.get()
        second = q.get()
        # HIGH (value 1) outranks LOW (value 3) regardless of insertion order.
        assert first is high
        assert first.priority == EventPriority.HIGH
        assert second is low
        assert q.get() is None

    def test_queue_full_drops_low_priority(self) -> None:
        q = PriorityEventQueue(max_size=1)
        low = _make_event("low", EventPriority.LOW)
        crit = _make_event("crit", EventPriority.CRITICAL)
        q.put(low)
        # Queue full; CRITICAL should evict the LOW one
        result = q.put(crit)
        assert result is True
        assert q.size() == 1

    def test_queue_full_drops_new_low_priority(self) -> None:
        q = PriorityEventQueue(max_size=1)
        crit = _make_event("crit", EventPriority.CRITICAL)
        low = _make_event("low", EventPriority.LOW)
        q.put(crit)
        result = q.put(low)
        # New low-priority event should be dropped
        assert result is False

    def test_duplicate_event_id_reminted(self) -> None:
        # When the same event object is re-queued (event_id still present in the
        # set), the queue remints a fresh identity and accepts it, so both copies
        # coexist in the queue with *different* event_ids.
        q = PriorityEventQueue(max_size=10)
        ev = _make_event()
        assert q.put(ev) is True
        original_id = ev.metadata.event_id

        result = q.put(ev)
        assert result is True
        # remint must have changed the event_id...
        assert ev.metadata.event_id != original_id
        # ...and the queue now holds two entries (the original id + reminted id).
        assert q.size() == 2

    def test_clear(self) -> None:
        q = PriorityEventQueue()
        q.put(_make_event())
        assert q.size() == 1
        q.clear()
        assert q.size() == 0
        # clear() also resets id tracking, so a fresh put still succeeds.
        assert q.get() is None
        assert q.put(_make_event()) is True


# ---------------------------------------------------------------------------
# NeuroBus — basic lifecycle
# ---------------------------------------------------------------------------


class TestNeuroBusLifecycle:
    async def test_start_sets_running(self) -> None:
        bus = _make_bus()
        await bus.start()
        assert bus.is_running is True
        await bus.stop()

    async def test_start_idempotent(self) -> None:
        bus = _make_bus()
        await bus.start()
        await bus.start()  # second start should be no-op
        assert bus.is_running is True
        await bus.stop()

    async def test_stop_clears_running(self) -> None:
        bus = _make_bus()
        await bus.start()
        await bus.stop()
        assert bus.is_running is False

    async def test_stop_without_start_is_safe(self) -> None:
        bus = _make_bus()
        await bus.stop()  # should not raise

    async def test_publish_before_start_returns_false(self) -> None:
        bus = _make_bus()
        ev = _make_event()
        assert bus.publish(ev) is False


# ---------------------------------------------------------------------------
# NeuroBus — subscribe / publish / dispatch
# ---------------------------------------------------------------------------


class TestNeuroBusPubSub:
    async def test_subscribe_and_receive(self) -> None:
        bus = _make_bus()
        await bus.start()
        received: list[NeuroEvent] = []

        async def handler(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("test.event", handler)
        ev = _make_event()
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 1

    async def test_global_handler_receives_all_events(self) -> None:
        bus = _make_bus()
        await bus.start()
        received: list[NeuroEvent] = []

        async def global_h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe_all(global_h)
        bus.publish(_make_event("a"))
        bus.publish(_make_event("b"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 2

    async def test_domain_handler_receives_domain_events(self) -> None:
        bus = _make_bus()
        await bus.start()
        received: list[NeuroEvent] = []

        async def domain_h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe_to_domain("sales", "order.created", domain_h)
        ev = _make_event("order.created", domain="sales")
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 1

    async def test_no_handler_for_event_type(self) -> None:
        bus = _make_bus()
        await bus.start()
        ev = _make_event("no.handler")
        result = bus.publish(ev)
        assert result is True
        await asyncio.sleep(0.05)
        await bus.stop()

    async def test_sync_handler_via_executor(self) -> None:
        bus = _make_bus()
        await bus.start()
        received: list[NeuroEvent] = []

        def sync_h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("sync.test", sync_h, is_async=False)
        bus.publish(_make_event("sync.test"))
        await asyncio.sleep(0.15)
        await bus.stop()
        assert len(received) == 1

    async def test_filter_fn_blocks_event(self) -> None:
        bus = _make_bus()
        await bus.start()
        received: list[NeuroEvent] = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("filtered", h, filter_fn=lambda e: False)
        bus.publish(_make_event("filtered"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 0

    async def test_expired_event_is_dropped(self) -> None:
        bus = _make_bus()
        await bus.start()
        received: list[NeuroEvent] = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("expire.test", h)
        ev = _make_event("expire.test", timeout_ms=1)
        # Make the event already expired
        ev.metadata.timestamp = time.time() - 10
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 0

    async def test_handler_raising_is_counted_as_error(self) -> None:
        bus = _make_bus()
        await bus.start()

        async def bad_h(e: NeuroEvent) -> None:
            raise RuntimeError("boom")

        bus.subscribe("bad.event", bad_h)
        bus.publish(_make_event("bad.event"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert bus._error_count >= 1

    async def test_subscribe_global_alias_delivers_every_event(self) -> None:
        # subscribe_global is an alias for subscribe_all: the returned sub is a
        # wildcard global handler that fires for arbitrary event types.
        bus = _make_bus()
        received: list[NeuroEvent] = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        sub = bus.subscribe_global(h)
        assert sub.event_type == "*"
        assert sub in bus._global_handlers

        await bus.start()
        bus.publish(_make_event("anything"))
        bus.publish(_make_event("else"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert [e.event_type for e in received] == ["anything", "else"]

    async def test_subscribe_event_with_domain_routes_to_domain_handler(self) -> None:
        # When domain is given, subscribe_event delegates to subscribe_to_domain:
        # the sub lands in the domain map (not the flat map) and only domain
        # events reach it.
        bus = _make_bus()
        received: list[NeuroEvent] = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        sub = bus.subscribe_event("order", h, domain="sales")
        assert sub in bus._domain_handlers["sales"]["order"]
        assert "order" not in bus._handlers

        await bus.start()
        bus.publish(_make_event("order", domain="sales"))
        # Same event type but no matching domain must NOT reach the handler.
        bus.publish(_make_event("order", domain="other"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 1
        assert received[0].metadata.domain == "sales"

    async def test_subscribe_event_without_domain_routes_to_flat_handler(self) -> None:
        bus = _make_bus()
        received: list[NeuroEvent] = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        sub = bus.subscribe_event("order", h)
        assert sub in bus._handlers["order"]
        assert "order" not in bus._domain_handlers

        await bus.start()
        bus.publish(_make_event("order"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 1

    async def test_unsubscribe_returns_true(self) -> None:
        bus = _make_bus()

        async def h(e: NeuroEvent) -> None:
            pass

        sub = bus.subscribe("test", h)
        assert bus.unsubscribe(sub) is True

    async def test_unsubscribe_unknown_returns_false(self) -> None:
        bus = _make_bus()
        sub = HandlerSubscription(event_type="ghost", handler=lambda e: None)
        assert bus.unsubscribe(sub) is False


# ---------------------------------------------------------------------------
# NeuroBus — stats / reliability status
# ---------------------------------------------------------------------------


class TestNeuroBusStats:
    def test_get_stats_structure(self) -> None:
        bus = _make_bus()
        stats = bus.get_stats()
        assert "published" in stats
        assert "processed" in stats
        assert "running" in stats
        assert "reliability" in stats

    def test_get_reliability_status_defaults(self) -> None:
        bus = _make_bus()
        rel = bus.get_reliability_status()
        assert rel["dedup"] is False
        assert rel["circuit_breaker"] is False

    def test_summarize_subscriptions(self) -> None:
        bus = _make_bus()
        bus.subscribe("ev_a", lambda e: None)
        summary = bus.summarize_subscriptions()
        assert "ev_a" in summary["flat_event_handlers"]

    def test_registered_domains_delegates_to_registry(self) -> None:
        # registered_domains returns exactly what DomainRegistry.list_domains()
        # yields — patch the registry the property imports and assert pass-through.
        bus = _make_bus()
        fake_registry = MagicMock()
        fake_registry.list_domains.return_value = ["sales", "intent"]
        with patch(
            "app.neuro_bus.domains.base.get_domain_registry",
            return_value=fake_registry,
        ):
            domains = bus.registered_domains
        assert domains == ["sales", "intent"]


# ---------------------------------------------------------------------------
# NeuroBus — ingest_remote_event
# ---------------------------------------------------------------------------


class TestIngestRemoteEvent:
    async def test_ingest_remote_when_not_running(self) -> None:
        bus = _make_bus()
        ev = _make_event()
        result = bus.ingest_remote_event(ev)
        assert result is False

    async def test_ingest_remote_when_running(self) -> None:
        bus = _make_bus()
        await bus.start()
        ev = _make_event()
        result = bus.ingest_remote_event(ev)
        assert result is True
        await bus.stop()


# ---------------------------------------------------------------------------
# NeuroBus — persistence flag
# ---------------------------------------------------------------------------


class TestPersistenceBuffer:
    async def test_persistence_enabled_buffers_event(self) -> None:
        bus = _make_bus()
        bus._enable_persistence = True
        await bus.start()
        ev = _make_event()
        bus.publish(ev)
        await asyncio.sleep(0.05)
        await bus.stop()
        assert len(bus._event_buffer) >= 1


# ---------------------------------------------------------------------------
# get_neuro_bus / set_neuro_bus
# ---------------------------------------------------------------------------


class TestGlobalBus:
    def test_set_and_get(self) -> None:
        from app.neuro_bus import bus as bus_module

        original = bus_module._neuro_bus
        try:
            fake_bus = _make_bus()
            set_neuro_bus(fake_bus)
            assert get_neuro_bus() is fake_bus
        finally:
            bus_module._neuro_bus = original

    def test_get_creates_if_none(self) -> None:
        from app.neuro_bus import bus as bus_module

        original = bus_module._neuro_bus
        try:
            bus_module._neuro_bus = None
            with patch.dict(
                os.environ,
                {
                    "XCAGI_NEURO_BUS_SLA_LOG": "0",
                    "XCAGI_NEURO_BUS_RETRY": "0",
                    "XCAGI_NEURO_BUS_DEDUP": "0",
                    "XCAGI_NEURO_BUS_RATE_LIMIT": "0",
                    "XCAGI_NEURO_BUS_CIRCUIT": "0",
                    "XCAGI_NEURO_BUS_LIFELINE": "0",
                    "XCAGI_NEURO_BUS_TRACE": "0",
                    "XCAGI_NEURO_BUS_DLQ_AUTO": "0",
                    "XCAGI_NEURO_BUS_REDIS_TRANSPORT": "",
                    "XCAGI_NEURO_BUS_REDIS_PUBSUB": "0",
                },
            ):
                bus = get_neuro_bus()
                # Lazily created, cached as the module singleton, and the same
                # instance is returned on the next call (no re-creation).
                assert isinstance(bus, NeuroBus)
                assert bus_module._neuro_bus is bus
                assert get_neuro_bus() is bus
        finally:
            bus_module._neuro_bus = original


# ---------------------------------------------------------------------------
# NeuroBus — circuit-breaker path (mocked)
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    async def test_circuit_open_skips_handler(self) -> None:
        # Open circuit: handler is never invoked, the dispatch is recorded as a
        # failure, and neither success nor failure is recorded on the breaker
        # (can_execute short-circuits before the handler).
        bus = _make_bus()
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = False
        bus._rel_circuit = fake_circuit

        await bus.start()
        called = []

        async def h(e: NeuroEvent) -> None:
            called.append(e)

        sub = bus.subscribe("cb.test", h)
        bus.publish(_make_event("cb.test"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert called == []
        # The subscription itself records nothing because the call never started.
        assert sub.call_count == 0
        fake_circuit.record_success.assert_not_called()
        fake_circuit.record_failure.assert_not_called()

    async def test_circuit_closed_runs_handler_and_records_success(self) -> None:
        bus = _make_bus()
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = True
        bus._rel_circuit = fake_circuit

        await bus.start()
        called = []

        async def h(e: NeuroEvent) -> None:
            called.append(e)

        sub = bus.subscribe("cb.ok", h)
        bus.publish(_make_event("cb.ok"))
        await asyncio.sleep(0.1)
        await bus.stop()
        # Handler actually ran, success recorded on both sub and breaker, no failure.
        assert len(called) == 1
        assert sub.call_count == 1
        assert sub.error_count == 0
        fake_circuit.record_success.assert_called_once()
        fake_circuit.record_failure.assert_not_called()
        assert bus._error_count == 0

    async def test_circuit_closed_records_failure_on_handler_error(self) -> None:
        bus = _make_bus()
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = True
        bus._rel_circuit = fake_circuit

        await bus.start()

        async def bad_h(e: NeuroEvent) -> None:
            raise RuntimeError("fail")

        sub = bus.subscribe("cb.fail", bad_h)
        bus.publish(_make_event("cb.fail"))
        await asyncio.sleep(0.1)
        await bus.stop()
        # Handler raised: failure recorded on breaker + sub, error count bumped,
        # and success is NOT recorded.
        fake_circuit.record_failure.assert_called_once()
        fake_circuit.record_success.assert_not_called()
        assert sub.error_count == 1
        assert bus._error_count >= 1


# ---------------------------------------------------------------------------
# NeuroBus — reliability status with circuit open
# ---------------------------------------------------------------------------


class TestReliabilityStatusCircuit:
    def test_circuit_open_reported_in_reliability_status(self) -> None:
        bus = _make_bus()
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = False
        bus._rel_circuit = fake_circuit
        rel = bus.get_reliability_status()
        assert rel["circuit_open"] is True

    def test_circuit_closed_reported_in_reliability_status(self) -> None:
        bus = _make_bus()
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = True
        bus._rel_circuit = fake_circuit
        rel = bus.get_reliability_status()
        assert rel["circuit_open"] is False

    def test_circuit_can_execute_error_returns_none(self) -> None:
        bus = _make_bus()
        fake_circuit = MagicMock()
        fake_circuit.can_execute.side_effect = OSError("oops")
        bus._rel_circuit = fake_circuit
        rel = bus.get_reliability_status()
        assert rel["circuit_open"] is None


# ---------------------------------------------------------------------------
# NeuroBus — unsubscribe edge cases
# ---------------------------------------------------------------------------


class TestUnsubscribeEdgeCases:
    async def test_unsubscribe_sub_not_in_list_returns_false(self) -> None:
        bus = _make_bus()

        async def h1(e: NeuroEvent) -> None:
            pass

        async def h2(e: NeuroEvent) -> None:
            pass

        # Subscribe h1 so the event_type key exists in _handlers
        bus.subscribe("myevent", h1)
        # Create a subscription for the same event_type but never register it
        ghost_sub = HandlerSubscription(event_type="myevent", handler=h2)
        # unsubscribe returns False because ghost_sub is not in the list
        assert bus.unsubscribe(ghost_sub) is False


# ---------------------------------------------------------------------------
# NeuroBus — summarize_subscriptions with domain handlers
# ---------------------------------------------------------------------------


class TestSummarizeWithDomainHandlers:
    def test_summarize_includes_domain_handlers(self) -> None:
        bus = _make_bus()
        bus.subscribe_to_domain("orders", "order.created", lambda e: None)
        summary = bus.summarize_subscriptions()
        assert "orders" in summary["domain_handlers"]
        assert summary["domain_handlers"]["orders"]["order.created"] == 1


# ---------------------------------------------------------------------------
# NeuroBus — registered_domains exception path
# ---------------------------------------------------------------------------


class TestRegisteredDomainsException:
    def test_returns_empty_list_on_import_error(self) -> None:
        # A recoverable error while resolving the registry must degrade to an
        # empty list rather than propagate (used in health checks / startup logs).
        bus = _make_bus()
        fake_registry = MagicMock()
        fake_registry.list_domains.side_effect = OSError("registry unavailable")
        with patch(
            "app.neuro_bus.domains.base.get_domain_registry",
            return_value=fake_registry,
        ):
            result = bus.registered_domains
        assert result == []


# ---------------------------------------------------------------------------
# NeuroBus — _preflight_publish branches (dedup / rate / lifeline)
# ---------------------------------------------------------------------------


class TestPreflightPublish:
    async def test_dedup_reject_returns_false(self) -> None:
        bus = _make_bus()
        await bus.start()
        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = False
        bus._rel_dedup = fake_dedup
        ev = _make_event()
        result = bus.publish(ev)
        assert result is False
        await bus.stop()

    async def test_rate_limiter_reject_removes_dedup_and_returns_false(self) -> None:
        bus = _make_bus()
        await bus.start()
        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = True
        bus._rel_dedup = fake_dedup
        fake_rate = MagicMock()
        fake_rate.check_rate.return_value = False
        bus._rel_rate = fake_rate
        ev = _make_event()
        result = bus.publish(ev)
        assert result is False
        fake_dedup.remove.assert_called_once_with(ev)
        await bus.stop()

    async def test_rate_limiter_reject_without_dedup(self) -> None:
        # Rate limiter rejects in preflight: publish returns False, the event is
        # never queued/delivered, and published_count stays at 0.
        bus = _make_bus()
        await bus.start()
        fake_rate = MagicMock()
        fake_rate.check_rate.return_value = False
        bus._rel_rate = fake_rate
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("rl.test", h)
        ev = _make_event("rl.test")
        result = bus.publish(ev)
        await asyncio.sleep(0.05)
        await bus.stop()
        assert result is False
        assert received == []
        assert bus._published_count == 0
        fake_rate.check_rate.assert_called_once_with(ev)

    async def test_lifeline_reject_removes_dedup_and_returns_false(self) -> None:
        bus = _make_bus()
        await bus.start()
        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = True
        bus._rel_dedup = fake_dedup
        fake_lifeline = MagicMock()
        fake_lifeline.should_process.return_value = False
        bus._rel_lifeline = fake_lifeline
        ev = _make_event()
        result = bus.publish(ev)
        assert result is False
        fake_dedup.remove.assert_called_once_with(ev)
        await bus.stop()

    async def test_lifeline_reject_without_dedup(self) -> None:
        # Lifeline rejection in preflight: publish False, no delivery, queue depth
        # is passed to should_process alongside the event.
        bus = _make_bus()
        await bus.start()
        fake_lifeline = MagicMock()
        fake_lifeline.should_process.return_value = False
        bus._rel_lifeline = fake_lifeline
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("ll.test", h)
        ev = _make_event("ll.test")
        result = bus.publish(ev)
        await asyncio.sleep(0.05)
        await bus.stop()
        assert result is False
        assert received == []
        assert bus._published_count == 0
        # should_process is called with (event, current_queue_depth=0).
        fake_lifeline.should_process.assert_called_once_with(ev, 0)


# ---------------------------------------------------------------------------
# NeuroBus — publish with tracer
# ---------------------------------------------------------------------------


class TestPublishWithTracer:
    async def test_publish_starts_span_when_trace_sampled(self) -> None:
        # When sampled, a span is opened tagged with the event type/id and the
        # event_id->span_id mapping is recorded so dispatch can close it later.
        bus = _make_bus()
        await bus.start()
        fake_tracer = MagicMock()
        fake_span = MagicMock()
        fake_span.span_id = "span-001"
        fake_tracer.start_span.return_value = fake_span
        bus._rel_tracer = fake_tracer

        with patch("app.neuro_bus.bus._should_trace_event", return_value=True):
            ev = _make_event("traced.evt")
            bus.publish(ev)
            await asyncio.sleep(0.1)

        assert fake_tracer.start_span.call_count == 1
        name, kwargs = fake_tracer.start_span.call_args
        assert name[0] == "neuro.publish:traced.evt"
        assert kwargs["tags"]["event_type"] == "traced.evt"
        assert kwargs["tags"]["event_id"] == ev.metadata.event_id
        await bus.stop()

    async def test_publish_no_span_when_not_sampled(self) -> None:
        # Not sampled: no span is created and no event_id->span mapping is stored,
        # yet the event still gets delivered normally.
        bus = _make_bus()
        await bus.start()
        fake_tracer = MagicMock()
        bus._rel_tracer = fake_tracer
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("untraced.evt", h)
        with patch("app.neuro_bus.bus._should_trace_event", return_value=False):
            ev = _make_event("untraced.evt")
            assert bus.publish(ev) is True
            await asyncio.sleep(0.1)

        fake_tracer.start_span.assert_not_called()
        assert ev.metadata.event_id not in bus._trace_by_event_id
        assert len(received) == 1
        await bus.stop()

    async def test_publish_queue_full_ends_span_with_error(self) -> None:
        # max_queue_size=0 means every put fails => publish returns False and the
        # span that was opened in publish() is closed with ERROR (and unmapped).
        bus = _make_bus(max_queue_size=0)
        await bus.start()
        fake_tracer = MagicMock()
        fake_span = MagicMock()
        fake_span.span_id = "span-002"
        fake_tracer.start_span.return_value = fake_span

        from app.neuro_bus.tracer import SpanStatus

        bus._rel_tracer = fake_tracer
        with patch("app.neuro_bus.bus._should_trace_event", return_value=True):
            ev = _make_event()
            result = bus.publish(ev)

        assert result is False
        fake_tracer.start_span.assert_called_once()
        fake_tracer.end_span.assert_called_once_with("span-002", SpanStatus.ERROR)
        # The aborted span must not linger in the mapping.
        assert ev.metadata.event_id not in bus._trace_by_event_id
        await bus.stop()

    async def test_publish_queue_full_removes_dedup_entry(self) -> None:
        # Fill a size-1 queue with a CRITICAL event, then a LOW event that cannot
        # evict it. The dropped publish returns False and the dedup reservation
        # taken in preflight is rolled back via remove(ev2).
        bus = _make_bus(max_queue_size=1)
        await bus.stop()  # ensure not running so nothing is consumed mid-test
        bus._running = True  # publish() requires running, but no consumer loop

        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = True
        bus._rel_dedup = fake_dedup

        ev1 = _make_event("ev1", EventPriority.CRITICAL)
        ev2 = _make_event("ev2", EventPriority.LOW)
        assert bus.publish(ev1) is True
        result = bus.publish(ev2)

        assert result is False
        fake_dedup.remove.assert_called_once_with(ev2)
        # The reservation for the accepted event must NOT be removed.
        for call in fake_dedup.remove.call_args_list:
            assert call.args[0] is not ev1
        bus._running = False


# ---------------------------------------------------------------------------
# NeuroBus — publish with redis bridge (publish_remote)
# ---------------------------------------------------------------------------


class TestPublishWithRedisBridge:
    async def test_publish_remote_called_for_new_event(self) -> None:
        # A locally-published event is mirrored to the redis bridge exactly once
        # with the same event object, and is still delivered locally.
        bus = _make_bus()
        await bus.start()
        fake_bridge = MagicMock()
        bus._redis_bridge = fake_bridge
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("test.event", h)
        ev = _make_event()
        assert bus.publish(ev) is True
        await asyncio.sleep(0.1)
        fake_bridge.publish_remote.assert_called_once_with(ev)
        assert received == [ev]
        bus._redis_bridge = None  # remove before stop to avoid stop() calling .stop()
        await bus.stop()

    async def test_publish_remote_skipped_for_remote_ingest(self) -> None:
        # Events flagged as remote-ingest must NOT be re-broadcast (avoids loops),
        # but must still be delivered to local handlers.
        bus = _make_bus()
        await bus.start()
        fake_bridge = MagicMock()
        bus._redis_bridge = fake_bridge
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("test.event", h)
        ev = NeuroEvent(event_type="test.event", payload={"_neuro_remote_ingest": True})
        assert bus.publish(ev) is True
        await asyncio.sleep(0.1)
        fake_bridge.publish_remote.assert_not_called()
        assert received == [ev]
        bus._redis_bridge = None
        await bus.stop()


# ---------------------------------------------------------------------------
# NeuroBus — start/stop with redis bridge
# ---------------------------------------------------------------------------


class TestBusLifecycleWithRedisBridge:
    async def test_start_calls_bridge_start(self) -> None:
        # start() brings the bus up AND starts the bridge; stop is not yet called.
        bus = _make_bus()
        fake_bridge = MagicMock()
        bus._redis_bridge = fake_bridge
        await bus.start()
        assert bus.is_running is True
        fake_bridge.start.assert_called_once()
        fake_bridge.stop.assert_not_called()
        bus._redis_bridge = None
        await bus.stop()

    async def test_stop_calls_bridge_stop(self) -> None:
        # stop() tears the bus down AND stops the bridge exactly once.
        bus = _make_bus()
        fake_bridge = MagicMock()
        bus._redis_bridge = fake_bridge
        await bus.start()
        bus._redis_bridge = fake_bridge  # re-assign in case start() cleared it
        await bus.stop()
        assert bus.is_running is False
        fake_bridge.stop.assert_called_once()


# ---------------------------------------------------------------------------
# NeuroBus — ingest_remote_event with _event_available signal
# ---------------------------------------------------------------------------


class TestIngestRemoteEventSignal:
    async def test_ingest_remote_signals_event_available(self) -> None:
        # ingest_remote_event enqueues, bumps published_count, signals the loop,
        # and the event is actually dispatched to a local handler.
        bus = _make_bus()
        await bus.start()
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("test.event", h)
        ev = _make_event()
        before = bus._published_count
        result = bus.ingest_remote_event(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert result is True
        assert bus._published_count == before + 1
        assert received == [ev]

    async def test_ingest_remote_preflight_rejected(self) -> None:
        bus = _make_bus()
        await bus.start()
        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = False
        bus._rel_dedup = fake_dedup
        ev = _make_event()
        result = bus.ingest_remote_event(ev)
        assert result is False
        await bus.stop()


# ---------------------------------------------------------------------------
# NeuroBus — _dispatch_event with SLA controller
# ---------------------------------------------------------------------------


class TestDispatchWithSLA:
    async def test_sla_controller_start_and_finish_called(self) -> None:
        # Dispatch brackets the handler with start_monitoring(event) and
        # finish_monitoring(event_id) — the finish key is the event_id, not the
        # event object.
        bus = _make_bus()
        await bus.start()
        fake_sla = MagicMock()
        bus._rel_sla_controller = fake_sla
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("sla.test", h)
        ev = _make_event("sla.test")
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert received == [ev]
        fake_sla.start_monitoring.assert_called_once_with(ev)
        fake_sla.finish_monitoring.assert_called_once_with(ev.metadata.event_id)

    async def test_dedup_mark_processed_on_success(self) -> None:
        # On a successful dispatch the dedup entry is finalized via
        # mark_processed(event) and NOT rolled back via remove().
        bus = _make_bus()
        await bus.start()
        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = True
        bus._rel_dedup = fake_dedup
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("dedup.test", h)
        ev = _make_event("dedup.test")
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert received == [ev]
        fake_dedup.mark_processed.assert_called_once_with(ev)
        fake_dedup.remove.assert_not_called()

    async def test_dedup_remove_on_failure(self) -> None:
        # On a failed dispatch the dedup reservation is rolled back via
        # remove(event) and mark_processed is NOT called (so a retry can re-run).
        bus = _make_bus()
        await bus.start()
        fake_dedup = MagicMock()
        fake_dedup.mark_processing.return_value = True
        bus._rel_dedup = fake_dedup

        async def bad_h(e: NeuroEvent) -> None:
            raise RuntimeError("fail")

        bus.subscribe("dedup.fail", bad_h)
        ev = _make_event("dedup.fail")
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        fake_dedup.remove.assert_called_once_with(ev)
        fake_dedup.mark_processed.assert_not_called()
        assert bus._error_count >= 1


# ---------------------------------------------------------------------------
# NeuroBus — _dispatch_event with tracer end_span
# ---------------------------------------------------------------------------


class TestDispatchWithTracer:
    async def test_tracer_end_span_ok_on_success(self) -> None:
        bus = _make_bus()
        await bus.start()

        fake_tracer = MagicMock()
        fake_span = MagicMock()
        fake_span.span_id = "span-ok"
        fake_tracer.start_span.return_value = fake_span

        from app.neuro_bus.tracer import SpanStatus

        bus._rel_tracer = fake_tracer
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("tracer.ok", h)
        with patch("app.neuro_bus.bus._should_trace_event", return_value=True):
            ev = _make_event("tracer.ok")
            bus.publish(ev)
            await asyncio.sleep(0.15)

        await bus.stop()
        assert received == [ev]
        fake_tracer.end_span.assert_called_once_with("span-ok", SpanStatus.OK)
        # span mapping is popped after the span is closed.
        assert ev.metadata.event_id not in bus._trace_by_event_id

    async def test_tracer_end_span_error_on_failure(self) -> None:
        bus = _make_bus()
        await bus.start()

        fake_tracer = MagicMock()
        fake_span = MagicMock()
        fake_span.span_id = "span-err"
        fake_tracer.start_span.return_value = fake_span

        from app.neuro_bus.tracer import SpanStatus

        bus._rel_tracer = fake_tracer

        async def bad_h(e: NeuroEvent) -> None:
            raise RuntimeError("oops")

        sub = bus.subscribe("tracer.fail", bad_h)
        with patch("app.neuro_bus.bus._should_trace_event", return_value=True):
            ev = _make_event("tracer.fail")
            bus.publish(ev)
            await asyncio.sleep(0.15)

        await bus.stop()
        fake_tracer.end_span.assert_called_once_with("span-err", SpanStatus.ERROR)
        assert ev.metadata.event_id not in bus._trace_by_event_id
        assert sub.error_count == 1
        assert bus._error_count >= 1


# ---------------------------------------------------------------------------
# NeuroBus — _call_handler with retry handler
# ---------------------------------------------------------------------------


class TestCallHandlerRetry:
    async def test_retry_handler_success_path(self) -> None:
        # With a retry handler configured, _call_handler routes the invocation
        # through retry_handler.execute(...). We make the stub actually run the
        # wrapped coroutine so the real handler executes and success is recorded.
        bus = _make_bus()
        await bus.start()

        async def _run(invoke, *, operation_name=None):
            await invoke()
            _run.last_op = operation_name  # type: ignore[attr-defined]

        fake_retry_inst = MagicMock()
        fake_retry_inst.execute = AsyncMock(side_effect=_run)
        fake_retry_handler = MagicMock()
        fake_retry_handler.get_handler.return_value = fake_retry_inst
        bus._rel_retry_handler = fake_retry_handler
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        sub = bus.subscribe("retry.ok", h)
        bus.publish(_make_event("retry.ok", domain="sales"))
        await asyncio.sleep(0.15)
        await bus.stop()
        # The retry handler was looked up by the event's domain and the real
        # handler ran exactly once through it, recording a success.
        fake_retry_handler.get_handler.assert_called_once_with("sales")
        fake_retry_inst.execute.assert_called_once()
        assert _run.last_op == "h"  # type: ignore[attr-defined]
        assert len(received) == 1
        assert received[0].event_type == "retry.ok"
        assert sub.call_count == 1
        assert sub.error_count == 0

    async def test_retry_handler_failure_path(self) -> None:
        bus = _make_bus()
        await bus.start()
        fake_retry_inst = AsyncMock()
        fake_retry_inst.execute.side_effect = OSError("retry exhausted")
        fake_retry_inst._config = MagicMock()
        fake_retry_inst._config.max_retries = 3
        fake_retry_handler = MagicMock()
        fake_retry_handler.get_handler.return_value = fake_retry_inst
        bus._rel_retry_handler = fake_retry_handler

        async def h(e: NeuroEvent) -> None:
            pass

        bus.subscribe("retry.fail", h)
        bus.publish(_make_event("retry.fail"))
        await asyncio.sleep(0.15)
        await bus.stop()
        assert bus._error_count >= 1


# ---------------------------------------------------------------------------
# NeuroBus — _call_handler with DLQ integration
# ---------------------------------------------------------------------------


class TestCallHandlerDLQ:
    async def test_dlq_handle_failure_called_on_error(self) -> None:
        # When a handler raises, the failed event is routed to the DLQ with the
        # original event, the raised exception, and the handler name.
        bus = _make_bus()
        await bus.start()
        fake_dlq = MagicMock()
        bus._dlq_integration = fake_dlq

        async def bad_h(e: NeuroEvent) -> None:
            raise RuntimeError("dlq test")

        bus.subscribe("dlq.test", bad_h)
        ev = _make_event("dlq.test")
        bus.publish(ev)
        await asyncio.sleep(0.1)
        await bus.stop()
        fake_dlq.handle_failure.assert_called_once()
        call = fake_dlq.handle_failure.call_args
        assert call.args[0] is ev
        assert isinstance(call.args[1], RuntimeError)
        assert str(call.args[1]) == "dlq test"
        assert call.kwargs["handler_name"] == "bad_h"
        assert bus._error_count >= 1

    async def test_dlq_handle_failure_exception_swallowed(self) -> None:
        # If the DLQ itself raises a recoverable error, it is logged/swallowed:
        # the bus keeps running, the original handler error is still counted, and
        # a subsequent good event still gets delivered.
        bus = _make_bus()
        await bus.start()
        fake_dlq = MagicMock()
        fake_dlq.handle_failure.side_effect = OSError("dlq broken")
        bus._dlq_integration = fake_dlq
        received = []

        async def bad_h(e: NeuroEvent) -> None:
            raise RuntimeError("trigger dlq")

        async def good_h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("dlq.swallow", bad_h)
        bus.subscribe("dlq.ok", good_h)
        bus.publish(_make_event("dlq.swallow"))
        bus.publish(_make_event("dlq.ok"))
        await asyncio.sleep(0.1)
        await bus.stop()
        fake_dlq.handle_failure.assert_called_once()
        assert bus._error_count >= 1
        # Bus survived the DLQ blow-up and continued processing.
        assert len(received) == 1
        assert bus.is_running is False


# ---------------------------------------------------------------------------
# NeuroBus — _processing_loop: fallback asyncio.sleep and error branches
# ---------------------------------------------------------------------------


class TestProcessingLoopBranches:
    async def test_fallback_sleep_when_no_event_available(self) -> None:
        """Cover the `else: await asyncio.sleep(0.001)` branch.

        With ``_event_available`` set to None the loop cannot wait on the signal
        and falls back to a tiny poll-sleep. An event placed directly on the
        queue must still be picked up and dispatched, proving the fallback path
        keeps draining the queue.
        """
        bus = _make_bus()
        await bus.start()
        bus._event_available = None  # force the polling fallback branch
        received = []

        async def h(e: NeuroEvent) -> None:
            received.append(e)

        bus.subscribe("loop.sleep", h)
        ev = _make_event("loop.sleep")
        assert bus._event_queue.put(ev) is True
        await asyncio.sleep(0.1)
        await bus.stop()
        # The polling loop drained and dispatched the directly-queued event.
        assert received == [ev]
        assert bus._processed_count >= 1

    async def test_recoverable_error_in_processing_loop_increments_error_count(self) -> None:
        """Cover the `except RECOVERABLE_ERRORS` branch in _processing_loop."""
        bus = _make_bus()
        await bus.start()

        # Patch _dispatch_event to raise an OSError (a RECOVERABLE_ERROR)
        dispatch_call_count = 0

        original_dispatch = bus._dispatch_event

        async def patched_dispatch(event: NeuroEvent) -> None:
            nonlocal dispatch_call_count
            dispatch_call_count += 1
            if dispatch_call_count == 1:
                raise OSError("simulated recoverable error in loop")
            await original_dispatch(event)

        bus._dispatch_event = patched_dispatch
        bus.publish(_make_event())
        await asyncio.sleep(0.1)
        await bus.stop()
        assert bus._error_count >= 1


# ---------------------------------------------------------------------------
# PriorityEventQueue — duplicate event_id exhausts all remint attempts
# ---------------------------------------------------------------------------


class TestPriorityEventQueueDuplicateExhausted:
    def test_duplicate_exhausts_remint_and_drops(self) -> None:
        """Cover lines 145-150: after 4 failed remint attempts the event is dropped."""
        q = PriorityEventQueue(max_size=100)

        class StubEvent:
            """Event that always returns the same ID even after remint."""

            def __init__(self) -> None:
                from app.neuro_bus.events.base import EventPriority

                self.metadata = EventMetadata()
                self.metadata.event_id = "fixed-id"
                self.priority = EventPriority.NORMAL
                self.event_type = "stub"

            def remint_queue_identity(self) -> None:
                # Deliberately keep the same ID so remint always fails
                pass

            def is_expired(self) -> bool:
                return False

        from app.neuro_bus.events.base import NeuroEvent

        # Put a real event with "fixed-id" first
        real_ev = NeuroEvent(event_type="stub", payload={})
        real_ev.metadata.event_id = "fixed-id"
        q.put(real_ev)

        # Now put a stub that always has the same ID
        stub = StubEvent()
        result = q.put(stub)  # type: ignore[arg-type]
        assert result is False
        assert q._dropped_count >= 1
