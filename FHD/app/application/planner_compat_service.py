"""Planner chat API with request-scoped, explicitly bound components."""

from __future__ import annotations

import asyncio as asyncio
import json as json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from fastapi import HTTPException as HTTPException
from fastapi import Request

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run,
    finalize_legacy_chat_run,
    start_legacy_chat_run,
)
from app.application.planner_compat.admission import ChatAdmission
from app.application.planner_compat.application import CompatChatApplication, FastPaths
from app.application.planner_compat.persona import (
    BINARY_CONTEXT_KEYS,
    ConversationService,
    IndustryResolver,
    PersonaEnricher,
    request_session_candidates,
    summarize_context_for_log,
)
from app.application.planner_compat.persona import recent_history as _recent_history
from app.application.planner_compat.persona import resolve_chat_user_id as _resolve_chat_user_id
from app.application.planner_compat.protocols import (
    ChatBackends,
    ChatBody,
    ChatResponses,
    ChatTrace,
    Context,
    Payload,
)
from app.application.planner_compat.runtime import (
    allow_legacy_fallback,
    execute_mainline,
    use_mainline,
)
from app.application.planner_compat.runtime import await_with_timeout as _await_with_timeout
from app.application.planner_compat.runtime import env_truthy as _env_truthy
from app.application.planner_compat.runtime import (
    legacy_requires_token_payload as _legacy_requires_token_payload,
)
from app.application.planner_compat.runtime import (
    merge_kitten_attachments as _merge_kitten_attachments,
)
from app.application.planner_compat.runtime import (
    reply_has_legacy_tool_records as _reply_has_legacy_tool_records,
)
from app.application.planner_compat.streaming import CompatStream
from app.application.planner_compat_execute import ChatTurnExecutor
from app.domain.ai.tier import (
    assert_p2_elevated_claim_or_raise,
    resolve_ai_tier,
    runtime_context_with_tier,
)
from app.domain.context.session_context import (
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)
from app.domain.shared_services.conversation.modstore_adapter import (
    create_modstore_openai_client_from_request,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _runtime_context_with_authenticated_actor,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_planner_stream_bytes_async,
)
from app.infrastructure.llm.client import llm_client_factory_scope
from app.infrastructure.llm.client import set_mode as set_llm_mode
from app.legacy.chat.legacy_chat_adapter import chat as run_agent_chat
from app.utils.operational_errors import BOUNDARY_ERRORS as BOUNDARY_ERRORS
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_BINARY_CONTEXT_KEYS = BINARY_CONTEXT_KEYS


def _compatibility_session(request: Request) -> str | None:
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    return _session_id_from_request(request)


def _request_session_candidates(request: Request) -> list[str]:
    return request_session_candidates(request, _compatibility_session, logger)


def _account_meta(session: str) -> Context:
    from app.application.session_account_meta import load_session_account_meta

    return load_session_account_meta(session) or {}


def _workspace_prefs(owner: str) -> Context:
    from app.application.tenant_workspace_prefs import get_workspace_prefs

    return get_workspace_prefs(owner)


def _user_industry(user: Any) -> str | None:
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        row = db.query(User.industry_id).filter(User.id == user).first()
        return str(row[0]).strip() if row and row[0] else None


def _derive_industry_from_session(request: Request) -> str:
    return IndustryResolver(
        _request_session_candidates, _account_meta, _workspace_prefs, _user_industry, logger
    ).resolve(request)


def _summarize_context_for_log(value: Any, *, key: str = "", depth: int = 0) -> Any:
    return summarize_context_for_log(value, key=key, depth=depth, binary_keys=_BINARY_CONTEXT_KEYS)


def _attach_compat_chat_trace(
    payload: Payload,
    body: ChatBody,
    *,
    message: str,
    runtime_context: Context | None,
    channel: str,
) -> Payload:
    return attach_chat_trace_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=body.user_id,
        source=body.source,
        channel=channel,
    )


def _clear_legacy_tool_result_if_reply_has_no_records(reply: Any) -> None:
    if _reply_has_legacy_tool_records(reply):
        return
    try:
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result

        clear_last_tool_result()
    except RECOVERABLE_ERRORS:
        logger.debug("legacy planner local tool trace clear skipped", exc_info=True)


def _use_ai_chat_mainline(runtime_context: Context | None) -> bool:
    return use_mainline(runtime_context, _env_truthy)


def _legacy_chat_fallback_allowed(runtime_context: Context | None) -> bool:
    return allow_legacy_fallback(runtime_context, _env_truthy)


async def _execute_ai_chat_mainline(
    body: ChatBody,
    runtime_context: Context,
    *,
    message: str | None = None,
    kitten_extra: Payload | None = None,
) -> Payload:
    from app.application import get_ai_chat_app_service

    return await execute_mainline(
        get_ai_chat_app_service(),
        body,
        runtime_context,
        message=message,
        kitten_extra=kitten_extra,
        reply=_xcagi_compat_reply_payload,
        merge_attachments=_merge_kitten_attachments,
    )


async def _client_issue_payload(
    request: Request, runtime_context: Context, message: str
) -> tuple[str, Payload] | None:
    from app.fastapi_routes.xcagi_compat_chat_stream import (
        _apply_client_issue_outcome,
        _classify_and_submit_client_issue_async,
        _client_issue_reply,
    )

    receipt = await _classify_and_submit_client_issue_async(request, runtime_context, message, "")
    reply = _client_issue_reply(receipt)
    if not reply:
        return None
    return reply, _apply_client_issue_outcome(_xcagi_compat_reply_payload(reply), receipt)


def _business_action(
    message: str, *, runtime_context: Context, user_id: str | None, request: Request
) -> Payload | None:
    from app.domain.app_pure.chat_business_safety import try_handle_business_chat_action

    return try_handle_business_chat_action(
        message, runtime_context=runtime_context, user_id=user_id, request=request
    )


def _slot_read(message: str, *, request: Request, user_id: str) -> Payload | None:
    from app.application.normal_chat_dispatch import try_normal_slot_read_payload

    return try_normal_slot_read_payload(message, request=request, user_id=user_id)


async def _kitten_context(context: Context, message: str) -> tuple[Context, Payload]:
    try:
        from app.application.kitten_planner_context import (
            enrich_kitten_analyzer_runtime,
            kitten_reply_attachments,
        )

        context = await enrich_kitten_analyzer_runtime(context, message)
        return context, kitten_reply_attachments(context)
    except RECOVERABLE_ERRORS:
        logger.debug("kitten planner context enrich skipped", exc_info=True)
        return context, {}


def _conversation_service() -> ConversationService:
    from app.domain.shared_services.conversation.manager import get_ai_conversation_service

    return get_ai_conversation_service()


def _sse_event(payload: Payload) -> bytes:
    from app.fastapi_routes.xcagi_compat_chat_helpers import _sse_event_line

    return _sse_event_line(payload)


def _admission() -> ChatAdmission:
    return ChatAdmission(
        merge_paths=_merge_runtime_context_with_message_paths,
        authenticate=_runtime_context_with_authenticated_actor,
        with_tier=runtime_context_with_tier,
        authorize_read=_ensure_chat_db_read_authorized,
        requires_read=_message_requires_db_read_token,
        interrupt=planner_workflow_interrupt_reply,
        after_interrupt=runtime_context_after_workflow_interrupt,
        vector_guard=_ensure_vector_index_if_needed,
        reply=_xcagi_compat_reply_payload,
    )


def _fast_paths() -> FastPaths:
    return FastPaths(_client_issue_payload, _business_action, _slot_read, _kitten_context)


def _application() -> CompatChatApplication:
    # Resolve these seams from the calling module, including separately loaded
    # facade instances. No ambient globals or shared request state is needed.
    executor = ChatTurnExecutor(
        backends=ChatBackends(
            _execute_ai_chat_mainline,
            run_agent_chat,
            create_modstore_openai_client_from_request,
            _use_ai_chat_mainline,
            _legacy_chat_fallback_allowed,
        ),
        responses=ChatResponses(
            _xcagi_compat_reply_payload,
            _legacy_requires_token_payload,
            _xcagi_chat_timeout_error_payload,
            _xcagi_chat_http_exc,
        ),
        trace=ChatTrace(_attach_compat_chat_trace, start_legacy_chat_run, finalize_legacy_chat_run),
        await_timeout=_await_with_timeout,
        clear_legacy_tool_result=_clear_legacy_tool_result_if_reply_has_no_records,
        workspace_root=lambda: os.environ.get("WORKSPACE_ROOT", os.getcwd()),
        logger=logger,
    )
    return CompatChatApplication(
        _admission(),
        executor,
        _fast_paths(),
        set_llm_mode,
        assert_p2_elevated_claim_or_raise,
        resolve_ai_tier,
        _xcagi_chat_timeout_seconds,
        single_turn=execute_compat_chat,
    )


async def _execute_compat_chat_impl(request: Request, body: XcagiCompatChatBody) -> Payload:
    return await _application().single(request, body)


async def _execute_compat_chat_batch_impl(
    request: Request, body: XcagiCompatChatBatchBody
) -> Payload:
    return await _application().batch(request, body)


def _prepare_compat_chat_body(request: Request, body: XcagiCompatChatBody) -> XcagiCompatChatBody:
    context = _runtime_context_with_authenticated_actor(request, body.context or {})
    if not str(context.get("turn_id") or "").strip():
        context["turn_id"] = uuid.uuid4().hex
    return body.model_copy(update={"context": context})


def _persist_compat_chat_turn(body: XcagiCompatChatBody, payload: dict[str, Any]) -> None:
    from app.application import get_ai_chat_app_service
    from app.application.task_conversation_store import durable_user_id

    context = body.context or {}
    owner = durable_user_id(context.get("local_user_id"))
    if (
        owner is None
        or context.get("tenant_id") is None
        or not (context.get("session_id") or context.get("conversation_id"))
    ):
        return
    try:
        get_ai_chat_app_service()._persist_chat_turn(str(owner), body.message, context, payload)
    except RECOVERABLE_ERRORS:
        logger.warning("compat chat history persistence failed", exc_info=True)


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> Payload:
    body = _prepare_compat_chat_body(request, body)
    with llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)):
        payload = await _execute_compat_chat_impl(request, body)
    _persist_compat_chat_turn(body, payload)
    return payload


async def execute_compat_chat_batch(request: Request, body: XcagiCompatChatBatchBody) -> Payload:
    with llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)):
        return await _execute_compat_chat_batch_impl(request, body)


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
) -> AsyncGenerator[bytes, None]:
    body = _prepare_compat_chat_body(request, body)
    stream = CompatStream(
        _admission(),
        _fast_paths(),
        PersonaEnricher(
            _conversation_service,
            _resolve_chat_user_id,
            _derive_industry_from_session,
            _recent_history,
            _summarize_context_for_log,
            logger,
        ),
        attach_chat_trace_run,
        _sse_event,
        resolve_ai_tier,
        _xcagi_planner_stream_bytes_async,
        logger,
    )
    pending = b""
    with llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)):
        async with aclosing(stream.run(request, body, ai_tier=ai_tier)) as chunks:
            async for chunk in chunks:
                pending += chunk
                while b"\n\n" in pending:
                    event, pending = pending.split(b"\n\n", 1)
                    for line in event.splitlines():
                        if not line.startswith(b"data: "):
                            continue
                        try:
                            item = json.loads(line[6:])
                        except (ValueError, UnicodeError):
                            continue
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") == "done" and isinstance(item.get("result"), dict):
                            _persist_compat_chat_turn(body, item["result"])
                        elif item.get("type") == "error":
                            _persist_compat_chat_turn(
                                body,
                                {
                                    "success": False,
                                    "response": str(item.get("message") or "对话执行失败"),
                                },
                            )
                yield chunk
