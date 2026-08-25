# ruff: noqa: F401
"""Planner 兼容对话服务（3d）：供宿主 /api/ai/* 与 Mod facade 共用。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
    _runtime_context_with_trusted_dataset_access,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_planner_stream_bytes_async,
)
from app.infrastructure.llm.client import set_mode as set_llm_mode
from app.legacy.chat.legacy_chat_adapter import chat as run_agent_chat
from app.services.conversation.modstore_adapter import create_modstore_openai_client_from_request
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

_COMPAT_PATCH_EXPORTS: tuple[Any, ...] = (
    json,
    cast,
    HTTPException,
    finalize_legacy_chat_run,
    start_legacy_chat_run,
)
_COMPAT_PATCH_EXPORTS += (assert_p2_elevated_claim_or_raise, runtime_context_with_tier)
_COMPAT_PATCH_EXPORTS += (
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)
_COMPAT_PATCH_EXPORTS += (_ensure_chat_db_read_authorized, _ensure_vector_index_if_needed)
_COMPAT_PATCH_EXPORTS += (_message_requires_db_read_token, _xcagi_chat_http_exc)
_COMPAT_PATCH_EXPORTS += (_xcagi_chat_timeout_error_payload, _xcagi_chat_timeout_seconds)
_COMPAT_PATCH_EXPORTS += (set_llm_mode, run_agent_chat, create_modstore_openai_client_from_request)

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
from app.application.planner_compat_service_part02 import (
    execute_compat_chat as _execute_compat_chat_part,
)
from app.application.planner_compat_service_part02 import (
    execute_compat_chat_batch as _execute_compat_chat_batch_part,
)
from app.application.planner_compat_service_part03 import (
    compat_chat_stream_async as _compat_chat_stream_async_impl,
)


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> dict[str, Any]:
    """Run the extracted implementation against this facade's patchable globals."""
    token = set_facade_globals(globals())
    try:
        return await _execute_compat_chat_impl(request, body)
    finally:
        reset_facade_globals(token)


async def execute_compat_chat_batch(
    request: Request, body: XcagiCompatChatBatchBody
) -> dict[str, Any]:
    """Run the extracted batch implementation against this facade instance."""
    token = set_facade_globals(globals())
    try:
        return await _execute_compat_chat_batch_impl(request, body)
    finally:
        reset_facade_globals(token)


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    """Keep stream helpers bound to this facade while iterating the async generator."""
    token = set_facade_globals(globals())
    try:
        async for chunk in _compat_chat_stream_async_impl(request, body, ai_tier=ai_tier):
            yield chunk
    finally:
        reset_facade_globals(token)
