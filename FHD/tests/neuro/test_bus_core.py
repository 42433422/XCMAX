"""NeuroBus 核心模块测试：事件发布/订阅/取消订阅、优先级队列、处理器统计。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

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
)
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent

# ── Helpers ──────────────────────────────────────────────────────────────────


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


# ── _neuro_env_flag ──────────────────────────────────────────────────────────


class TestNeuroEnvFlag:
    def test_truthy_values(self, monkeypatch):
        for val in ("1", "true", "True", "TRUE", "yes", "Yes", "on", "On"):
            monkeypatch.setenv("_TEST_FLAG", val)
            assert _neuro_env_flag("_TEST_FLAG") is True

    def test_falsy_values(self, monkeypatch):
        for val in ("0", "false", "no", "off", "", "random"):
            monkeypatch.setenv("_TEST_FLAG", val)
            assert _neuro_env_flag("_TEST_FLAG") is False

    def test_unset_env(self, monkeypatch):
        monkeypatch.delenv("_TEST_FLAG", raising=False)
        assert _neuro_env_flag("_TEST_FLAG") is False


class TestDeploymentIsStaging:
    def test_staging(self, monkeypatch):
        monkeypatch.setenv("FHD_ENV", "staging")
        assert _deployment_is_staging() is True

    def test_production(self, monkeypatch):
        monkeypatch.setenv("FHD_ENV", "production")
        assert _deployment_is_staging() is False

    def test_unset(self, monkeypatch):
        monkeypatch.delenv("FHD_ENV", raising=False)
        assert _deployment_is_staging() is False


class TestNeuroTraceSampleRate:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", raising=False)
        assert _neuro_trace_sample_rate() == 0.1

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "0.5")
        assert _neuro_trace_sample_rate() == 0.5

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "abc")
        assert _neuro_trace_sample_rate() == 0.1

    def test_clamped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "2.0")
        assert _neuro_trace_sample_rate() == 1.0
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "-1.0")
        assert _neuro_trace_sample_rate() == 0.0


class TestShouldTraceEvent:
    def test_rate_1_always(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "1.0")
        assert _should_trace_event() is True

    def test_rate_0_never(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "0.0")
        assert _should_trace_event() is False


class TestNeuroReliabilityWanted:
    def test_explicit_set(self, monkeypatch):
        monkeypatch.setenv("_TEST_REL", "1")
        assert _neuro_reliability_wanted("_TEST_REL", staging_default=False) is True

    def test_explicit_set_false(self, monkeypatch):
        monkeypatch.setenv("_TEST_REL", "0")
        assert _neuro_reliability_wanted("_TEST_REL", staging_default=True) is False

    def test_unset_production_default_true(self, monkeypatch):
        monkeypatch.delenv("_TEST_REL", raising=False)
        monkeypatch.setenv("FHD_ENV", "production")
        assert _neuro_reliability_wanted("_TEST_REL", staging_default=True) is True

    def test_unset_production_default_false(self, monkeypatch):
        monkeypatch.delenv("_TEST_REL", raising=False)
        monkeypatch.setenv("FHD_ENV", "production")
        assert (
            _neuro_reliability_wanted(
                "_TEST_REL",
                staging_default=True,
                production_default=False,
            )
            is False
        )

    def test_unset_staging_default_true(self, monkeypatch):
        monkeypatch.delenv("_TEST_REL", raising=False)
        monkeypatch.setenv("FHD_ENV", "staging")
        assert _neuro_reliability_wanted("_TEST_REL", staging_default=True) is True

    def test_unset_staging_default_false(self, monkeypatch):
        monkeypatch.delenv("_TEST_REL", raising=False)
        monkeypatch.setenv("FHD_ENV", "staging")
        assert _neuro_reliability_wanted("_TEST_REL", staging_default=False) is False


# ── HandlerSubscription ──────────────────────────────────────────────────────


class TestHandlerSubscription:
    def test_should_handle_no_filter(self):
        handler = lambda e: None
        sub = HandlerSubscription(event_type="test", handler=handler)
        assert sub.should_handle(_make_event()) is True

    def test_should_handle_with_filter_pass(self):
        handler = lambda e: None
        filter_fn = lambda e: e.event_type == "test.event"
        sub = HandlerSubscription(event_type="test", handler=handler, filter_fn=filter_fn)
        assert sub.should_handle(_make_event("test.event")) is True

    def test_should_handle_with_filter_block(self):
        handler = lambda e: None
        filter_fn = lambda e: e.event_type == "other"
        sub = HandlerSubscription(event_type="test", handler=handler, filter_fn=filter_fn)
        assert sub.should_handle(_make_event("test.event")) is False

    def test_record_call_success(self):
        sub = HandlerSubscription(event_type="test", handler=lambda e: None)
        sub.record_call(success=True)
        assert sub.call_count == 1
        assert sub.error_count == 0

    def test_record_call_failure(self):
        sub = HandlerSubscription(event_type="test", handler=lambda e: None)
        sub.record_call(success=False)
        assert sub.call_count == 1
        assert sub.error_count == 1

    def test_error_rate_zero(self):
        sub = HandlerSubscription(event_type="test", handler=lambda e: None)
        assert sub.error_rate == 0.0

    def test_error_rate_calculation(self):
        sub = HandlerSubscription(event_type="test", handler=lambda e: None)
        sub.record_call(success=True)
        sub.record_call(success=False)
        assert sub.error_rate == 0.5


# ── PriorityEventQueue ───────────────────────────────────────────────────────


class TestPriorityEventQueue:
    def test_put_and_get(self):
        q = PriorityEventQueue()
        event = _make_event()
        assert q.put(event) is True
        assert q.size() == 1
        got = q.get()
        assert got is not None
        assert got.event_type == "test.event"
        assert q.size() == 0

    def test_priority_ordering(self):
        q = PriorityEventQueue()
        low = _make_event(priority=EventPriority.LOW)
        critical = _make_event(priority=EventPriority.CRITICAL)
        normal = _make_event(priority=EventPriority.NORMAL)
        q.put(low)
        q.put(critical)
        q.put(normal)
        assert q.get().priority == EventPriority.CRITICAL
        assert q.get().priority == EventPriority.NORMAL
        assert q.get().priority == EventPriority.LOW

    def test_get_empty(self):
        q = PriorityEventQueue()
        assert q.get() is None

    def test_peek(self):
        q = PriorityEventQueue()
        event = _make_event(priority=EventPriority.HIGH)
        q.put(event)
        peeked = q.peek()
        assert peeked is not None
        assert q.size() == 1  # peek doesn't remove

    def test_peek_empty(self):
        q = PriorityEventQueue()
        assert q.peek() is None

    def test_clear(self):
        q = PriorityEventQueue()
        q.put(_make_event())
        q.put(_make_event())
        q.clear()
        assert q.size() == 0

    def test_max_size_drop(self):
        q = PriorityEventQueue(max_size=2)
        q.put(_make_event(priority=EventPriority.LOW))
        q.put(_make_event(priority=EventPriority.LOW))
        # Queue full, new LOW event should be dropped
        assert q.put(_make_event(priority=EventPriority.LOW)) is False

    def test_max_size_replace_lower_priority(self):
        q = PriorityEventQueue(max_size=1)
        q.put(_make_event(priority=EventPriority.LOW))
        # Higher priority should replace lower
        assert q.put(_make_event(priority=EventPriority.HIGH)) is True
        got = q.get()
        assert got.priority == EventPriority.HIGH


# ── NeuroBus ─────────────────────────────────────────────────────────────────


class TestNeuroBusSubscribe:
    def test_subscribe_and_handler_count(self):
        bus = NeuroBus()
        sub = bus.subscribe("test.event", handler=lambda e: None)
        assert isinstance(sub, HandlerSubscription)
        stats = bus.get_stats()
        assert stats["handlers"] >= 1

    def test_subscribe_with_domain(self):
        bus = NeuroBus()
        sub = bus.subscribe_event("test.event", handler=lambda e: None, domain="shipment")
        assert isinstance(sub, HandlerSubscription)
        summary = bus.summarize_subscriptions()
        assert "shipment" in summary["domain_handlers"]

    def test_subscribe_global(self):
        bus = NeuroBus()
        sub = bus.subscribe_global(handler=lambda e: None)
        assert isinstance(sub, HandlerSubscription)
        assert bus.get_stats()["global_handlers"] == 1

    def test_subscribe_all_alias(self):
        bus = NeuroBus()
        sub = bus.subscribe_all(handler=lambda e: None)
        assert bus.get_stats()["global_handlers"] == 1

    def test_unsubscribe(self):
        bus = NeuroBus()
        sub = bus.subscribe("test.event", handler=lambda e: None)
        assert bus.unsubscribe(sub) is True
        assert bus.get_stats()["handlers"] == 0

    def test_unsubscribe_not_found(self):
        bus = NeuroBus()
        sub = HandlerSubscription(event_type="nonexistent", handler=lambda e: None)
        assert bus.unsubscribe(sub) is False


class TestNeuroBusPublish:
    @pytest.mark.asyncio
    async def test_publish_not_running(self):
        bus = NeuroBus()
        event = _make_event()
        assert bus.publish(event) is False

    @pytest.mark.asyncio
    async def test_publish_and_process(self):
        bus = NeuroBus()
        received = []
        bus.subscribe("test.event", handler=lambda e: received.append(e), is_async=False)
        await bus.start()
        try:
            event = _make_event("test.event")
            assert bus.publish(event) is True
            await asyncio.sleep(0.1)
            assert len(received) == 1
        finally:
            await bus.stop()

    @pytest.mark.asyncio
    async def test_publish_with_persistence(self):
        bus = NeuroBus()
        bus._enable_persistence = True
        await bus.start()
        try:
            event = _make_event()
            bus.publish(event)
            assert len(bus._event_buffer) == 1
        finally:
            await bus.stop()

    @pytest.mark.asyncio
    async def test_global_handler_receives_all(self):
        bus = NeuroBus()
        received = []

        async def on_event(e):
            received.append(e.event_type)

        bus.subscribe_global(handler=on_event)
        await bus.start()
        try:
            bus.publish(_make_event("a.event"))
            bus.publish(_make_event("b.event"))
            await asyncio.sleep(0.15)
            assert "a.event" in received
            assert "b.event" in received
        finally:
            await bus.stop()

    @pytest.mark.asyncio
    async def test_domain_handler(self):
        bus = NeuroBus()
        received = []
        bus.subscribe_to_domain(
            "shipment", "order.created", handler=lambda e: received.append(e), is_async=False
        )
        await bus.start()
        try:
            event = _make_event("order.created", domain="shipment")
            bus.publish(event)
            await asyncio.sleep(0.1)
            assert len(received) == 1
        finally:
            await bus.stop()


class TestNeuroBusStats:
    def test_initial_stats(self):
        bus = NeuroBus()
        stats = bus.get_stats()
        assert stats["published"] == 0
        assert stats["processed"] == 0
        assert stats["errors"] == 0
        assert stats["running"] is False

    def test_reliability_status(self, monkeypatch):
        monkeypatch.delenv("XCAGI_NEURO_BUS_DEDUP", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_CIRCUIT", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_RATE_LIMIT", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_LIFELINE", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_TRACE", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_DLQ_AUTO", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_SLA_LOG", raising=False)
        monkeypatch.delenv("XCAGI_NEURO_BUS_REDIS_PUBSUB", raising=False)
        monkeypatch.delenv("FHD_ENV", raising=False)
        bus = NeuroBus()
        rel = bus.get_reliability_status()
        assert rel["dedup"] is False
        assert rel["circuit_breaker"] is False


class TestNeuroBusSingletons:
    def test_get_neuro_bus_creates(self, monkeypatch):
        import app.neuro_bus.bus as bus_mod

        monkeypatch.setattr(bus_mod, "_neuro_bus", None)
        bus = bus_mod.get_neuro_bus()
        assert isinstance(bus, NeuroBus)

    def test_set_neuro_bus(self, monkeypatch):
        import app.neuro_bus.bus as bus_mod

        custom = NeuroBus()
        bus_mod.set_neuro_bus(custom)
        assert bus_mod.get_neuro_bus() is custom
        bus_mod.set_neuro_bus(None)


class TestNeuroBusIngestRemote:
    @pytest.mark.asyncio
    async def test_ingest_not_running(self):
        bus = NeuroBus()
        assert bus.ingest_remote_event(_make_event()) is False

    @pytest.mark.asyncio
    async def test_ingest_success(self):
        bus = NeuroBus()
        await bus.start()
        try:
            event = _make_event()
            assert bus.ingest_remote_event(event) is True
            assert bus.get_stats()["published"] == 1
        finally:
            await bus.stop()


class TestNeuroBusFilterFn:
    @pytest.mark.asyncio
    async def test_filter_blocks_event(self):
        # Create bus without dedup to avoid same-ms dedup collisions
        bus = NeuroBus()
        bus._rel_dedup = None
        received = []
        filter_fn = lambda e: e.payload.get("allowed") is True
        bus.subscribe(
            "test.event", handler=lambda e: received.append(e), filter_fn=filter_fn, is_async=False
        )
        await bus.start()
        try:
            bus.publish(_make_event("test.event", payload={"allowed": False, "id": 1}))
            bus.publish(_make_event("test.event", payload={"allowed": True, "id": 2}))
            await asyncio.sleep(0.15)
            assert len(received) == 1
            assert received[0].payload["allowed"] is True
        finally:
            await bus.stop()


class TestNeuroBusExpiredEvent:
    @pytest.mark.asyncio
    async def test_expired_event_dropped(self):
        bus = NeuroBus()
        received = []
        bus.subscribe("test.event", handler=lambda e: received.append(e), is_async=False)
        await bus.start()
        try:
            event = _make_event("test.event")
            event.metadata.timeout_ms = 0
            event.metadata.timestamp = time.time() - 10
            bus.publish(event)
            await asyncio.sleep(0.1)
            assert len(received) == 0
        finally:
            await bus.stop()
