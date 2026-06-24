"""Run asyncio coroutines from sync contexts (thread-pool fallback when loop is running).

契约：

- **无运行中的事件循环**（典型：同步路由、脚本主线程）：使用 ``asyncio.run(coro)``，每次调用新建并关闭
  一个 loop —— 与 ``httpx.AsyncClient`` 等「每次请求新建客户端」的模式兼容。
- **已有运行中的 loop**（典型：FastAPI 已在异步栈内又调用了同步封装）：在 **守护线程** 内单独
  ``asyncio.run(coro)``，避免在 running loop 上嵌套 ``run_until_complete``。不要在协程内部再递归调用
  ``run_coro_sync``。
- 不要在协程里假定跨调用的 loop 长期存在；LLM 路径禁止进程级 ``AsyncClient`` 单例（见 ``llm_chat_proxy``）。
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from typing import Any, Dict, TypeVar

T = TypeVar("T")


def run_coro_sync(coro: Any) -> Any:
    """Execute ``coro`` synchronously; safe when called from worker threads."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: Dict[str, Any] = {}
    error: Dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as e:  # noqa: PERF203
            error["err"] = e

    # 用 copy_context() 让守护线程继承当前上下文（含平台模型作用域），
    # 否则新线程的 contextvar 为默认值，作用域会丢失。
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(_runner,), daemon=True)
    t.start()
    t.join()
    if "err" in error:
        raise error["err"]
    return result.get("value")


__all__ = ["run_coro_sync"]
