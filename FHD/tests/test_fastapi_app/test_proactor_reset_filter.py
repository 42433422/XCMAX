"""Windows Proactor 10054 噪声过滤器（lifespan._install_proactor_reset_filter）。

win32 实测：对端强制断开后 _call_connection_lost 抛 ConnectionResetError
(WinError 10054)，asyncio 默认 handler 刷屏（81 次/2000 行）。过滤器只吞这一
种良性异常，其余必须原样委托，防止吞掉真实错误。
"""

from __future__ import annotations

import asyncio

from app.fastapi_app.lifespan import _install_proactor_reset_filter


def _reset_error(winerror: int = 10054) -> ConnectionResetError:
    exc = ConnectionResetError(winerror, "远程主机强迫关闭了一个现有的连接")
    exc.winerror = winerror  # type: ignore[attr-defined]
    return exc


_PROACOR_LOST_MSG = (
    "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)"
)


def test_filter_suppresses_benign_proactor_reset():
    forwarded: list[tuple] = []

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda l, ctx: forwarded.append((l, ctx)))
        _install_proactor_reset_filter()
        loop.call_exception_handler({"message": _PROACOR_LOST_MSG, "exception": _reset_error()})

    asyncio.run(scenario())
    assert forwarded == []


def test_filter_delegates_other_exceptions_to_previous_handler():
    forwarded: list[dict] = []

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda l, ctx: forwarded.append(ctx))
        _install_proactor_reset_filter()
        loop.call_exception_handler({"message": "some real failure", "exception": ValueError("x")})
        # 非 10054 的 ConnectionResetError 同样不得吞掉
        loop.call_exception_handler(
            {"message": _PROACOR_LOST_MSG, "exception": _reset_error(10053)}
        )
        # 10054 但回调不是 _call_connection_lost 也不得吞掉
        loop.call_exception_handler(
            {"message": "Exception in callback something_else", "exception": _reset_error()}
        )

    asyncio.run(scenario())
    assert [ctx["message"] for ctx in forwarded] == [
        "some real failure",
        _PROACOR_LOST_MSG,
        "Exception in callback something_else",
    ]


def test_install_is_idempotent_and_marks_handler():
    async def scenario():
        loop = asyncio.get_running_loop()
        _install_proactor_reset_filter()
        first = loop.get_exception_handler()
        _install_proactor_reset_filter()
        second = loop.get_exception_handler()
        assert first is second
        assert getattr(first, "_xcagi_proactor_filter", False) is True

    asyncio.run(scenario())
