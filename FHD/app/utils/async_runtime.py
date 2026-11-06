"""Helpers for bridging synchronous call sites to coroutines safely."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

# Named boundary so the broad-except gate allows intentional cleanup when
# ``executor.submit`` fails before the coroutine reaches a loop.
_SUBMIT_FAILURES: tuple[type[BaseException], ...] = (BaseException,)


def run_coroutine_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` from synchronous code without nested event-loop conflicts.

    ``asyncio.run`` / ``loop.run_until_complete`` raise ``RuntimeError`` when the
    current thread already has a running loop.  In that case the coroutine is
    executed on a short-lived worker thread with its own loop.  The caller is
    synchronous by contract, so blocking until the result is unavoidable.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="async-bridge"
    )
    try:
        future = executor.submit(asyncio.run, coro)
    except _SUBMIT_FAILURES:
        # The coroutine never reached a loop; close it to avoid
        # "coroutine ... was never awaited" warnings.
        coro.close()
        executor.shutdown(wait=False)
        raise
    try:
        return future.result()
    finally:
        executor.shutdown(wait=False)
