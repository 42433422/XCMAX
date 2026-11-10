"""SSE streaming helpers for the XCAGI compatibility conversation API."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import TYPE_CHECKING, Any

from fastapi import Request

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.fastapi_routes.domains.conversation.helpers import XcagiCompatChatBody


def _facade() -> Any:
    from app.fastapi_routes.domains.conversation import helpers

    return helpers


def _sse_event_line(payload: dict) -> bytes:
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def _thinking_steps_from_planner_stream_text(merged: str) -> str | None:
    if not (merged or "").strip():
        return None
    lines: list[str] = []
    for m in re.finditer("\\[正在调用工具:[^\\]\\n]+\\]", merged):
        s = m.group(0).strip()
        if s and s not in lines:
            lines.append(s)
    for m in re.finditer("\\[工具已返回[^\\]\\n]*\\]|\\[工具未成功[^\\]\\n]*\\]", merged):
        s = m.group(0).strip()
        if s and s not in lines:
            lines.append(s)
    for m in re.finditer("\\[需要授权:[^\\]\\n]+\\]|\\[请提供令牌:[^\\]\\n]+\\]", merged):
        s = m.group(0).strip()
        if s and s not in lines:
            lines.append(s)
    if not lines:
        return None
    return "\n".join(lines)


def strip_planner_stream_markers(merged: str) -> tuple[str, str | None]:
    text = str(merged or "")
    thinking = _facade()._thinking_steps_from_planner_stream_text(text)
    cleaned = re.sub(
        "\\[(?:正在调用工具:[^\\]\\n]+|工具已返回[^\\]\\n]*|工具未成功[^\\]\\n]*|需要授权:[^\\]\\n]+|请提供令牌:[^\\]\\n]+)\\]",
        "",
        text,
    )
    cleaned = re.sub("\\s{2,}", " ", cleaned).strip()
    return (cleaned, thinking)


async def _xcagi_planner_stream_bytes_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str
):
    """Async generator wrapper around _xcagi_planner_stream_bytes.

    Runs the sync generator in a background thread and feeds items through an
    asyncio.Queue so the event loop is NEVER blocked.  This avoids the
    Starlette BaseHTTPMiddleware / anyio thread-pool deadlock that occurs when
    a sync StreamingResponse generator is iterated via iterate_in_threadpool
    while the middleware task-group is still open.
    """
    _SENTINEL = object()
    async_q: asyncio.Queue = asyncio.Queue(maxsize=128)
    loop = asyncio.get_running_loop()

    def _feed_queue() -> None:
        try:
            for chunk in _facade()._xcagi_planner_stream_bytes(request, body, ai_tier=ai_tier):
                asyncio.run_coroutine_threadsafe(async_q.put(chunk), loop).result(timeout=120)
        except BOUNDARY_ERRORS as exc:
            err_msg = str(exc).strip() or exc.__class__.__name__
            err_line = _facade()._sse_event_line({"type": "error", "message": err_msg})
            try:
                asyncio.run_coroutine_threadsafe(async_q.put(err_line), loop).result(timeout=5)
            except RECOVERABLE_ERRORS:
                pass
        finally:
            asyncio.run_coroutine_threadsafe(async_q.put(_SENTINEL), loop).result(timeout=5)

    thread = threading.Thread(target=_feed_queue, daemon=True, name="xcagi-stream-async-bridge")
    thread.start()
    while True:
        item = await async_q.get()
        if item is _SENTINEL:
            break
        yield item


def _xcagi_planner_stream_bytes(request: Request, body: XcagiCompatChatBody, *, ai_tier: str):
    """Compatibility facade; the shared online stream now has one mainline."""
    from app.fastapi_routes.xcagi_compat_chat_stream import _xcagi_planner_stream_bytes as mainline

    yield from mainline(request, body, ai_tier=ai_tier)
