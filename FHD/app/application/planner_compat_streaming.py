"""Extracted helpers for an existing public module."""

from __future__ import annotations

import json

from app.utils.mixin_module_sync import sync_module_functions


def _stream_sse_event_line(payload: dict[str, Any]) -> bytes:
    encoder = globals().get("_sse_event_line")
    if callable(encoder):
        encoded = encoder(payload)
        if isinstance(encoded, bytes):
            return encoded
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


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
            build_shipment_records_query_response_dict,
            route_normal_mode_message,
        )

        route = route_normal_mode_message(message)
        intent = route.get("intent")
        if intent == "shipment_records_query":
            return build_shipment_records_query_response_dict(route)
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


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    """Stream a chat response with the authenticated tenant kept in scope.

    Most ordinary request handlers can recover their tenant through the
    request ContextVar.  A ``StreamingResponse`` runs this generator after
    middleware has unwound, however, so owner-scoped ETL preview reads would
    otherwise fail closed and render a shipment card without its proven
    model/price/layout.  This scope is server-derived and read-only for the
    preview path; it does not trust a client-supplied tenant or session id.
    """

    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(_authenticated_tenant_id(request)):
        async for chunk in _compat_chat_stream_with_tenant_scope(
            request,
            body,
            ai_tier=ai_tier,
        ):
            yield chunk


async def _compat_chat_stream_with_tenant_scope(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    # Yield before any parser, preview-store read, persona lookup, or model
    # transport work.  A delivery-order request is normally handled locally,
    # but its owner-scoped ETL evidence still requires a database read.  This
    # protocol-level progress frame prevents a slow local dependency from
    # being misreported by the desktop as a model "first packet" timeout.
    yield _stream_sse_event_line(
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
        yield _stream_sse_event_line({"type": "token", "text": response_text})
        yield _stream_sse_event_line({"type": "done", "result": shipment_preview})
        return

    # Read-only customer/product slots do not need an LLM.  This avoids a
    # provider 429/quota failure for simple business lookups while preserving
    # the existing confirmation-only shipment and print paths above.
    business_query = _stream_read_only_business_query_payload(body.message)
    if business_query is not None:
        response_text = str(business_query.get("response") or business_query.get("message") or "")
        yield _stream_sse_event_line({"type": "token", "text": response_text})
        yield _stream_sse_event_line({"type": "done", "result": business_query})
        return

    # The first progress event above guarantees a prompt first packet.  This
    # second phase tells the user where the remaining wait is happening; it
    # does not create a synthetic answer or hide a provider error.
    yield _stream_sse_event_line(
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


sync_module_functions(
    target=globals(),
    source_module="app.application.planner_compat_service",
    function_names=(
        "_stream_shipment_preview_payload",
        "_stream_read_only_business_query_payload",
        "compat_chat_stream_async",
        "_compat_chat_stream_with_tenant_scope",
    ),
)
