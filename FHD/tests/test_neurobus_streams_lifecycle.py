"""A04: real Redis consumer lifecycle and failure-path contracts."""

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from contextlib import suppress

import pytest

from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.events.events_base import NeuroEvent
from app.neuro_bus.transports import redis_streams as streams

redis = pytest.importorskip("redis")


@pytest.fixture
def redis_client(monkeypatch, tmp_path):
    """Never flush or touch production stream keys; use a private Redis instance."""
    url = os.environ.get("XCAGI_NEUROBUS_TEST_REDIS_URL")
    process = None
    if url:
        client = redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
    else:
        executable = shutil.which("redis-server")
        if not executable or os.name == "nt":
            pytest.skip("dedicated Redis service or redis-server executable required")
        socket_path = str(tmp_path / "redis.sock")
        process = subprocess.Popen(
            [
                executable,
                "--port",
                "0",
                "--unixsocket",
                socket_path,
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        client = redis.Redis(unix_socket_path=socket_path, socket_timeout=3)
    namespace = "neurobus:test:{" + uuid.uuid4().hex + "}"
    monkeypatch.setattr(streams, "STREAM_KEY", namespace + ":events")
    monkeypatch.setattr(streams, "DLQ_KEY", namespace + ":dlq")
    monkeypatch.setattr(streams, "CLAIM_IDLE_MS", 150)
    monkeypatch.setenv("FHD_ENV", "development")
    monkeypatch.setenv("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "")
    monkeypatch.setenv("XCAGI_NEURO_BUS_REDIS_PUBSUB", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_DEDUP", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_CIRCUIT", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_RATE_LIMIT", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_LIFELINE", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_RETRY", "0")
    monkeypatch.setenv("XCAGI_NEURO_BUS_DLQ_AUTO", "0")
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                client.ping()
                break
            except redis.exceptions.ConnectionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        yield client
    finally:
        with suppress(redis.exceptions.RedisError):
            client.delete(streams.STREAM_KEY, streams.DLQ_KEY)
        client.close()
        if process is not None:
            process.terminate()
            process.wait(timeout=5)


async def _until(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def _event(event_type="a04.test"):
    return NeuroEvent(event_type, {}).with_timeout(30000)


def _pending(client):
    return client.xpending(streams.STREAM_KEY, streams.CONSUMER_GROUP)["pending"]


def _bus(client):
    bus = NeuroBus(enable_metrics=False)
    bridge = streams.RedisStreamsBridge(bus, client)
    bus._redis_bridge = bridge
    return bus, bridge


@pytest.mark.asyncio
async def test_automatic_consume_ack_only_after_handler_and_restart(redis_client):
    bus, bridge = _bus(redis_client)
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def handler(event):
        seen.append(event.metadata.event_id)
        entered.set()
        await release.wait()

    bus.subscribe("a04.test", handler)
    try:
        await bus.start()
        original_task = bridge._task
        await bus.start()
        assert bridge._task is original_task
        await _until(lambda: bridge.get_stats()["ready"])
        event = _event()
        assert bus.publish(event)
        await asyncio.wait_for(entered.wait(), 5)
        assert _pending(redis_client) == 1
        # Hold longer than reclaim-idle; heartbeat prevents another worker claiming.
        await asyncio.sleep(0.35)
        other = streams.RedisStreamsBridge(bus, redis_client, consumer_id="other")
        assert other._recover_one() == []
        release.set()
        await _until(lambda: _pending(redis_client) == 0)
        assert seen == [event.metadata.event_id]
        await bus.stop()
        assert not bridge.get_stats()["running"]
        await bus.start()
        assert bridge._task is not original_task
        second = _event()
        assert bus.publish(second)
        await _until(lambda: len(seen) == 2 and _pending(redis_client) == 0)
        assert seen[-1] == second.metadata.event_id
    finally:
        release.set()
        await bus.stop()


@pytest.mark.asyncio
async def test_reclaim_abandoned_consumer_and_fence_stale_ack(redis_client):
    bus, bridge = _bus(redis_client)
    seen = []
    abandoned = streams.RedisStreamsBridge(bus, redis_client, consumer_id="abandoned")
    event = _event()
    msg_id = abandoned.publish(event.to_dict())
    assert abandoned.consume(count=1, block_ms=20)[0]["_msg_id"] == msg_id
    assert _pending(redis_client) == 1

    async def handler(event):
        seen.append(event.metadata.event_id)
        # Ownership has changed: the old consumer cannot remove the PEL entry.
        assert not abandoned.ack(msg_id)
        assert _pending(redis_client) == 1

    bus.subscribe("a04.test", handler)
    await asyncio.sleep(0.2)
    try:
        await bus.start()
        await _until(lambda: seen and _pending(redis_client) == 0)
        assert seen == [event.metadata.event_id]
        assert bridge.get_stats()["ready"]
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_failed_handler_and_poison_message_go_to_dlq(redis_client):
    bus, bridge = _bus(redis_client)

    async def handler(event):
        raise ValueError("test handler failure")

    bus.subscribe("a04.test", handler)
    try:
        await bus.start()
        await _until(lambda: bridge.get_stats()["ready"])
        assert bus.publish(_event())
        redis_client.xadd(streams.STREAM_KEY, {"payload": b"\xff"})
        await _until(lambda: redis_client.xlen(streams.DLQ_KEY) == 2)
        assert _pending(redis_client) == 0
        assert bridge.get_stats()["running"]
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_stop_during_handler_leaves_recoverable_pending(redis_client):
    bus, bridge = _bus(redis_client)
    entered = asyncio.Event()
    never = asyncio.Event()
    completed = []

    async def interrupted(event):
        entered.set()
        await never.wait()

    subscription = bus.subscribe("a04.test", interrupted)
    event = _event()
    try:
        await bus.start()
        assert bus.publish(event)
        await asyncio.wait_for(entered.wait(), 5)
        await bus.stop()
        assert _pending(redis_client) == 1
        assert not bridge.get_stats()["running"]
        bus.unsubscribe(subscription)

        async def recovered(event):
            completed.append(event.metadata.event_id)

        bus.subscribe("a04.test", recovered)
        await bus.start()
        await _until(lambda: completed and _pending(redis_client) == 0)
        assert completed == [event.metadata.event_id]
    finally:
        await bus.stop()


def test_missing_redis_client_cannot_start():
    bridge = streams.RedisStreamsBridge(NeuroBus(enable_metrics=False))
    with pytest.raises(RuntimeError, match="client missing"):
        bridge.start()
    assert not bridge.get_stats()["running"]


def test_integrated_safe_trim_preserves_slow_group_and_out_of_order_ack(redis_client, monkeypatch):
    """A04 ownership ACK and A05 progress trim must hold on the same code."""
    monkeypatch.setattr(streams, "MAXLEN", 2)
    monkeypatch.setattr(streams, "TRIM_BATCH", 2)
    _, bridge = _bus(redis_client)
    bridge._ensure_group()
    redis_client.xgroup_create(streams.STREAM_KEY, "lagging", id="0-0")
    ids = [bridge.publish(_event().to_dict()) for _ in range(8)]
    assert all(ids)
    assert [row["_msg_id"] for row in bridge.consume(count=8, block_ms=20)] == ids

    # Fast group's ACKs arrive out of order; id0 is still unacknowledged.
    for msg_id in ids[1:]:
        assert bridge.ack(msg_id)
    assert redis_client.xlen(streams.STREAM_KEY) == 8
    redis_client.xreadgroup("lagging", "old", {streams.STREAM_KEY: ">"}, count=5)
    redis_client.xack(streams.STREAM_KEY, "lagging", *ids[:4])
    assert bridge.ack(ids[0])
    assert redis_client.xlen(streams.STREAM_KEY) == 6
    assert bridge.trim_acknowledged() == 2
    assert [row_id.decode() for row_id, _ in redis_client.xrange(streams.STREAM_KEY)] == ids[4:]

    # A replacement worker can still claim the earliest pending payload.
    _, rows, *_ = redis_client.xautoclaim(
        streams.STREAM_KEY,
        "lagging",
        "replacement",
        min_idle_time=0,
        start_id="0-0",
        count=8,
    )
    assert len(rows) == 1 and rows[0][0].decode() == ids[4]
    assert redis_client.xpending(streams.STREAM_KEY, "lagging")["pending"] == 1
    redis_client.xack(streams.STREAM_KEY, "lagging", ids[4])
    redis_client.xreadgroup("lagging", "replacement", {streams.STREAM_KEY: ">"}, count=8)
    redis_client.xack(streams.STREAM_KEY, "lagging", *ids[5:])
    while bridge.trim_acknowledged():
        pass
    assert [row_id.decode() for row_id, _ in redis_client.xrange(streams.STREAM_KEY)] == ids[-2:]


def test_rolling_worker_takeover_fences_old_ack_before_trim(redis_client, monkeypatch):
    """Same-version worker replacement; this is not a mixed-binary rollout test."""
    monkeypatch.setattr(streams, "MAXLEN", 1)
    bus, original = _bus(redis_client)
    original._ensure_group()
    event = _event()
    msg_id = original.publish(event.to_dict())
    assert original.consume(count=1, block_ms=20)[0]["_msg_id"] == msg_id

    replacement = streams.RedisStreamsBridge(bus, redis_client, consumer_id="replacement")
    reclaimed = redis_client.xclaim(
        streams.STREAM_KEY,
        streams.CONSUMER_GROUP,
        "replacement",
        min_idle_time=0,
        message_ids=[msg_id],
    )
    assert reclaimed and reclaimed[0][0].decode() == msg_id
    # An ACK from the old consumer must not remove another owner's PEL entry.
    assert not original.ack(msg_id)
    assert redis_client.xpending(streams.STREAM_KEY, streams.CONSUMER_GROUP)["pending"] == 1
    assert redis_client.xrange(streams.STREAM_KEY)[0][0].decode() == msg_id
    assert replacement.ack(msg_id)
    assert redis_client.xpending(streams.STREAM_KEY, streams.CONSUMER_GROUP)["pending"] == 0


@pytest.mark.asyncio
async def test_duplicate_remote_ingress_does_not_remint_pending_event_id(redis_client):
    """A stream retry must retain its original event identity on queue conflict."""
    bus, _ = _bus(redis_client)
    original = _event()
    already_queued = NeuroEvent.from_dict(original.to_dict(), preserve_queue_identity=True)
    bus._running = True
    bus._shutdown = False
    assert bus._event_queue.put(already_queued)
    loop = asyncio.get_running_loop()
    receipt = loop.create_future()
    bus._stream_waiters[id(original)] = receipt
    stable_id = original.metadata.event_id
    try:
        assert not bus.ingest_remote_event(original)
        assert original.metadata.event_id == stable_id
        assert already_queued.metadata.event_id == stable_id
        assert bus._event_queue.size() == 1
        assert await asyncio.wait_for(receipt, timeout=1) == "retry"
    finally:
        bus._stream_waiters.clear()
        bus._running = False


def test_previous_consumer_pending_survives_new_consumer_progress(redis_client, monkeypatch):
    """Rolling worker replacement must retain the previous PEL payload.

    This checks consumer replacement, not a still-active legacy XADD MAXLEN writer.
    """
    monkeypatch.setattr(streams, "MAXLEN", 2)
    bus, old = _bus(redis_client)
    old._ensure_group()
    original = _event()
    old_id = old.publish(original.to_dict())
    assert old.consume(count=1, block_ms=20)[0]["_msg_id"] == old_id

    newer = streams.RedisStreamsBridge(bus, redis_client, consumer_id="new-release")
    ids = [newer.publish(_event().to_dict()) for _ in range(6)]
    assert [m["_msg_id"] for m in newer.consume(count=6, block_ms=20)] == ids
    for message_id in ids:
        assert newer.ack(message_id)

    # The prior owner's unacknowledged event must retain its exact serialized payload.
    retained = redis_client.xrange(streams.STREAM_KEY, min=old_id, max=old_id)
    assert len(retained) == 1
    assert retained[0][0].decode() == old_id
    assert redis_client.xpending(streams.STREAM_KEY, streams.CONSUMER_GROUP)["pending"] == 1

    _, claimed, *_ = redis_client.xautoclaim(
        streams.STREAM_KEY,
        streams.CONSUMER_GROUP,
        "new-release",
        min_idle_time=0,
        start_id="0-0",
        count=8,
    )
    assert [raw_id.decode() for raw_id, _ in claimed] == [old_id]
    assert not old.ack(old_id)
    assert newer.ack(old_id)
