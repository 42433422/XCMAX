"""真实行为测试：AIOPEN 虚拟光标 WS 会话池 hub。

覆盖 ``app/infrastructure/aiopen/cursor_hub.py`` 中 dispatch 下发/回执/超时/
发送失败分支、handle_client_message 回执关联、_log_command 溢出裁剪等逻辑。

不 mock hub 本身——用 fake WebSocket 直驱真实方法，离线确定性。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.infrastructure.aiopen.cursor_hub import (
    _MAX_COMMAND_LOG,
    AiOpenCursorHub,
)


class _FakeWS:
    """记录 send_text 调用的假 WebSocket。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.raise_on_send: BaseException | None = None

    async def send_text(self, text: str) -> None:
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append(text)


# ---- dispatch: 无会话分支 ---------------------------------------------------


async def test_dispatch_no_sessions_returns_failure() -> None:
    hub = AiOpenCursorHub()
    result = await hub.dispatch("click", {"x": 1})
    assert result["success"] is False
    assert "没有在线" in result["message"]
    assert result["online_sessions"] == []


async def test_dispatch_explicit_session_not_online() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    await hub.connect("s1", ws)  # type: ignore[arg-type]
    # 指定一个不存在的 session_id -> 落入失败分支
    result = await hub.dispatch("click", session_id="missing")
    assert result["success"] is False
    assert "没有在线" in result["message"]
    assert result["online_sessions"] == ["s1"]


# ---- dispatch: 成功路径（dict result，补默认键） ----------------------------


async def test_dispatch_success_dict_result_sets_defaults() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    await hub.connect("s1", ws)  # type: ignore[arg-type]

    async def _runner() -> dict[str, Any]:
        return await hub.dispatch("click", {"x": 5}, timeout=2.0)

    task = asyncio.ensure_future(_runner())
    # 等到指令真正发出（payload 已 send_text）
    for _ in range(100):
        if ws.sent:
            break
        await asyncio.sleep(0)
    assert ws.sent, "dispatch 应当已发送指令"

    payload = json.loads(ws.sent[0])
    assert payload["type"] == "command"
    assert payload["action"] == "click"
    assert payload["params"] == {"x": 5}
    req_id = payload["id"]

    # 前端回执：result 是 dict，但缺 success/session_id -> setdefault 填充
    delivered = hub.handle_client_message(json.dumps({"id": req_id, "result": {"value": 42}}))
    assert delivered is True

    result = await task
    assert result["value"] == 42
    assert result["success"] is True  # setdefault 填充
    assert result["session_id"] == "s1"  # setdefault 填充


async def test_dispatch_success_default_session_picks_first() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    await hub.connect("only", ws)  # type: ignore[arg-type]

    async def _runner() -> dict[str, Any]:
        return await hub.dispatch("scroll", timeout=2.0)

    task = asyncio.ensure_future(_runner())
    for _ in range(100):
        if ws.sent:
            break
        await asyncio.sleep(0)
    payload = json.loads(ws.sent[0])
    # session_id 为空 -> 取第一个在线会话；params 为空 -> {}
    assert payload["params"] == {}
    hub.handle_client_message(json.dumps({"id": payload["id"], "result": {"ok": True}}))
    result = await task
    assert result["session_id"] == "only"


# ---- dispatch: 回执 result 非 dict -> 包裹分支 (line 128) -------------------


async def test_dispatch_non_dict_result_wrapped() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    await hub.connect("s1", ws)  # type: ignore[arg-type]

    async def _runner() -> dict[str, Any]:
        return await hub.dispatch("type", timeout=2.0)

    task = asyncio.ensure_future(_runner())
    for _ in range(100):
        if ws.sent:
            break
        await asyncio.sleep(0)
    req_id = json.loads(ws.sent[0])["id"]

    # 回执里 result 不是 dict -> handle_client_message 把整个 msg 作为 future 值
    # 然后 dispatch 看到 result 是 dict(=msg) -> 仍走 setdefault 路径。
    # 为命中 line 128(result 非 dict 包裹)，直接把 future 设为标量。
    fut = hub._pending[req_id]
    fut.set_result("done")  # 标量

    result = await task
    assert result == {"success": True, "session_id": "s1", "result": "done"}


# ---- dispatch: 发送失败 (RECOVERABLE_ERRORS) 分支 (108-113) -----------------


async def test_dispatch_send_failure_disconnects_and_returns_error() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    ws.raise_on_send = ConnectionError("socket closed")  # 属于 RECOVERABLE_ERRORS
    await hub.connect("s1", ws)  # type: ignore[arg-type]

    result = await hub.dispatch("click", timeout=2.0)
    assert result["success"] is False
    assert "指令下发失败" in result["message"]
    # 发送失败后会话被断开，pending 清空
    assert hub.session_ids() == []
    assert hub._pending == {}


# ---- dispatch: 超时分支 (116-121) ------------------------------------------


async def test_dispatch_timeout_branch() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    await hub.connect("s1", ws)  # type: ignore[arg-type]

    # 极短超时且不送回执 -> 命中 TimeoutError 分支
    result = await hub.dispatch("click", timeout=0.01)
    assert result["success"] is False
    assert "回执超时" in result["message"]
    assert result["action"] == "click"
    # finally 清理了 pending
    assert hub._pending == {}


# ---- handle_client_message 各分支 (132-143) --------------------------------


def test_handle_client_message_invalid_json_returns_false() -> None:
    hub = AiOpenCursorHub()
    assert hub.handle_client_message("not-json{") is False


def test_handle_client_message_non_dict_returns_false() -> None:
    hub = AiOpenCursorHub()
    # 合法 JSON 但不是 dict
    assert hub.handle_client_message("[1, 2, 3]") is False


def test_handle_client_message_unknown_id_returns_false() -> None:
    hub = AiOpenCursorHub()
    assert hub.handle_client_message(json.dumps({"id": "nope"})) is False


def test_handle_client_message_missing_id_returns_false() -> None:
    hub = AiOpenCursorHub()
    # 无 id -> req_id 为 "" -> _pending 中无此键
    assert hub.handle_client_message(json.dumps({"result": {}})) is False


async def test_handle_client_message_already_done_future_returns_false() -> None:
    hub = AiOpenCursorHub()
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    fut.set_result({"x": 1})  # 已完成
    hub._pending["abc"] = fut
    assert hub.handle_client_message(json.dumps({"id": "abc"})) is False


async def test_handle_client_message_sets_dict_result() -> None:
    hub = AiOpenCursorHub()
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    hub._pending["abc"] = fut
    ok = hub.handle_client_message(json.dumps({"id": "abc", "result": {"k": "v"}}))
    assert ok is True
    assert fut.result() == {"k": "v"}


async def test_handle_client_message_non_dict_result_uses_whole_msg() -> None:
    hub = AiOpenCursorHub()
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    hub._pending["abc"] = fut
    # result 非 dict -> future 收到整个 msg
    msg = {"id": "abc", "result": "scalar", "extra": 1}
    ok = hub.handle_client_message(json.dumps(msg))
    assert ok is True
    assert fut.result() == msg


# ---- 会话管理与日志 --------------------------------------------------------


async def test_connect_disconnect_and_sessions_info() -> None:
    hub = AiOpenCursorHub()
    ws = _FakeWS()
    await hub.connect("s1", ws, meta={"role": "screen"})  # type: ignore[arg-type]
    assert hub.session_ids() == ["s1"]
    info = hub.sessions_info()
    assert len(info) == 1
    assert info[0]["session_id"] == "s1"
    assert info[0]["role"] == "screen"
    assert "connected_at" in info[0]

    await hub.disconnect("s1")
    assert hub.session_ids() == []
    assert hub.sessions_info() == []


def test_log_command_overflow_trims_to_max() -> None:
    hub = AiOpenCursorHub()
    total = _MAX_COMMAND_LOG + 25
    for i in range(total):
        hub._log_command({"id": str(i)})
    # 溢出裁剪到 _MAX_COMMAND_LOG
    assert len(hub._command_log) == _MAX_COMMAND_LOG
    # 最旧的被删除，保留尾部
    assert hub._command_log[0]["id"] == str(total - _MAX_COMMAND_LOG)
    assert hub._command_log[-1]["id"] == str(total - 1)


def test_recent_commands_limit() -> None:
    hub = AiOpenCursorHub()
    for i in range(10):
        hub._log_command({"id": str(i)})
    recent = hub.recent_commands(limit=3)
    assert [e["id"] for e in recent] == ["7", "8", "9"]
    # limit<=0 被夹到 1
    assert len(hub.recent_commands(limit=0)) == 1


def test_recent_commands_empty() -> None:
    hub = AiOpenCursorHub()
    assert hub.recent_commands() == []
