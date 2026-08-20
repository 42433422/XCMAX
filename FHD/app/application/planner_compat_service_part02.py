# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.planner_compat_execute")._facade()


def _summarize_context_for_log(
    value: _facade().Any, *, key: str = "", depth: int = 0
) -> _facade().Any:
    """Build a bounded, binary-safe representation of planner context for logs."""
    if depth >= 5:
        return "<nested-context>"
    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"
    if isinstance(value, str):
        normalized_key = key.lower().replace("-", "_")
        if value.startswith("data:"):
            header, separator, payload = value.partition(",")
            safe_header = header[:96]
            payload_length = len(payload) if separator else 0
            return f"<{safe_header} payload_chars={payload_length}>"
        if normalized_key in _facade()._BINARY_CONTEXT_KEYS:
            return f"<redacted-binary chars={len(value)}>"
        if len(value) > 320:
            return f"{value[:160]}… <text_chars={len(value)}>"
        return value
    if isinstance(value, dict):
        items = list(value.items())
        summarized = {
            str(item_key): _summarize_context_for_log(
                item_value, key=str(item_key), depth=depth + 1
            )
            for item_key, item_value in items[:32]
        }
        if len(items) > 32:
            summarized["<omitted_keys>"] = len(items) - 32
        return summarized
    if isinstance(value, (list, tuple)):
        summarized_items = [
            _summarize_context_for_log(item, key=key, depth=depth + 1) for item in value[:12]
        ]
        if len(value) > 12:
            summarized_items.append(f"<omitted_items={len(value) - 12}>")
        return summarized_items
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _derive_industry_from_session(request: _facade().Request) -> str:
    """单一真相源 + 自动派生：从 session account_kind + User.industry_id 派生 industry。

    1. admin 账号 → "管理端"（运维助手身份）
    2. 普通账号 → User.industry_id（涂料/考勤/批发/电商/餐饮/物流等）
    3. 兜底 → "通用"（业务管家身份）

    前端/手机端无需传 industry，后端自动判断。
    """
    state_raw = getattr(getattr(request, "state", None), "industry_id", "")
    state_industry = state_raw.strip() if isinstance(state_raw, str) else ""
    if state_industry == "管理端":
        return "管理端"
    try:
        from app.application.session_account_meta import load_session_account_meta

        meta: dict[str, _facade().Any] = {}
        for sid in _facade()._request_session_candidates(request):
            candidate_meta = load_session_account_meta(sid) or {}
            if candidate_meta:
                meta = candidate_meta
                break
        if meta.get("account_kind") == "admin":
            return "管理端"
        if state_industry and state_industry != "通用":
            return state_industry
        owner_id = ""
        tenant_id = meta.get("tenant_id")
        local_user_id = meta.get("local_user_id")
        if tenant_id is not None and str(tenant_id).strip().isdigit():
            owner_id = f"tenant:{int(tenant_id)}"
        elif local_user_id is not None and str(local_user_id).strip().isdigit():
            owner_id = f"session:{int(local_user_id)}"
        if owner_id:
            from app.application.tenant_workspace_prefs import get_workspace_prefs

            prefs = get_workspace_prefs(owner_id)
            selected = str(prefs.get("selected_industry_id") or "").strip()
            if selected:
                return selected
        local_user_id = meta.get("local_user_id")
        if local_user_id:
            from app.db.models.user import User
            from app.db.session import get_db

            with get_db() as db:
                row = db.query(User.industry_id).filter(User.id == local_user_id).first()
                if row and row[0]:
                    return str(row[0]).strip()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("derive_industry_from_session failed", exc_info=True)
    return state_industry or "通用"


def _attach_compat_chat_trace(
    payload: dict[str, _facade().Any],
    body: _facade().XcagiCompatChatBody | _facade().XcagiCompatChatBatchBody,
    *,
    message: str,
    runtime_context: dict[str, _facade().Any] | None,
    channel: str,
) -> dict[str, _facade().Any]:
    return _facade().attach_chat_trace_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=getattr(body, "user_id", None),
        source=getattr(body, "source", None),
        channel=channel,
    )


def _legacy_requires_token_payload(parsed: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    raw_records = parsed.get("legacy_tool_records")
    legacy_tool_records = raw_records if isinstance(raw_records, list) else []
    data_payload = {
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
    }
    if legacy_tool_records:
        data_payload["legacy_tool_records"] = legacy_tool_records
    return {
        "success": True,
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
        "message": parsed.get("message"),
        "response": parsed.get("message"),
        "data": data_payload,
    }


def _reply_has_legacy_tool_records(reply: _facade().Any) -> bool:
    return isinstance(reply, dict) and isinstance(
        reply.get("legacy_tool_records") or reply.get("_tool_records"), list
    )


def _clear_legacy_tool_result_if_reply_has_no_records(reply: _facade().Any) -> None:
    if _facade()._reply_has_legacy_tool_records(reply):
        return
    try:
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result

        clear_last_tool_result()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("legacy planner local tool trace clear skipped", exc_info=True)


def _env_truthy(name: str) -> bool:
    return str(_facade().os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


async def _await_with_timeout(awaitable, *, timeout: float):
    """Await with timeout without leaking a coroutine when ``wait_for`` fails early.

    Besides normal timeouts, tests and fault-injection layers may raise before
    ``asyncio.wait_for`` has awaited its argument.  Scheduling first and then
    cancelling/consuming the task guarantees there is no orphaned
    ``asyncio.to_thread`` coroutine or background execution.
    """
    task = _facade().asyncio.ensure_future(awaitable)
    try:
        return await _facade().asyncio.wait_for(task, timeout=timeout)
    except _facade().BOUNDARY_ERRORS + (_facade().asyncio.CancelledError,):
        if not task.done():
            task.cancel()
        try:
            await task
        except _facade().BOUNDARY_ERRORS + (_facade().asyncio.CancelledError,):
            pass
        raise


def _use_ai_chat_mainline(runtime_context: dict[str, _facade().Any] | None) -> bool:
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    if ctx.get("use_legacy_chat_adapter") is True:
        return False
    if ctx.get("use_ai_chat_mainline") is True:
        return True
    if _facade()._env_truthy("XCAGI_USE_LEGACY_CHAT_ADAPTER"):
        return False
    if _facade().os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _legacy_chat_fallback_allowed(runtime_context: dict[str, _facade().Any] | None) -> bool:
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    if ctx.get("allow_legacy_chat_adapter") is True:
        return True
    if _facade()._env_truthy("XCAGI_ALLOW_LEGACY_CHAT_FALLBACK"):
        return True
    return bool(_facade().os.environ.get("PYTEST_CURRENT_TEST"))


def _merge_kitten_attachments(
    payload: dict[str, _facade().Any], kitten_extra: dict[str, _facade().Any] | None
) -> dict[str, _facade().Any]:
    if not kitten_extra:
        return payload
    enriched = dict(payload)
    data = enriched.get("data") if isinstance(enriched.get("data"), dict) else {}
    data = dict(data or {})
    for key, value in kitten_extra.items():
        if value is not None:
            data[key] = value
    enriched["data"] = data
    return enriched


async def _execute_ai_chat_mainline(
    body: _facade().XcagiCompatChatBody | _facade().XcagiCompatChatBatchBody,
    runtime_context: dict[str, _facade().Any],
    *,
    message: str | None = None,
    kitten_extra: dict[str, _facade().Any] | None = None,
) -> dict[str, _facade().Any]:
    from app.application import get_ai_chat_app_service

    service = get_ai_chat_app_service()
    file_context = runtime_context.get("file_context")
    if not isinstance(file_context, dict):
        file_context = runtime_context.get("file_analysis")
    if not isinstance(file_context, dict):
        file_context = {}
    message_text = str(message if message is not None else getattr(body, "message", "") or "")
    payload = await _facade().asyncio.to_thread(
        service.process_chat,
        user_id=str(getattr(body, "user_id", None) or "default"),
        message=message_text,
        context=dict(runtime_context or {}),
        source=getattr(body, "source", None),
        file_context=file_context,
    )
    if not isinstance(payload, dict):
        payload = _facade()._xcagi_compat_reply_payload(str(payload))
    return _facade()._merge_kitten_attachments(payload, kitten_extra)


async def execute_compat_chat(
    request: _facade().Request, body: _facade().XcagiCompatChatBody
) -> dict[str, _facade().Any]:
    token = _facade().set_facade_globals(globals())
    try:
        return await _facade()._execute_compat_chat_impl(request, body)
    finally:
        _facade().reset_facade_globals(token)


async def execute_compat_chat_batch(
    request: _facade().Request, body: _facade().XcagiCompatChatBatchBody
) -> dict[str, _facade().Any]:
    token = _facade().set_facade_globals(globals())
    try:
        return await _facade()._execute_compat_chat_batch_impl(request, body)
    finally:
        _facade().reset_facade_globals(token)


def _recent_history(svc, user_id: str) -> list[dict]:
    """从对话服务里尽力读取该用户最近历史（供 persona L2/L3 周期推断使用）。

    取不到则返回空列表（容错，绝不因此中断流式响应）。
    """
    try:
        contexts = getattr(svc, "contexts", None)
        if not contexts:
            return []
        ctx = contexts.get(user_id)
        hist = getattr(ctx, "conversation_history", None) if ctx else None
        return list(hist) if hist else []
    except _facade().RECOVERABLE_ERRORS:
        return []


def _resolve_chat_user_id(request: _facade().Request, body: _facade().XcagiCompatChatBody) -> str:
    """统一对话流 user_id 口径，与 butler 路由 (_resolve_persona_user_id) 对齐：
    优先 body.user_id，其次 X-User-Id 头，最后默认 '1'，
    使 Settings UI 用同一会话作用域 id（``web_normal_<session>``）读到对话写入的画像。
    """
    uid = getattr(body, "user_id", None)
    if uid:
        return str(uid)
    try:
        hdr = request.headers.get("X-User-Id") or request.headers.get("X-User-ID")
        if hdr and str(hdr).strip():
            return str(hdr).strip()
    except _facade().RECOVERABLE_ERRORS:
        pass
    return "1"
