"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


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
            for chunk in _xcagi_planner_stream_bytes(request, body, ai_tier=ai_tier):
                asyncio.run_coroutine_threadsafe(async_q.put(chunk), loop).result(timeout=120)
        except BaseException as exc:  # noqa: BLE001
            err_msg = str(exc).strip() or exc.__class__.__name__
            err_line = _sse_event_line({"type": "error", "message": err_msg})
            try:
                asyncio.run_coroutine_threadsafe(async_q.put(err_line), loop).result(timeout=5)
            except RECOVERABLE_ERRORS:
                pass
        finally:
            asyncio.run_coroutine_threadsafe(async_q.put(_SENTINEL), loop).result(timeout=5)

    thread = threading.Thread(target=_feed_queue, daemon=True, name="xcagi-stream-async-bridge")
    thread.start()

    item = await async_q.get()
    while item is not _SENTINEL:
        yield item
        item = await async_q.get()


def _xcagi_planner_stream_bytes(request: Request, body: XcagiCompatChatBody, *, ai_tier: str):
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)
    runtime_context, _ = _merge_runtime_context_with_message_paths(body.context, body.message)
    runtime_context = runtime_context_with_tier(runtime_context, ai_tier)
    ok_read, read_req = _ensure_chat_db_read_authorized(
        request,
        message=body.message,
        provided_token=body.db_read_token,
    )
    if not ok_read and read_req:
        yield _sse_event_line(
            {"type": "token", "text": f"[需要授权: {read_req.get('token_description')}]"}
        )
        yield _sse_event_line(
            {
                "type": "requires_token",
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
            }
        )
        return
    if ok_read and _message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True
    intr = planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = runtime_context_after_workflow_interrupt(runtime_context)
        yield _sse_event_line({"type": "token", "text": intr})
        payload = _xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
        payload = attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=cleared,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        yield _sse_event_line(
            {
                "type": "done",
                "result": payload,
            }
        )
        return
    vector_error = _ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        yield _sse_event_line({"type": "error", "message": vector_error})
        return
    workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
    llm_client = create_modstore_openai_client_from_request(request)
    reply_parts: list[str] = []
    try:
        halted_for_write_token = False
        for ev in _xcagi_guarded_planner_stream_events(
            body,
            runtime_context=runtime_context,
            workspace_root=workspace_root,
            client=llm_client,
        ):
            et = ev.get("type")
            if et == "error":
                yield _sse_event_line(ev)
                return
            if et == "token":
                text = str(ev.get("text") or "")
                if not ev.get("ephemeral"):
                    reply_parts.append(text)
                yield _sse_event_line(ev)
            elif et == "requires_token":
                yield _sse_event_line(ev)
                halted_for_write_token = True
                break
            elif et == "done":
                continue
            else:
                yield _sse_event_line(ev)
        if halted_for_write_token:
            return
        merged = "".join(reply_parts)
        if not merged.strip():
            msg = (
                "模型服务已完成请求，但没有返回可显示的正文。"
                "若附带图片，请确认当前账号已启用视觉模型，或上传文字更清晰的截图。"
            )
            yield _sse_event_line({"type": "error", "message": msg})
            return
        thinking = _thinking_steps_from_planner_stream_text(merged)
        if thinking:
            done_reply: str | dict = {"response": merged, "thinking_steps": thinking}
        else:
            done_reply = merged
        payload = _xcagi_compat_reply_payload(done_reply)
        payload = attach_chat_trace_run(
            payload,
            message=body.message,
            runtime_context=runtime_context,
            user_id=body.user_id,
            source=body.source,
            channel="compat_chat_stream",
        )
        yield _sse_event_line({"type": "done", "result": payload})
    except RECOVERABLE_ERRORS as e:
        exc = _xcagi_chat_http_exc(e)
        yield _sse_event_line(_xcagi_chat_error_event(exc))


sync_module_functions(
    target=globals(),
    source_module="app.fastapi_routes.domains.conversation.helpers",
    function_names=(
        "_xcagi_planner_stream_bytes_async",
        "_xcagi_planner_stream_bytes",
    ),
)
