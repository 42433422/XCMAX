"""Load-bearing scheduling/overload contracts, without timing throughput claims."""

import asyncio
import threading

import pytest

from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.bus_primitives import PriorityEventQueue, event_partition_key
from app.neuro_bus.events.events_base import EventPriority, NeuroEvent


def event(entity, number=0, priority=EventPriority.NORMAL, tenant="t"):
    return NeuroEvent(
        "work", {"conversation_id": entity, "tenant_id": tenant, "number": number}, priority
    )


def test_full_queue_evicts_only_lowest_newest_and_preserves_equal_priority_fifo():
    queue = PriorityEventQueue(3)
    high, normal, background = (
        event(str(p), priority=p)
        for p in (EventPriority.HIGH, EventPriority.NORMAL, EventPriority.BACKGROUND)
    )
    for value in (high, normal, background):
        assert queue.put(value)
    critical = event("critical", priority=EventPriority.CRITICAL)
    assert queue.put(critical)
    assert [queue.get(), queue.get(), queue.get()] == [critical, high, normal]
    queue = PriorityEventQueue(2)
    assert queue.put(critical) and queue.put(background) and queue.put(high)
    assert [queue.get(), queue.get()] == [critical, high]
    queue = PriorityEventQueue(2)
    older, newer = event("older"), event("newer")
    assert queue.put(older) and queue.put(newer)
    assert not queue.put(event("same"))
    assert [queue.get(), queue.get()] == [older, newer]


def test_partition_fifo_overrides_priority_but_not_other_entities():
    queue = PriorityEventQueue(5, partition_key=event_partition_key)
    first = event("a", 1, EventPriority.BACKGROUND)
    second = event("a", 2, EventPriority.CRITICAL)
    unrelated = event("b", 1, EventPriority.HIGH)
    for value in (first, second, unrelated):
        assert queue.put(value)
    assert [queue.get(), queue.get(), queue.get()] == [unrelated, first, second]


@pytest.mark.parametrize(
    "domain,primary,related",
    [
        ("shipment", "shipment_id", "product_id"),
        ("payment", "payment_id", "order_id"),
        ("order", "order_id", "customer_id"),
        ("material", "material_id", "warehouse_id"),
        ("print", "job_id", "document_id"),
    ],
)
def test_domain_primary_keys_are_stable_across_event_types_and_metadata(domain, primary, related):
    first = NeuroEvent(f"{domain}.created", {primary: 7, related: 1})
    last = NeuroEvent(f"{domain}.deleted", {primary: 7}).with_domain(domain)
    aggregate = NeuroEvent(f"{domain}.updated", {"_aggregate_id": 7}).with_domain(domain)
    assert event_partition_key(first) == event_partition_key(last) == event_partition_key(aggregate)
    assert event_partition_key(first) != event_partition_key(
        NeuroEvent(f"{domain}.created", {primary: 8, related: 1})
    )


def test_domain_barrier_orders_bulk_work_and_other_domains_can_progress():
    queue = PriorityEventQueue(6, partition_key=event_partition_key)
    older = NeuroEvent("product.updated", {"product_id": 1}, EventPriority.LOW)
    bulk = NeuroEvent("product.imported", {"unit_name": "u"}, EventPriority.HIGH)
    newer = NeuroEvent("product.deleted", {"product_id": 2}, EventPriority.CRITICAL)
    unrelated = NeuroEvent("shipment.printed", {"shipment_id": 3})
    for value in (older, bulk, newer, unrelated):
        assert queue.put(value)
    assert queue.get() is unrelated
    assert queue.get() is older
    assert queue.get({event_partition_key(older)}) is None
    assert queue.get() is bulk
    assert queue.get({event_partition_key(bulk)}) is None
    assert queue.get() is newer
    assert not queue._scopes and not queue._barriers


@pytest.mark.asyncio
async def test_shipment_print_cancel_delete_are_fifo_with_actual_facade_payloads():
    bus = NeuroBus(worker_threads=3, enable_metrics=False)
    entered, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []

    async def handler(value):
        seen.append(value.event_type)
        if value.event_type == "shipment.printed":
            entered.set()
            await release.wait()
        if len(seen) == 3:
            done.set()

    for name in ("printed", "cancelled", "deleted"):
        bus.subscribe(f"shipment.{name}", handler)
    await bus.start()
    try:
        for name in ("printed", "cancelled", "deleted"):
            assert bus.publish(NeuroEvent(f"shipment.{name}", {"shipment_id": 7}))
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.sleep(0)
        assert seen == ["shipment.printed"] and len(bus._inflight) == 1
        release.set()
        await asyncio.wait_for(done.wait(), 1)
        assert seen == ["shipment.printed", "shipment.cancelled", "shipment.deleted"]
    finally:
        release.set()
        await bus.stop()


@pytest.mark.asyncio
async def test_start_cannot_overtake_shared_stop_even_if_stop_caller_is_cancelled():
    bus = NeuroBus(enable_metrics=False)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    bus.subscribe("work", handler)
    await bus.start()
    bus.publish(event("a"))
    await asyncio.wait_for(entered.wait(), 1)
    first = asyncio.create_task(bus.stop())
    await asyncio.wait_for(cleaning.wait(), 1)
    second = asyncio.create_task(bus.stop())
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(RuntimeError, match="is stopping"):
        await bus.start()
    assert not bus.is_running and not second.done()
    release.set()
    await asyncio.wait_for(second, 1)
    assert bus._executor._shutdown and not bus._inflight
    await bus.start()
    assert bus.is_running and not bus._executor._shutdown and not bus._processing_task.done()
    await bus.stop()


@pytest.mark.asyncio
async def test_workers_are_bounded_and_same_entity_never_overlaps():
    bus = NeuroBus(worker_threads=3, enable_metrics=False)
    admitted, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active, seen = set(), []
    peak = 0

    async def handler(value):
        nonlocal peak
        key = event_partition_key(value)
        assert key not in active
        active.add(key)
        peak = max(peak, len(active))
        if len(active) == 3:
            admitted.set()
        await release.wait()
        seen.append(
            (value.payload["tenant_id"], value.payload["conversation_id"], value.payload["number"])
        )
        active.remove(key)
        if len(seen) == 12:
            finished.set()

    bus.subscribe("work", handler)
    await bus.start()
    try:
        for number in range(2):
            for tenant in ("t1", "t2"):
                for entity in ("a", "b", "c"):
                    assert bus.publish(event(entity, number, tenant=tenant))
        await asyncio.wait_for(admitted.wait(), 1)
        assert len(bus._inflight) == 3 and bus._event_queue.size() == 9
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        assert peak == 3
        for tenant in ("t1", "t2"):
            for entity in ("a", "b", "c"):
                assert [n for t, e, n in seen if (t, e) == (tenant, entity)] == [0, 1]
    finally:
        release.set()
        await bus.stop()
    assert not bus._inflight and not bus._active_partitions


@pytest.mark.asyncio
async def test_async_deadline_does_not_block_independent_default_ttl_event():
    bus = NeuroBus(worker_threads=2, enable_metrics=False, handler_timeout_sec=0.03)
    started, cancelled, fast = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(value):
        if value.payload["conversation_id"] == "slow":
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        else:
            fast.set()

    bus.subscribe("work", handler)
    await bus.start()
    try:
        assert bus.publish(event("slow"))
        await asyncio.wait_for(started.wait(), 1)
        critical = event("fast", priority=EventPriority.CRITICAL)
        assert critical.metadata.timeout_ms == 5000
        assert bus.publish(critical)
        await asyncio.wait_for(fast.wait(), 1)
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.sleep(0)
        assert bus.get_stats()["handler_timeouts"] == 1
        assert bus.get_stats()["dropped"] == 0
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_sync_timeout_keeps_partition_and_restart_cannot_leak_another_pool():
    bus = NeuroBus(worker_threads=2, enable_metrics=False, handler_timeout_sec=0.01)
    entered, release = threading.Event(), threading.Event()
    seen, fast = [], asyncio.Event()

    def synchronous(value):
        if value.payload["number"] == 1:
            entered.set()
            assert release.wait(2)
        seen.append(value.payload["number"])

    async def independent(_):
        fast.set()

    bus.subscribe("work", synchronous, is_async=False)
    bus.subscribe("fast", independent)
    await bus.start()
    try:
        assert bus.publish(event("a", 1))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        assert bus.publish(event("a", 2))
        assert bus.publish(NeuroEvent("fast", {}))
        await asyncio.wait_for(fast.wait(), 1)
        await asyncio.sleep(0.03)
        assert bus.get_stats()["handler_timeouts"] == 1 and seen == []
        await asyncio.wait_for(bus.stop(), 0.5)
        with pytest.raises(RuntimeError, match="stopping synchronous"):
            await bus.start()
    finally:
        release.set()
        await bus.stop()
    for _ in range(100):
        if not bus._sync_futures:
            break
        await asyncio.sleep(0.001)
    await bus.start()
    await bus.stop()
    assert seen == [1]
