"""Run employee coroutines synchronously without dropping host context."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context


def run_employee_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(copy_context().run, asyncio.run, coro).result()
