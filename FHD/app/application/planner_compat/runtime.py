"""Execution selection, coroutine ownership and mainline response adaptation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from app.utils.operational_errors import BOUNDARY_ERRORS

from .protocols import ChatBody, Context, Payload, ReplyFormatter

T = TypeVar("T")


class MainlineService(Protocol):
    def process_chat(
        self,
        *,
        user_id: str,
        message: str,
        context: Context,
        source: str | None,
        file_context: Context,
    ) -> Any: ...


async def await_with_timeout(awaitable: Awaitable[T], *, timeout: float) -> T:
    """Own and consume the task even when the timeout boundary raises early."""
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.wait_for(task, timeout=timeout)
    except BOUNDARY_ERRORS + (asyncio.CancelledError,):
        if not task.done():
            task.cancel()
        try:
            await task
        except BOUNDARY_ERRORS + (asyncio.CancelledError,):
            pass
        raise


def merge_kitten_attachments(payload: Payload, kitten_extra: Payload | None) -> Payload:
    if not kitten_extra:
        return payload
    enriched = dict(payload)
    data = enriched.get("data") if isinstance(enriched.get("data"), dict) else {}
    enriched["data"] = {
        **dict(data or {}),
        **{k: v for k, v in kitten_extra.items() if v is not None},
    }
    return enriched


def resolve_file_context(runtime_context: Context) -> Context:
    file_context = runtime_context.get("file_context")
    if not isinstance(file_context, dict):
        file_context = runtime_context.get("file_analysis")
    return file_context if isinstance(file_context, dict) else {}


async def execute_mainline(
    service: MainlineService,
    body: ChatBody,
    runtime_context: Context,
    *,
    message: str | None,
    kitten_extra: Payload | None,
    reply: ReplyFormatter,
    merge_attachments: Callable[[Payload, Payload | None], Payload],
) -> Payload:
    file_context = resolve_file_context(runtime_context)
    payload = await asyncio.to_thread(
        service.process_chat,
        user_id=str(body.user_id or "default"),
        message=str(message if message is not None else getattr(body, "message", "") or ""),
        context=dict(runtime_context or {}),
        source=body.source,
        file_context=file_context,
    )
    if not isinstance(payload, dict):
        payload = reply(str(payload))
    return merge_attachments(payload, kitten_extra)
