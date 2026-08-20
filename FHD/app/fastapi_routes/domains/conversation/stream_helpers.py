"""SSE streaming helpers for the XCAGI compatibility conversation API."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import threading
import time
from typing import TYPE_CHECKING, Any

from fastapi import Request

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.fastapi_routes.domains.conversation.helpers import XcagiCompatChatBody


def _facade() -> Any:
    from app.fastapi_routes.domains.conversation import helpers

    return helpers


def _xcagi_guarded_planner_stream_events(
    body: XcagiCompatChatBody,
    *,
    runtime_context: dict[str, Any] | None,
    workspace_root: str,
    client: Any,
):
    event_queue: queue.Queue[Any] = queue.Queue()
    done_marker = object()

    def _worker() -> None:
        try:
            for ev in _facade().chat_stream_sse_events(
                body.message,
                runtime_context=runtime_context or None,
                system_prompt=body.system_prompt,
                workspace_root=workspace_root,
                db_write_token=body.db_write_token,
                client=client,
            ):
                event_queue.put(ev)
        except BOUNDARY_ERRORS as exc:
            event_queue.put(exc)
        finally:
            event_queue.put(done_marker)

    threading.Thread(target=_worker, daemon=True, name="xcagi-chat-stream-guard").start()
    total_timeout = _facade()._xcagi_chat_timeout_seconds()
    first_token_timeout = min(_facade()._xcagi_stream_first_token_timeout_seconds(), total_timeout)
    idle_notice_seconds = _facade()._xcagi_stream_idle_notice_seconds()
    started_at = time.monotonic()
    first_event_seen = True
    yield {
        "type": "tool_progress",
        "label": "模型服务",
        "text": "模型服务已接收任务，正在思考…",
        "phase": "accepted",
    }
    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= total_timeout:
            raise TimeoutError(
                f"流式对话总超时（>{int(total_timeout)} 秒）。请稍后重试，或缩短问题范围。"
            )
        wait_timeout = first_token_timeout if not first_event_seen else idle_notice_seconds
        wait_timeout = max(0.2, min(wait_timeout, total_timeout - elapsed))
        try:
            item = event_queue.get(timeout=wait_timeout)
        except queue.Empty:
            elapsed_int = int(time.monotonic() - started_at)
            if not first_event_seen:
                raise TimeoutError(
                    f"流式对话首包超时（>{int(first_token_timeout)} 秒）。模型服务暂未返回首个分片，请稍后重试。"
                )
            yield {
                "type": "token",
                "text": f"\n（仍在处理中，已等待 {elapsed_int} 秒，请稍候…）\n",
                "ephemeral": True,
            }
            continue
        if item is done_marker:
            return
        if isinstance(item, Exception):
            exc = _facade()._xcagi_chat_http_exc(item)
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            yield {"type": "error", "message": detail, "status_code": exc.status_code}
            return
        first_event_seen = True
        yield item


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
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        _facade().set_llm_mode(m)
    (runtime_context, _) = _facade()._merge_runtime_context_with_message_paths(
        body.context, body.message
    )
    runtime_context = _facade().runtime_context_with_tier(runtime_context, ai_tier)
    (ok_read, read_req) = _facade()._ensure_chat_db_read_authorized(
        request, message=body.message, provided_token=body.db_read_token
    )
    if not ok_read and read_req:
        yield _facade()._sse_event_line(
            {"type": "token", "text": f"[需要授权: {read_req.get('token_description')}]"}
        )
        yield _facade()._sse_event_line(
            {
                "type": "requires_token",
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
            }
        )
        return
    if ok_read and _facade()._message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True
    intr = _facade().planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = _facade().runtime_context_after_workflow_interrupt(runtime_context)
        yield _facade()._sse_event_line({"type": "token", "text": intr})
        payload = _facade()._xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
        payload = _facade().attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=cleared,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        yield _facade()._sse_event_line({"type": "done", "result": payload})
        return
    vector_error = _facade()._ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        yield _facade()._sse_event_line({"type": "error", "message": vector_error})
        return
    workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
    llm_client = _facade().create_modstore_openai_client_from_request(request)
    reply_parts: list[str] = []
    try:
        halted_for_write_token = False
        for ev in _facade()._xcagi_guarded_planner_stream_events(
            body, runtime_context=runtime_context, workspace_root=workspace_root, client=llm_client
        ):
            et = ev.get("type")
            if et == "error":
                yield _facade()._sse_event_line(ev)
                return
            if et == "token":
                text = str(ev.get("text") or "")
                if not ev.get("ephemeral"):
                    reply_parts.append(text)
                yield _facade()._sse_event_line(ev)
            elif et == "requires_token":
                yield _facade()._sse_event_line(ev)
                halted_for_write_token = True
                break
            elif et == "done":
                continue
            else:
                yield _facade()._sse_event_line(ev)
        if halted_for_write_token:
            return
        merged = _facade().sanitize_model_chat_reply("".join(reply_parts))
        if not merged.strip():
            msg = "模型服务已完成请求，但没有返回可显示的正文。若附带图片，请确认当前账号已启用视觉模型，或上传文字更清晰的截图。"
            yield _facade()._sse_event_line({"type": "error", "message": msg})
            return
        thinking = _facade()._thinking_steps_from_planner_stream_text(merged)
        if thinking:
            done_reply: str | dict = {"response": merged, "thinking_steps": thinking}
        else:
            done_reply = merged
        payload = _facade()._xcagi_compat_reply_payload(done_reply)
        payload = _facade().attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=runtime_context,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        yield _facade()._sse_event_line({"type": "done", "result": payload})
    except RECOVERABLE_ERRORS as e:
        exc = _facade()._xcagi_chat_http_exc(e)
        yield _facade()._sse_event_line(
            {
                "type": "error",
                "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "status_code": exc.status_code,
            }
        )
