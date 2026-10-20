"""Trusted invocation budget for cooperative I/O, not arbitrary-tool cancellation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass
class InvocationBudget:
    deadline: float
    uncertain: list[dict[str, str]] = field(default_factory=list)


_DEADLINE: ContextVar[InvocationBudget | None] = ContextVar("tool_execution_deadline", default=None)


@contextmanager
def invocation_deadline(deadline: float) -> Iterator[InvocationBudget]:
    parent = _DEADLINE.get()
    budget = (
        InvocationBudget(min(parent.deadline, deadline), parent.uncertain)
        if parent
        else InvocationBudget(deadline)
    )
    token = _DEADLINE.set(budget)
    try:
        yield budget
    finally:
        _DEADLINE.reset(token)


def build_http_request(
    client_factory: Callable[..., Any] | None = None,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    # Capture before employee coroutines move to a helper thread/event loop.
    invocation = _DEADLINE.get()

    async def request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        owners = [owner for owner in (invocation, _DEADLINE.get()) if owner is not None]
        budget = min(owner.deadline for owner in owners) - time.monotonic() if owners else None
        if budget is not None and budget <= 0:
            return {"ok": False, "error": "invocation deadline expired", "outcome": "not_started"}
        try:
            async with asyncio.timeout(budget):
                async with (client_factory or httpx.AsyncClient)(
                    timeout=kw.pop("timeout", 30)
                ) as client:
                    resp = await client.request(method, url, **kw)
                    try:
                        body = resp.json()
                    except RECOVERABLE_ERRORS:
                        body = resp.text
                    return {"ok": resp.is_success, "status": resp.status_code, "body": body}
        except (TimeoutError, httpx.TimeoutException):
            for owner in owners:
                marker = {"kind": "http_timeout", "method": method}
                if marker not in owner.uncertain:
                    owner.uncertain.append(marker)
            return {
                "ok": False,
                "error": "invocation deadline exceeded",
                "outcome": "unknown",
                "retryable": False,
            }
        except RECOVERABLE_ERRORS as exc:
            return {"ok": False, "error": repr(exc)}

    return request


def build_http_helpers() -> tuple[
    Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[dict[str, Any]]]
]:
    request = build_http_request()

    async def get(url: str, **kw: Any) -> dict[str, Any]:
        return await request("GET", url, **kw)

    async def post(url: str, json_body: Any = None, **kw: Any) -> dict[str, Any]:
        if json_body is not None:
            kw["json"] = json_body
        return await request("POST", url, **kw)

    return get, post
