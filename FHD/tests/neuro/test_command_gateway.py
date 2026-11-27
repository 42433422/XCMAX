import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.neuro_bus.command_gateway import CommandGateway
from app.neuro_bus.events.events_base import EventPriority, NeuroEvent


@pytest.mark.asyncio
async def test_command_gateway_wait_and_resolve():
    gw = CommandGateway()
    ev = NeuroEvent("test.cmd", {"x": 1}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)

    async def resolve_later():
        await asyncio.sleep(0.02)
        gw.resolve(ev, {"success": True, "v": 42})

    asyncio.create_task(resolve_later())
    out = await gw.wait_for_result(rid, timeout=2.0)
    assert out["success"] is True
    assert out["v"] == 42


@pytest.mark.asyncio
async def test_command_gateway_timeout():
    gw = CommandGateway()
    ev = NeuroEvent("test.slow", {}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)
    with pytest.raises(asyncio.TimeoutError):
        await gw.wait_for_result(rid, timeout=0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streams", "pubsub"])
async def test_manually_correlated_command_is_not_forwarded(monkeypatch, transport):
    from app.neuro_bus.bus import NeuroBus
    from app.neuro_bus.transports.redis_pubsub import RedisPubSubBridge
    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    monkeypatch.setenv("FHD_ENV", "development")
    monkeypatch.setenv("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "")
    monkeypatch.setenv("XCAGI_NEURO_BUS_REDIS_PUBSUB", "0")
    bus = NeuroBus(enable_metrics=False)
    bridge = MagicMock(spec=RedisStreamsBridge if transport == "streams" else RedisPubSubBridge)
    bridge.publish_remote.return_value = "1-0"
    if transport == "streams":
        bridge.stop = AsyncMock()
    bus._redis_bridge = bridge
    gateway = CommandGateway()
    event = NeuroEvent("test.command", {"_command_reply_id": "manual", "local_only": False})
    gateway._pending["manual"] = asyncio.get_running_loop().create_future()
    calls = []

    async def handle(value):
        calls.append(value)
        gateway.resolve(value, {"success": True})

    bus.subscribe("test.command", handle)
    try:
        await bus.start()
        assert bus.publish(event)
        assert await gateway.wait_for_result("manual", 0.2) == {"success": True}
        assert len(calls) == 1
        bridge.publish_remote.assert_not_called()
        assert not gateway._pending
    finally:
        await bus.stop()
