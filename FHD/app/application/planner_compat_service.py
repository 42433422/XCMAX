"""Planner 兼容对话服务（3d）：供宿主 /api/ai/* 与 Mod facade 共用。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import HTTPException, Request

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run,
    finalize_legacy_chat_run,
    start_legacy_chat_run,
)
from app.domain.ai.tier import (
    assert_p2_elevated_claim_or_raise,
    resolve_ai_tier,
    runtime_context_with_tier,
)
from app.domain.context.session_context import (
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _sse_event_line,
    _xcagi_chat_error_event,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_planner_stream_bytes_async,
)
from app.infrastructure.llm.client import set_mode as set_llm_mode
from app.legacy.chat.legacy_chat_adapter import chat as run_agent_chat
from app.services.conversation.modstore_adapter import create_modstore_openai_client_from_request
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _authenticated_owner_user_id(request: Request) -> int | None:
    """Read the authenticated owner only from server request state.

    ``body.user_id`` is a chat/session identifier and may be client supplied;
    it must never select a private ETL preview.
    """

    try:
        value = getattr(request.state, "user_id", None)
        owner = int(value)
    except (AttributeError, TypeError, ValueError):
        return None
    return owner if owner > 0 else None


def _stream_shipment_preview_payload(
    message: str,
    *,
    authenticated_owner_user_id: int | None = None,
) -> dict[str, Any] | None:
    """Return the deterministic *preview* for an order-like chat message.

    The regular stream path used to jump straight to the legacy LLM planner.
    That meant the same ``打印客户发货单…`` request which the non-streaming
    normal/pro paths recognise locally could wait for a model first token (and
    fail before a confirmation card was ever shown).  Keep this deliberately
    narrow and side-effect free: it only creates a preview task.  The existing
    confirmation flow still owns the later tool execution and the separate
    print authorisation remains required.
    """

    try:
        from app.application.normal_chat_dispatch import (
            route_normal_mode_message,
            run_normal_slot_shipment_preview,
        )

        route = route_normal_mode_message(message)
        if route.get("intent") != "shipment":
            return None
        payload = run_normal_slot_shipment_preview(
            message,
            authenticated_owner_user_id=authenticated_owner_user_id,
        )
        return payload if isinstance(payload, dict) else None
    except RECOVERABLE_ERRORS:
        # A deterministic convenience path must never hide the normal,
        # receipt-enforced planner error path when a local read dependency is
        # temporarily unavailable.
        logger.debug("stream shipment preview fast path skipped", exc_info=True)
        return None


def _stream_read_only_business_query_payload(message: str) -> dict[str, Any] | None:
    """Return a deterministic answer for narrow, read-only business queries.

    Customer and product list requests are already represented by normal-chat
    slots and backed by local application services.  Serving those slots before
    the model makes them available when a configured provider is rate-limited
    or out of quota.  Keep the scope deliberately small: no import, document,
    print, or mutation intent is handled here.

    Raw database-read wording is intentionally excluded so this convenience
    path cannot weaken the existing DB-read-token policy.
    """

    try:
        # Do not infer intent from raw-database wording.  The complete
        # authorization path (including DB_READ_TOKEN) must remain in charge
        # of phrases such as “客户数据库 / 数据表 / schema / SQL”, even when the
        # message also contains a customer or product keyword.
        raw_db_markers = (
            "数据库",
            "数据表",
            "表结构",
            "schema",
            "sql",
            "raw",
            "原始",
            "全库",
            "整库",
            "数据库文件",
        )
        if any(marker in str(message or "").lower() for marker in raw_db_markers):
            return None
        if _message_requires_db_read_token(message):
            return None

        from app.application.normal_chat_dispatch import (
            build_customers_query_response_dict,
            build_product_query_response_dict,
            route_normal_mode_message,
        )

        route = route_normal_mode_message(message)
        intent = route.get("intent")
        if intent == "customers_query":
            return build_customers_query_response_dict(route)
        if intent == "product_query":
            return build_product_query_response_dict(route)
    except RECOVERABLE_ERRORS:
        # If a local read dependency is temporarily unavailable, return its
        # explicit, side-effect-free error payload when available rather than
        # pretending the model has a business receipt.  Unexpected programming
        # errors still reach the normal boundary.
        logger.debug("stream read-only business query fast path skipped", exc_info=True)
    return None


def _request_session_candidates(request: Request) -> list[str]:
    """Return possible *host* session ids without mistaking the market token for one.

    Desktop chat requests intentionally carry both the local ``session_id`` cookie
    and a 修茈市场 bearer token.  The generic compatibility extractor prefers the
    bearer value, which is correct for model proxying but is not a host session id.
    Industry/persona lookup must therefore try the explicit host session sources
    before that compatibility value.
    """

    candidates: list[str] = []

    def _append(raw: Any) -> None:
        value = raw.strip() if isinstance(raw, str) else ""
        if value and value not in candidates:
            candidates.append(value)

    headers = getattr(request, "headers", {}) or {}
    cookies = getattr(request, "cookies", {}) or {}
    try:
        _append(headers.get("X-Session-ID"))
    except (AttributeError, TypeError):
        pass

    cookie_name = (os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()
    try:
        _append(cookies.get(cookie_name))
    except (AttributeError, TypeError):
        pass

    # Keep the established extractor as a final fallback for mobile/legacy clients
    # that only send Authorization.  A market bearer simply fails the DB lookup and
    # the cookie candidate above remains authoritative.
    try:
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        _append(_session_id_from_request(request))
    except Exception:  # noqa: BLE001 - request identity derivation is best effort
        logger.debug("planner session candidate extraction failed", exc_info=True)
    return candidates


_BINARY_CONTEXT_KEYS = frozenset(
    {
        "base64",
        "data_url",
        "dataurl",
        "file_bytes",
        "image_base64",
        "image_data",
        "pdf_base64",
        "raw_bytes",
    }
)


def _summarize_context_for_log(value: Any, *, key: str = "", depth: int = 0) -> Any:
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
        if normalized_key in _BINARY_CONTEXT_KEYS:
            return f"<redacted-binary chars={len(value)}>"
        if len(value) > 320:
            return f"{value[:160]}… <text_chars={len(value)}>"
        return value
    if isinstance(value, dict):
        items = list(value.items())
        summarized = {
            str(item_key): _summarize_context_for_log(
                item_value,
                key=str(item_key),
                depth=depth + 1,
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


def _derive_industry_from_session(request: Request) -> str:
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

        meta: dict[str, Any] = {}
        for sid in _request_session_candidates(request):
            candidate_meta = load_session_account_meta(sid) or {}
            if candidate_meta:
                meta = candidate_meta
                break
        # 1. admin 账号 → 管理端
        if meta.get("account_kind") == "admin":
            return "管理端"
        # 2. 请求中间件已经从认证用户解析出行业时直接复用。
        if state_industry and state_industry != "通用":
            return state_industry
        # 3. 工作区选择是跨设备同步 SSOT；优先于可能尚未回写的 User.industry_id。
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
        # 4. 普通账号 → User.industry_id
        local_user_id = meta.get("local_user_id")
        if local_user_id:
            from app.db.models.user import User
            from app.db.session import get_db

            with get_db() as db:
                row = db.query(User.industry_id).filter(User.id == local_user_id).first()
                if row and row[0]:
                    return str(row[0]).strip()
    except Exception:  # noqa: BLE001  # best-effort 派生，失败回退到默认行业
        logger.debug("derive_industry_from_session failed", exc_info=True)
    return state_industry or "通用"


def _attach_compat_chat_trace(
    payload: dict[str, Any],
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    channel: str,
) -> dict[str, Any]:
    return attach_chat_trace_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=getattr(body, "user_id", None),
        source=getattr(body, "source", None),
        channel=channel,
    )


def _legacy_requires_token_payload(parsed: dict[str, Any]) -> dict[str, Any]:
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


def _reply_has_legacy_tool_records(reply: Any) -> bool:
    return isinstance(reply, dict) and isinstance(
        reply.get("legacy_tool_records") or reply.get("_tool_records"),
        list,
    )


def _clear_legacy_tool_result_if_reply_has_no_records(reply: Any) -> None:
    if _reply_has_legacy_tool_records(reply):
        return
    try:
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result

        clear_last_tool_result()
    except RECOVERABLE_ERRORS:
        logger.debug("legacy planner local tool trace clear skipped", exc_info=True)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


async def _await_with_timeout(awaitable, *, timeout: float):
    """Await with timeout without leaking a coroutine when ``wait_for`` fails early.

    Besides normal timeouts, tests and fault-injection layers may raise before
    ``asyncio.wait_for`` has awaited its argument.  Scheduling first and then
    cancelling/consuming the task guarantees there is no orphaned
    ``asyncio.to_thread`` coroutine or background execution.
    """

    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.wait_for(task, timeout=timeout)
    except (Exception, asyncio.CancelledError):
        if not task.done():
            task.cancel()
        try:
            await task
        except (Exception, asyncio.CancelledError):  # noqa: BLE001 - consume task before reraising original
            pass
        raise


def _use_ai_chat_mainline(runtime_context: dict[str, Any] | None) -> bool:
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    if ctx.get("use_legacy_chat_adapter") is True:
        return False
    if ctx.get("use_ai_chat_mainline") is True:
        return True
    if _env_truthy("XCAGI_USE_LEGACY_CHAT_ADAPTER"):
        return False
    # Many legacy unit tests patch run_agent_chat directly. Keep pytest on the
    # historical path unless a test opts in, while production defaults to the
    # unified AIChatApplicationService mainline.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _legacy_chat_fallback_allowed(runtime_context: dict[str, Any] | None) -> bool:
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    if ctx.get("allow_legacy_chat_adapter") is True:
        return True
    if _env_truthy("XCAGI_ALLOW_LEGACY_CHAT_FALLBACK"):
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _merge_kitten_attachments(
    payload: dict[str, Any], kitten_extra: dict[str, Any] | None
) -> dict[str, Any]:
    if not kitten_extra:
        return payload
    enriched = dict(payload)
    data = enriched.get("data") if isinstance(enriched.get("data"), dict) else {}
    data = dict(data)
    for key, value in kitten_extra.items():
        if value is not None:
            data[key] = value
    enriched["data"] = data
    return enriched


async def _execute_ai_chat_mainline(
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
    runtime_context: dict[str, Any],
    *,
    message: str | None = None,
    kitten_extra: dict[str, Any] | None = None,
    authenticated_owner_user_id: int | None = None,
) -> dict[str, Any]:
    from app.application.ai_chat_app_service import AIChatApplicationService

    service = AIChatApplicationService()
    file_context = runtime_context.get("file_context")
    if not isinstance(file_context, dict):
        file_context = runtime_context.get("file_analysis")
    if not isinstance(file_context, dict):
        file_context = {}
    message_text = str(message if message is not None else getattr(body, "message", "") or "")

    payload = await asyncio.to_thread(
        service.process_chat,
        user_id=str(getattr(body, "user_id", None) or "default"),
        message=message_text,
        context=dict(runtime_context or {}),
        source=getattr(body, "source", None),
        file_context=file_context,
        authenticated_owner_user_id=authenticated_owner_user_id,
    )
    if not isinstance(payload, dict):
        payload = _xcagi_compat_reply_payload(str(payload))
    return _merge_kitten_attachments(payload, kitten_extra)


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> dict[str, Any]:
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)

    runtime_context, _ = _merge_runtime_context_with_message_paths(body.context, body.message)
    assert_p2_elevated_claim_or_raise(request)
    tier = resolve_ai_tier(request)
    runtime_context = runtime_context_with_tier(runtime_context, tier)
    # Business facts and side effects must be backed by a deterministic tool
    # receipt.  Guard before either the new app service or legacy planner so
    # deployment flags cannot reopen an LLM-only success path.
    from app.application.chat_business_safety import try_handle_business_chat_action

    business_payload = try_handle_business_chat_action(
        body.message,
        runtime_context=runtime_context,
        user_id=getattr(body, "user_id", None),
        request=request,
    )
    if business_payload is not None:
        return business_payload
    try:
        from app.application.kitten_planner_context import (
            enrich_kitten_analyzer_runtime,
            kitten_reply_attachments,
        )

        runtime_context = await enrich_kitten_analyzer_runtime(runtime_context, body.message)
        kitten_extra = kitten_reply_attachments(runtime_context)
    except RECOVERABLE_ERRORS:
        logger.debug("kitten planner context enrich skipped", exc_info=True)
        kitten_extra = {}
    ok_read, read_req = _ensure_chat_db_read_authorized(
        request,
        message=body.message,
        provided_token=body.db_read_token,
    )
    if not ok_read and read_req:
        payload = {
            "success": True,
            "requires_token": True,
            "token_name": read_req.get("token_name"),
            "token_description": read_req.get("token_description"),
            "message": read_req.get("message"),
            "response": read_req.get("message"),
            "data": {
                "requires_token": True,
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
            },
        }
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=runtime_context,
            channel="compat_chat",
        )
    if ok_read and _message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True
    intr = planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = runtime_context_after_workflow_interrupt(runtime_context)
        payload = _xcagi_compat_reply_payload(
            intr, runtime_context_update=cleared, kitten_attachments=kitten_extra or None
        )
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=cleared,
            channel="compat_chat",
        )

    vector_error = _ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        payload = _xcagi_compat_reply_payload(vector_error, kitten_attachments=kitten_extra or None)
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=runtime_context,
            channel="compat_chat",
        )

    timeout = _xcagi_chat_timeout_seconds()
    pre_run = None
    planner_runtime_context = dict(runtime_context or {})
    if body.system_prompt:
        planner_runtime_context["system_prompt"] = body.system_prompt
    if body.db_write_token:
        planner_runtime_context["db_write_token_present"] = True
    if _use_ai_chat_mainline(planner_runtime_context):
        try:
            payload = await _await_with_timeout(
                _execute_ai_chat_mainline(
                    body,
                    planner_runtime_context,
                    kitten_extra=kitten_extra or None,
                    authenticated_owner_user_id=_authenticated_owner_user_id(request),
                ),
                timeout=timeout,
            )
            if payload.get("run_id") or payload.get("agent_run_id"):
                return payload
            return _attach_compat_chat_trace(
                payload,
                body,
                message=body.message,
                runtime_context=planner_runtime_context,
                channel="compat_chat_mainline",
            )
        except TimeoutError:
            payload = _xcagi_chat_timeout_error_payload(timeout)
            return _attach_compat_chat_trace(
                payload,
                body,
                message=body.message,
                runtime_context=planner_runtime_context,
                channel="compat_chat_mainline",
            )
        except RECOVERABLE_ERRORS as e:
            if not _legacy_chat_fallback_allowed(planner_runtime_context):
                raise _xcagi_chat_http_exc(e) from e
            logger.warning(
                "AIChatApplicationService mainline failed; legacy fallback explicitly allowed: %s",
                e,
                exc_info=True,
            )
    try:
        workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
        llm_client = create_modstore_openai_client_from_request(request)
        try:
            pre_run = start_legacy_chat_run(
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
            planner_runtime_context["run_id"] = pre_run.run_id
            planner_runtime_context["agent_run_id"] = pre_run.run_id
        except RECOVERABLE_ERRORS:
            logger.debug("legacy planner AgentRun pre-create skipped", exc_info=True)
        reply = await _await_with_timeout(
            asyncio.to_thread(
                run_agent_chat,
                body.message,
                runtime_context=planner_runtime_context or None,
                system_prompt=body.system_prompt,
                workspace_root=workspace_root,
                db_write_token=body.db_write_token,
                client=llm_client,
            ),
            timeout=timeout,
        )
        try:
            parsed = reply if isinstance(reply, dict) else None
            if parsed is None and isinstance(reply, str):
                parsed = json.loads(reply)
            if isinstance(parsed, dict) and parsed.get("requires_token"):
                payload = _legacy_requires_token_payload(parsed)
                if pre_run is not None:
                    return finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=body.message,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat",
                    )
                return _attach_compat_chat_trace(
                    payload,
                    body,
                    message=body.message,
                    runtime_context=planner_runtime_context,
                    channel="compat_chat",
                )
        except json.JSONDecodeError:
            pass
        _clear_legacy_tool_result_if_reply_has_no_records(reply)
    except TimeoutError:
        payload = _xcagi_chat_timeout_error_payload(timeout)
        if pre_run is not None:
            return finalize_legacy_chat_run(
                pre_run.run_id,
                payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=planner_runtime_context,
            channel="compat_chat",
        )
    except RECOVERABLE_ERRORS as e:
        if pre_run is not None:
            err_payload = {
                "success": False,
                "message": str(e),
                "response": str(e),
                "data": {"error": str(e)},
            }
            finalize_legacy_chat_run(
                pre_run.run_id,
                err_payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
        raise _xcagi_chat_http_exc(e) from e
    payload = _xcagi_compat_reply_payload(reply, kitten_attachments=kitten_extra or None)
    if pre_run is not None:
        return finalize_legacy_chat_run(
            pre_run.run_id,
            payload,
            message=body.message,
            runtime_context=planner_runtime_context,
            user_id=getattr(body, "user_id", None),
            source=getattr(body, "source", None),
            channel="compat_chat",
        )
    return _attach_compat_chat_trace(
        payload,
        body,
        message=body.message,
        runtime_context=planner_runtime_context,
        channel="compat_chat",
    )


async def execute_compat_chat_batch(
    request: Request, body: XcagiCompatChatBatchBody
) -> dict[str, Any]:
    msgs = [str(x).strip() for x in (body.messages or []) if str(x).strip()]
    if not msgs:
        raise HTTPException(status_code=400, detail="messages 须为非空字符串数组")
    assert_p2_elevated_claim_or_raise(request)
    batch_tier = resolve_ai_tier(request)
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)
    results: list[dict[str, Any]] = []
    timeout = _xcagi_chat_timeout_seconds()
    rolling_ctx = body.context
    llm_client = create_modstore_openai_client_from_request(request)
    for txt in msgs:
        runtime_context, _ = _merge_runtime_context_with_message_paths(rolling_ctx, txt)
        runtime_context = runtime_context_with_tier(runtime_context, batch_tier)
        from app.application.chat_business_safety import try_handle_business_chat_action

        business_payload = try_handle_business_chat_action(
            txt,
            runtime_context=runtime_context,
            user_id=getattr(body, "user_id", None),
            request=request,
        )
        if business_payload is not None:
            results.append(business_payload)
            continue
        ok_read, read_req = _ensure_chat_db_read_authorized(
            request,
            message=txt,
            provided_token=body.db_read_token,
        )
        if not ok_read and read_req:
            payload = {
                "success": True,
                "requires_token": True,
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
                "message": read_req.get("message"),
                "response": read_req.get("message"),
                "data": {
                    "requires_token": True,
                    "token_name": read_req.get("token_name"),
                    "token_description": read_req.get("token_description"),
                },
            }
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=runtime_context,
                    channel="compat_chat_batch",
                )
            )
            continue
        if ok_read and _message_requires_db_read_token(txt):
            runtime_context["chat_db_read_authorized"] = True
        intr = planner_workflow_interrupt_reply(txt)
        if intr is not None:
            cleared = runtime_context_after_workflow_interrupt(runtime_context)
            rolling_ctx = cleared
            payload = _xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=cleared,
                    channel="compat_chat_batch",
                )
            )
            continue
        vector_error = _ensure_vector_index_if_needed(txt, runtime_context)
        if vector_error:
            payload = _xcagi_compat_reply_payload(vector_error)
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=runtime_context,
                    channel="compat_chat_batch",
                )
            )
            continue
        pre_run = None
        planner_runtime_context = dict(runtime_context or {})
        if body.system_prompt:
            planner_runtime_context["system_prompt"] = body.system_prompt
        if body.db_write_token:
            planner_runtime_context["db_write_token_present"] = True
        if _use_ai_chat_mainline(planner_runtime_context):
            try:
                payload = await _await_with_timeout(
                    _execute_ai_chat_mainline(
                        body,
                        planner_runtime_context,
                        message=txt,
                    ),
                    timeout=timeout,
                )
                results.append(
                    payload
                    if payload.get("run_id") or payload.get("agent_run_id")
                    else _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch_mainline",
                    )
                )
                continue
            except TimeoutError:
                payload = _xcagi_chat_timeout_error_payload(timeout)
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch_mainline",
                    )
                )
                continue
            except RECOVERABLE_ERRORS as e:
                if not _legacy_chat_fallback_allowed(planner_runtime_context):
                    err = _xcagi_chat_http_exc(e)
                    error_event = _xcagi_chat_error_event(err)
                    error_message = str(error_event["message"])
                    results.append(
                        {
                            "success": False,
                            "message": error_message,
                            "response": error_message,
                            "error_code": error_event.get("error_code"),
                            "data": {
                                "error": error_message,
                                "status_code": err.status_code,
                                "error_code": error_event.get("error_code"),
                            },
                        }
                    )
                    continue
                logger.warning(
                    "AIChatApplicationService batch mainline failed; legacy fallback explicitly allowed: %s",
                    e,
                    exc_info=True,
                )
        try:
            try:
                pre_run = start_legacy_chat_run(
                    message=txt,
                    runtime_context=planner_runtime_context,
                    user_id=getattr(body, "user_id", None),
                    source=getattr(body, "source", None),
                    channel="compat_chat_batch",
                )
                planner_runtime_context["run_id"] = pre_run.run_id
                planner_runtime_context["agent_run_id"] = pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("legacy batch planner AgentRun pre-create skipped", exc_info=True)
            workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
            reply = await _await_with_timeout(
                asyncio.to_thread(
                    run_agent_chat,
                    txt,
                    runtime_context=planner_runtime_context or None,
                    system_prompt=body.system_prompt,
                    workspace_root=workspace_root,
                    db_write_token=body.db_write_token,
                    client=llm_client,
                ),
                timeout=timeout,
            )
            try:
                parsed = reply if isinstance(reply, dict) else None
                if parsed is None and isinstance(reply, str):
                    parsed = json.loads(reply)
                if isinstance(parsed, dict) and parsed.get("requires_token"):
                    payload = _legacy_requires_token_payload(parsed)
                    if pre_run is not None:
                        results.append(
                            finalize_legacy_chat_run(
                                pre_run.run_id,
                                payload,
                                message=txt,
                                runtime_context=planner_runtime_context,
                                user_id=getattr(body, "user_id", None),
                                source=getattr(body, "source", None),
                                channel="compat_chat_batch",
                            )
                        )
                    else:
                        results.append(
                            _attach_compat_chat_trace(
                                payload,
                                body,
                                message=txt,
                                runtime_context=planner_runtime_context,
                                channel="compat_chat_batch",
                            )
                        )
                    continue
            except json.JSONDecodeError:
                pass
            _clear_legacy_tool_result_if_reply_has_no_records(reply)
            payload = _xcagi_compat_reply_payload(reply)
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
        except TimeoutError:
            payload = _xcagi_chat_timeout_error_payload(timeout)
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
        except RECOVERABLE_ERRORS as e:
            err = _xcagi_chat_http_exc(e)
            error_event = _xcagi_chat_error_event(err)
            payload = {
                "success": False,
                "message": str(error_event["message"]),
                "error_code": error_event.get("error_code"),
                "data": {
                    "status_code": err.status_code,
                    "error_code": error_event.get("error_code"),
                },
            }
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
    ok = all(r.get("success") for r in results)
    return {"success": ok, "batch": True, "results": results, "count": len(results)}


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
    except Exception:  # noqa: BLE001
        return []


def _resolve_chat_user_id(request: Request, body: XcagiCompatChatBody) -> str:
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
    except Exception:  # noqa: BLE001
        pass
    return "1"


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    # Yield before any parser, preview-store read, persona lookup, or model
    # transport work.  A delivery-order request is normally handled locally,
    # but its owner-scoped ETL evidence still requires a database read.  This
    # protocol-level progress frame prevents a slow local dependency from
    # being misreported by the desktop as a model "first packet" timeout.
    yield _sse_event_line(
        {
            "type": "tool_progress",
            "label": "正在识别需求",
            "phase": "intent_recognition",
        }
    )

    # Shipping / order phrases are deliberately handled before persona and
    # model work for both normal and pro callers.  This only renders the
    # confirmation task; it does not execute a tool, write a record, or submit
    # a print job.  Keeping it at the common stream entry makes the UI's
    # default `/api/ai/chat/stream` route behave like the non-streaming path.
    shipment_preview = _stream_shipment_preview_payload(
        body.message,
        authenticated_owner_user_id=_authenticated_owner_user_id(request),
    )
    if shipment_preview is not None:
        response_text = str(
            shipment_preview.get("response") or shipment_preview.get("message") or ""
        )
        yield _sse_event_line({"type": "token", "text": response_text})
        yield _sse_event_line({"type": "done", "result": shipment_preview})
        return

    # Read-only customer/product slots do not need an LLM.  This avoids a
    # provider 429/quota failure for simple business lookups while preserving
    # the existing confirmation-only shipment and print paths above.
    business_query = _stream_read_only_business_query_payload(body.message)
    if business_query is not None:
        response_text = str(business_query.get("response") or business_query.get("message") or "")
        yield _sse_event_line({"type": "token", "text": response_text})
        yield _sse_event_line({"type": "done", "result": business_query})
        return

    # The first progress event above guarantees a prompt first packet.  This
    # second phase tells the user where the remaining wait is happening; it
    # does not create a synthetic answer or hide a provider error.
    yield _sse_event_line(
        {
            "type": "tool_progress",
            "label": "正在连接模型服务",
            "phase": "model_connect",
        }
    )

    # 注入 persona system_prompt（前端没传时用 persona 系统生成去客服腔 prompt）
    if not body.system_prompt and body.message:
        try:
            from app.services.conversation.manager import get_ai_conversation_service

            svc = get_ai_conversation_service()
            persona_svc = getattr(svc, "persona_service", None)
            logger.info(
                "persona_inject check: has_persona=%s msg=%s",
                persona_svc is not None,
                body.message[:50],
            )
            if persona_svc is not None:
                user_id = _resolve_chat_user_id(request, body)
                ctx = body.context or {}
                # 单一真相源 + 自动派生：优先用前端传的 industry；
                # 没传则从 session account_kind 派生（admin → 管理端，其他 → 通用）
                industry = ctx.get("industry") if isinstance(ctx, dict) else None
                if not industry:
                    industry = _derive_industry_from_session(request)
                history = _recent_history(svc, user_id)
                logger.info(
                    "persona_inject ctx=%s industry=%s history_len=%d",
                    _summarize_context_for_log(ctx),
                    industry,
                    len(history),
                )
                prompt, _params = await persona_svc.build_prompt_from_message(
                    user_id=user_id,
                    message=body.message,
                    history=history,
                    industry=industry,
                    context_prompt="",
                )
                body.system_prompt = prompt
                logger.info("persona_inject OK: prompt_len=%d", len(prompt))
        except Exception as e:  # noqa: BLE001  # persona 注入为尽力而为，失败不应中断流式响应
            logger.warning("persona_inject FAIL: %s", e, exc_info=True)

    tier = ai_tier or resolve_ai_tier(request)
    async for chunk in _xcagi_planner_stream_bytes_async(request, body, ai_tier=tier):
        yield chunk
