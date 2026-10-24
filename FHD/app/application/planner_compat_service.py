# ruff: noqa: F401
"""Planner 兼容对话服务（3d）：供宿主 /api/ai/* 与 Mod facade 共用。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, cast

from fastapi import HTTPException, Request

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run,
    finalize_legacy_chat_run,
    start_legacy_chat_run,
)
from app.application.planner_compat_execute import (
    execute_compat_chat as _execute_compat_chat_impl,
)
from app.application.planner_compat_execute import (
    execute_compat_chat_batch as _execute_compat_chat_batch_impl,
)
from app.application.planner_compat_execute import reset_facade_globals, set_facade_globals
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
from app.services.conversation.modstore_adapter import create_modstore_openai_client_from_request
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


from app.application.planner_compat_service_part01 import (
    _request_session_candidates as _request_session_candidates,
)

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


from app.application.planner_compat_service_part02 import (
    _attach_compat_chat_trace as _attach_compat_chat_trace,
)
from app.application.planner_compat_service_part02 import (
    _await_with_timeout as _await_with_timeout,
)
from app.application.planner_compat_service_part02 import (
    _clear_legacy_tool_result_if_reply_has_no_records as _clear_legacy_tool_result_if_reply_has_no_records,
)
from app.application.planner_compat_service_part02 import (
    _derive_industry_from_session as _derive_industry_from_session,
)
from app.application.planner_compat_service_part02 import (
    _env_truthy as _env_truthy,
)
from app.application.planner_compat_service_part02 import (
    _execute_ai_chat_mainline as _execute_ai_chat_mainline,
)
from app.application.planner_compat_service_part02 import (
    _legacy_chat_fallback_allowed as _legacy_chat_fallback_allowed,
)
from app.application.planner_compat_service_part02 import (
    _legacy_requires_token_payload as _legacy_requires_token_payload,
)
from app.application.planner_compat_service_part02 import (
    _merge_kitten_attachments as _merge_kitten_attachments,
)
from app.application.planner_compat_service_part02 import (
    _recent_history as _recent_history,
)
from app.application.planner_compat_service_part02 import (
    _reply_has_legacy_tool_records as _reply_has_legacy_tool_records,
)
from app.application.planner_compat_service_part02 import (
    _resolve_chat_user_id as _resolve_chat_user_id,
)
from app.application.planner_compat_service_part02 import (
    _summarize_context_for_log as _summarize_context_for_log,
)
from app.application.planner_compat_service_part02 import (
    _use_ai_chat_mainline as _use_ai_chat_mainline,
)
from app.application.planner_compat_service_part03 import (
    compat_chat_stream_async as _compat_chat_stream_async_impl,
)


def _prepare_compat_chat_body(request: Request, body: XcagiCompatChatBody) -> XcagiCompatChatBody:
    context = _runtime_context_with_authenticated_actor(request, body.context)
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


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> dict[str, Any]:
    """Run the extracted implementation against this facade's patchable globals."""
    token = set_facade_globals(globals())
    try:
        body = _prepare_compat_chat_body(request, body)
        with llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)):
            payload = await _execute_compat_chat_impl(request, body)
        _persist_compat_chat_turn(body, payload)
        return payload
    finally:
        reset_facade_globals(token)


async def execute_compat_chat_batch(
    request: Request, body: XcagiCompatChatBatchBody
) -> dict[str, Any]:
    """Run the extracted batch implementation against this facade instance."""
    token = set_facade_globals(globals())
    try:
        with llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)):
            return await _execute_compat_chat_batch_impl(request, body)
    finally:
        reset_facade_globals(token)


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    """Keep stream helpers bound to this facade while iterating the async generator."""
    token = set_facade_globals(globals())
    try:
        body = _prepare_compat_chat_body(request, body)
        pending = b""
        with llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request)):
            async for chunk in _compat_chat_stream_async_impl(request, body, ai_tier=ai_tier):
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
    finally:
        reset_facade_globals(token)
