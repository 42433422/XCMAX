"""Execution selection, coroutine ownership and mainline response adaptation."""

from __future__ import annotations

import asyncio
import os
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


def env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def use_mainline(context: Context | None, truthy: Callable[[str], bool]) -> bool:
    context = context if isinstance(context, dict) else {}
    if context.get("use_legacy_chat_adapter") is True:
        return False
    if context.get("use_ai_chat_mainline") is True:
        return True
    if truthy("XCAGI_USE_LEGACY_CHAT_ADAPTER"):
        return False
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def allow_legacy_fallback(context: Context | None, truthy: Callable[[str], bool]) -> bool:
    context = context if isinstance(context, dict) else {}
    return bool(
        context.get("allow_legacy_chat_adapter") is True
        or truthy("XCAGI_ALLOW_LEGACY_CHAT_FALLBACK")
        or os.environ.get("PYTEST_CURRENT_TEST")
    )


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
    file_context = runtime_context.get("file_context")
    if not isinstance(file_context, dict):
        file_context = runtime_context.get("file_analysis")
    if not isinstance(file_context, dict):
        file_context = {}
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


def legacy_requires_token_payload(parsed: Payload) -> Payload:
    records = parsed.get("legacy_tool_records")
    data = {
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
    }
    if isinstance(records, list) and records:
        data["legacy_tool_records"] = records
    return {
        "success": True,
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
        "message": parsed.get("message"),
        "response": parsed.get("message"),
        "data": data,
    }


def reply_has_legacy_tool_records(reply: Any) -> bool:
    return isinstance(reply, dict) and isinstance(
        reply.get("legacy_tool_records") or reply.get("_tool_records"), list
    )
