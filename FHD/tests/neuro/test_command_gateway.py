import asyncio

import pytest

from app.neuro_bus.command_gateway import CommandGateway
from app.neuro_bus.events.base import EventPriority, NeuroEvent


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
