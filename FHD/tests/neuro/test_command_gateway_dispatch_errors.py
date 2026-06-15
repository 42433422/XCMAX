"""COVERAGE_RAMP C3.1: CommandGateway 错误路径覆盖。

覆盖：
- prepare_command_event 在无 running loop 时抛 RuntimeError
- wait_for_result 收到 unknown reply_id 抛 KeyError
- wait_for_result 超时 -> 取消 future / 清理 pending
- cancel_pending 取消未 done future
- resolve 收到 late reply (pending 已清) -> logger.debug
- resolve 收到 error -> future.set_exception
- try_complete_command_reply 调用 gateway.resolve
- get_command_gateway 单例化
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.neuro_bus import command_gateway as cg
from app.neuro_bus.command_gateway import CommandGateway, try_complete_command_reply
from app.neuro_bus.events.base import EventPriority, NeuroEvent

# ---------------------------------------------------------------------------
# prepare_command_event
# ---------------------------------------------------------------------------


def test_prepare_command_event_requires_running_loop():
    gw = CommandGateway()
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    with pytest.raises(RuntimeError, match="requires a running event loop"):
        gw.prepare_command_event(ev)


@pytest.mark.asyncio
async def test_prepare_command_event_writes_reply_id():
    gw = CommandGateway()
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)
    assert ev.payload["_command_reply_id"] == rid
    assert rid in gw._pending
    gw._pending.pop(rid, None)


# ---------------------------------------------------------------------------
# wait_for_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_result_unknown_reply_id_raises_keyerror():
    gw = CommandGateway()
    with pytest.raises(KeyError, match="unknown command reply_id"):
        await gw.wait_for_result("nope", timeout=0.1)


@pytest.mark.asyncio
async def test_wait_for_result_timeout_cancels_and_cleans_pending():
    gw = CommandGateway()
    ev = NeuroEvent("cmd.slow", {}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)
    with pytest.raises(asyncio.TimeoutError):
        await gw.wait_for_result(rid, timeout=0.05)
    assert rid not in gw._pending


# ---------------------------------------------------------------------------
# cancel_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_pending_cancels_pending_future():
    gw = CommandGateway()
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)
    fut = gw._pending[rid]
    assert not fut.done()
    gw.cancel_pending(rid)
    assert fut.cancelled()
    assert rid not in gw._pending


def test_cancel_pending_unknown_rid_no_op():
    gw = CommandGateway()
    gw.cancel_pending("nope")  # 不抛


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_unknown_rid_logs_debug(caplog):
    gw = CommandGateway()
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    # 不调用 prepare_command_event，ev.payload 中无 _command_reply_id
    with caplog.at_level("DEBUG", logger="app.neuro_bus.command_gateway"):
        gw.resolve(ev, result={"x": 1})
    # 静默退出，无异常


@pytest.mark.asyncio
async def test_resolve_sets_exception_on_error():
    gw = CommandGateway()
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)
    err = ValueError("boom")
    # 真实 request-reply：先进入 wait_for_result（已持有 future），handler 再 resolve。
    # 若先 resolve 会 pop 掉 pending，wait_for_result 反而 KeyError——非该用例意图。
    asyncio.get_running_loop().call_soon(gw.resolve, ev, None, err)
    with pytest.raises(ValueError, match="boom"):
        await gw.wait_for_result(rid, timeout=0.5)


@pytest.mark.asyncio
async def test_resolve_late_reply_logs_debug_and_noop(caplog):
    gw = CommandGateway()
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    rid = gw.prepare_command_event(ev)
    gw._pending.pop(rid)  # 模拟已被清
    with caplog.at_level("DEBUG", logger="app.neuro_bus.command_gateway"):
        gw.resolve(ev, result={"v": 1})  # 不抛


# ---------------------------------------------------------------------------
# try_complete_command_reply / get_command_gateway
# ---------------------------------------------------------------------------


def test_try_complete_command_reply_invokes_gateway(monkeypatch):
    fake_gw = MagicMock()
    monkeypatch.setattr(cg, "get_command_gateway", lambda: fake_gw)
    ev = NeuroEvent("cmd", {}, priority=EventPriority.NORMAL)
    try_complete_command_reply(ev, result={"a": 1})
    fake_gw.resolve.assert_called_once_with(ev, result={"a": 1}, error=None)


def test_get_command_gateway_singleton():
    cg._gateway = None
    a = cg.get_command_gateway()
    b = cg.get_command_gateway()
    assert a is b
    cg._gateway = None
