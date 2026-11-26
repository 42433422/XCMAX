"""Event-level delivery accounting with the actual local bus and counters."""

from __future__ import annotations

import asyncio

import pytest

from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.events.events_base import EventPriority, NeuroEvent
from app.utils.metrics import neurobus_delivery_outcomes_total


def _snapshot() -> dict[str, float]:
    return {
        sample.labels["outcome"]: sample.value
        for metric in neurobus_delivery_outcomes_total.collect()
        for sample in metric.samples
        if sample.name == "neurobus_delivery_outcomes_total"
    }


def _delta(before: dict[str, float]) -> dict[str, float]:
    return {key: value - before[key] for key, value in _snapshot().items()}


@pytest.fixture
def isolated_bus(monkeypatch):
    for flag in (
        "SLA_LOG",
        "RETRY",
        "RATE_LIMIT",
        "CIRCUIT",
        "LIFELINE",
        "TRACE",
        "DLQ_AUTO",
        "REDIS_PUBSUB",
    ):
        monkeypatch.setenv(f"XCAGI_NEURO_BUS_{flag}", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_DEDUP", "1")
    monkeypatch.setenv("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "")
    return NeuroBus


def _event(name: str, priority: EventPriority = EventPriority.NORMAL) -> NeuroEvent:
    event = NeuroEvent(event_type=name, payload={}, priority=priority)
    event.metadata.dedup_key = name
    return event


def _completion(bus: NeuroBus, monkeypatch) -> asyncio.Event:
    done = asyncio.Event()
    original = bus._record_partition_outcome

    def record(task: asyncio.Task[str]) -> None:
        original(task)
        done.set()

    monkeypatch.setattr(bus, "_record_partition_outcome", record)
    return done


@pytest.mark.asyncio
async def test_multiple_handler_failures_are_one_terminal_event(isolated_bus, monkeypatch):
    bus = isolated_bus()
    done = _completion(bus, monkeypatch)
    calls: list[str] = []

    async def broken(_event: NeuroEvent) -> None:
        calls.append("failed")
        raise ValueError("fixture failure")

    async def healthy(_event: NeuroEvent) -> None:
        calls.append("success")

    async def also_broken(event: NeuroEvent) -> None:
        await broken(event)

    bus.subscribe("work", broken)
    bus.subscribe("work", also_broken)
    bus.subscribe("work", healthy)
    before = _snapshot()
    await bus.start()
    try:
        assert bus.publish(_event("work"))
        await asyncio.wait_for(done.wait(), 3)
        assert calls.count("failed") == 2
        assert calls.count("success") == 1
        delta = _delta(before)
        assert delta["accepted"] == delta["failed"] == 1
        assert delta["delivered"] == delta["rejected"] == 0
    finally:
        await bus.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [False, True])
async def test_rejection_dedup_eviction_and_unhandled_are_distinct(
    isolated_bus, monkeypatch, remote
):
    bus = isolated_bus(max_queue_size=1)
    submit = bus.ingest_remote_event if remote else bus.publish
    done = _completion(bus, monkeypatch)
    before = _snapshot()
    assert not submit(_event("offline"))
    await bus.start()
    try:
        assert submit(_event("first"))
        assert not submit(_event("first"))
        assert not submit(_event("low", EventPriority.LOW))
        assert submit(_event("high", EventPriority.HIGH))
        await asyncio.wait_for(done.wait(), 3)
        assert _delta(before) == {
            "accepted": 2,
            "rejected": 2,
            "deduplicated": 1,
            "delivered": 0,
            "failed": 1,
            "unhandled": 1,
            "cancelled": 0,
        }
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_success_and_cancellation_have_separate_terminal_outcomes(isolated_bus, monkeypatch):
    bus = isolated_bus()
    done = _completion(bus, monkeypatch)
    started = asyncio.Event()
    blocker = asyncio.Event()

    async def healthy(_event: NeuroEvent) -> None:
        return None

    async def pending(_event: NeuroEvent) -> None:
        started.set()
        await blocker.wait()

    bus.subscribe("ok", healthy)
    bus.subscribe("pending", pending)
    before = _snapshot()
    await bus.start()
    try:
        assert bus.publish(_event("ok"))
        await asyncio.wait_for(done.wait(), 3)
        done.clear()
        assert bus.publish(_event("pending"))
        await asyncio.wait_for(started.wait(), 3)
    finally:
        await bus.stop()
    await asyncio.wait_for(done.wait(), 3)
    delta = _delta(before)
    assert delta["accepted"] == 2
    assert delta["delivered"] == delta["cancelled"] == 1
    assert delta["failed"] == delta["unhandled"] == 0


@pytest.mark.asyncio
async def test_partition_task_cancelled_before_start_has_one_terminal_outcome(
    isolated_bus, monkeypatch
):
    bus = isolated_bus()
    done = _completion(bus, monkeypatch)
    loop = asyncio.get_running_loop()
    create_task = loop.create_task
    partition_code = NeuroBus._process_partition_event.__code__

    def cancel_partition_on_creation(coro, **kwargs):
        task = create_task(coro, **kwargs)
        if getattr(coro, "cr_code", None) is partition_code:
            task.cancel()
        return task

    monkeypatch.setattr(loop, "create_task", cancel_partition_on_creation)
    handled = []

    async def handler(event: NeuroEvent) -> None:
        handled.append(event)

    bus.subscribe("work", handler)
    before = _snapshot()
    await bus.start()
    try:
        assert bus.publish(_event("work"))
        await asyncio.wait_for(done.wait(), 3)
    finally:
        await bus.stop()

    assert not handled
    assert _delta(before) == {
        "accepted": 1,
        "rejected": 0,
        "deduplicated": 0,
        "delivered": 0,
        "failed": 0,
        "unhandled": 0,
        "cancelled": 1,
    }


@pytest.mark.asyncio
async def test_stream_ingress_does_not_double_count_origin_admission(
    isolated_bus, monkeypatch
):
    """Redis transport ACK is counted once; local dispatch is not a second publish."""
    from unittest.mock import MagicMock

    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bus = isolated_bus()
    bridge = RedisStreamsBridge(bus=bus, redis_client=MagicMock())
    monkeypatch.setattr(bridge, "publish_remote", lambda event: "1-0")
    bus._redis_bridge = bridge
    bus._running = True
    bus._shutdown = False
    event = _event("stream.once")
    before = _snapshot()
    waiter = asyncio.get_running_loop().create_future()
    try:
        assert bus.publish(event)
        assert _delta(before)["accepted"] == 1
        bus._stream_waiters[id(event)] = waiter
        assert bus.ingest_remote_event(event)
        assert bus._event_queue.size() == 1
        assert _delta(before)["accepted"] == 1
        assert bus._published_count == 1
    finally:
        bus._stream_waiters.clear()
        bus._running = False
        bus._executor.shutdown(wait=False)
