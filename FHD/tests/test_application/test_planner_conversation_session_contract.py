"""Regression coverage for the public top-level chat session id contract."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.application import planner_compat_service as service
from app.fastapi_routes.domains.conversation.helpers import XcagiCompatChatBody


def test_execute_compat_chat_keeps_top_level_session_id_on_mainline() -> None:
    body = XcagiCompatChatBody(
        message="你好",
        session_id="session-contract-mainline",
        user_id="default",
        source="normal",
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat",
            "headers": [],
        }
    )
    captured: dict[str, object] = {}

    async def _mainline(_body, runtime_context, **_kwargs):
        captured.update(runtime_context)
        return {"success": True, "run_id": "run-session-contract"}

    with (
        patch.object(service, "assert_p2_elevated_claim_or_raise"),
        patch.object(service, "resolve_ai_tier", return_value="p1"),
        patch.object(service, "runtime_context_with_tier", side_effect=lambda ctx, _tier: ctx),
        patch.object(service, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(service, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(service, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(service, "_use_ai_chat_mainline", return_value=True),
        patch.object(service, "_execute_ai_chat_mainline", new=AsyncMock(side_effect=_mainline)),
        patch(
            "app.application.chat_business_safety.try_handle_business_chat_action",
            return_value=None,
        ),
        patch(
            "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
            new=AsyncMock(side_effect=lambda ctx, _message: ctx),
        ),
        patch(
            "app.application.kitten_planner_context.kitten_reply_attachments",
            return_value={},
        ),
    ):
        result = asyncio.run(service.execute_compat_chat(request, body))

    assert result["success"] is True
    assert captured["session_id"] == "session-contract-mainline"
