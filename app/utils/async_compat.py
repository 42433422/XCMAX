"""
Sync/async 双路径装饰器工厂。

供 retry、metrics、monitored 等装饰器在 FastAPI 异步生态中正确分支。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def dual_wrapper(
    sync_fn: Callable[[Callable[P, R]], Callable[P, R]],
    async_fn: Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]],
) -> Callable[[Callable[P, R | Awaitable[R]]], Callable[P, R | Awaitable[R]]]:
    """根据被装饰函数是否为 coroutine 选择 sync 或 async 包装器。"""

    def decorator(func: Callable[P, R | Awaitable[R]]) -> Callable[P, R | Awaitable[R]]:
        if inspect.iscoroutinefunction(func):
            return async_fn(func)  # type: ignore[arg-type, return-value]
        return sync_fn(func)  # type: ignore[arg-type, return-value]

    return decorator


def wrap_sync_async(
    func: Callable[P, R | Awaitable[R]],
    *,
    sync_body: Callable[[Callable[P, R | Awaitable[R]], tuple, dict], R],
    async_body: Callable[[Callable[P, R | Awaitable[R]], tuple, dict], Awaitable[R]],
) -> Callable[P, R | Awaitable[R]]:
    """通用 sync/async 装饰器内核。"""

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await async_body(func, args, kwargs)

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return sync_body(func, args, kwargs)

    return sync_wrapper


async def async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
