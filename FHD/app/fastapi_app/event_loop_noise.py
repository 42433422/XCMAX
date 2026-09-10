"""Windows ProactorEventLoop 良性异常过滤（桌面端日志噪声治理）。

对端强制断开后，``_ProactorBasePipeTransport._call_connection_lost`` 会在清理
阶段抛 ``ConnectionResetError``（WinError 10054），asyncio 默认把它交给 loop 的
exception handler 打印，导致后端日志被同一异常刷屏（win32 实测 81 次/2000 行）。
这是 CPython 在 3.12.1 前未修复的已知竞态，连接本身早已失效，忽略即可；其余
异常仍完整委托给原 handler，不吞掉任何真实错误。
"""

from __future__ import annotations

import asyncio


def install_proactor_reset_filter() -> None:
    """在当前运行的事件循环上安装 10054 噪声过滤器（幂等）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    current = loop.get_exception_handler()
    if getattr(current, "_xcagi_proactor_filter", False):
        return

    def _filtered_handler(current_loop, context):
        exc = context.get("exception")
        message = str(context.get("message", ""))
        if (
            isinstance(exc, ConnectionResetError)
            and getattr(exc, "winerror", None) == 10054
            and "_call_connection_lost" in message
        ):
            return
        if current is not None:
            current(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    _filtered_handler._xcagi_proactor_filter = True  # type: ignore[attr-defined]
    loop.set_exception_handler(_filtered_handler)
