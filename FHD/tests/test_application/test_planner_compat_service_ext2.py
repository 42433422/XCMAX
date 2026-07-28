"""Tests for app.application.planner_compat_service — extended coverage (ext2).

Focus: execute_compat_chat with various paths (mode setting, kitten enrich,
db read token required, workflow interrupt, vector error, timeout, recoverable
errors, reply parsing), execute_compat_chat_batch (empty messages, all success,
mixed results), compat_chat_stream_async.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.application.planner_compat_service import (
    compat_chat_stream_async,
    execute_compat_chat,
    execute_compat_chat_batch,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)


def _make_request(*, ip: str = "127.0.0.1", is_admin: bool = False) -> Request:
    """Create a mock Request with scope state."""
    scope = {
        "type": "http",
        "headers": [],
        "method": "POST",
        "path": "/",
        "client": (ip, 12345),
        "state": {},
    }
    req = Request(scope)
    # Set scope state
    req.scope["state"] = {
        "lan_client_ip": ip,
        "lan_is_admin": is_admin,
    }
    return req


# ---------------------------------------------------------------------------
# execute_compat_chat — mode setting
# ---------------------------------------------------------------------------


class TestExecuteCompatChatMode:
    @pytest.mark.asyncio
    async def test_mode_online_sets_llm_mode(self):
        body = XcagiCompatChatBody(message="hi", mode="online")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode") as mock_set_mode,
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value="hello back",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "hello back"},
            ),
        ):
            result = await execute_compat_chat(request, body)
            mock_set_mode.assert_called_once_with("online")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_mode_offline_sets_llm_mode(self):
        body = XcagiCompatChatBody(message="hi", mode="offline")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode") as mock_set_mode,
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value="hello back",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "hello back"},
            ),
        ):
            result = await execute_compat_chat(request, body)
            mock_set_mode.assert_called_once_with("offline")

    @pytest.mark.asyncio
    async def test_mode_other_does_not_set_llm_mode(self):
        body = XcagiCompatChatBody(message="hi", mode="invalid")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode") as mock_set_mode,
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value="hello back",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "hello back"},
            ),
        ):
            await execute_compat_chat(request, body)
            mock_set_mode.assert_not_called()


# ---------------------------------------------------------------------------
# execute_compat_chat — db read token required
# ---------------------------------------------------------------------------


class TestExecuteCompatChatDbReadToken:
    @pytest.mark.asyncio
    async def test_db_read_token_required(self):
        body = XcagiCompatChatBody(message="查看数据库")
        request = _make_request()

        read_req = {
            "token_name": "DB_READ_TOKEN",
            "token_description": "desc",
            "message": "需要令牌",
        }

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(False, read_req),
            ),
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True
            assert result["requires_token"] is True
            assert result["token_name"] == "DB_READ_TOKEN"


# ---------------------------------------------------------------------------
# execute_compat_chat — workflow interrupt
# ---------------------------------------------------------------------------


class TestExecuteCompatChatWorkflowInterrupt:
    @pytest.mark.asyncio
    async def test_workflow_interrupt_reply(self):
        body = XcagiCompatChatBody(message="中断流程")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value="已中断当前流程。",
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_after_workflow_interrupt",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "已中断当前流程。"},
            ) as mock_payload,
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True
            mock_payload.assert_called_once()


# ---------------------------------------------------------------------------
# execute_compat_chat — vector error
# ---------------------------------------------------------------------------


class TestExecuteCompatChatVectorError:
    @pytest.mark.asyncio
    async def test_vector_error_returns_payload(self):
        body = XcagiCompatChatBody(message="向量索引")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value="向量索引失败",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "向量索引失败"},
            ) as mock_payload,
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True
            mock_payload.assert_called_once()


# ---------------------------------------------------------------------------
# execute_compat_chat — timeout
# ---------------------------------------------------------------------------


class TestExecuteCompatChatTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error_payload(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                side_effect=TimeoutError("timed out"),
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_error_payload",
                return_value={"success": False, "message": "timeout"},
            ) as mock_timeout_payload,
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is False
            mock_timeout_payload.assert_called_once_with(30.0)


# ---------------------------------------------------------------------------
# execute_compat_chat — recoverable errors
# ---------------------------------------------------------------------------


class TestExecuteCompatChatRecoverableErrors:
    @pytest.mark.asyncio
    async def test_recoverable_error_raises_http_exception(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        http_exc = HTTPException(status_code=503, detail="service unavailable")

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                side_effect=RuntimeError("db error"),
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_http_exc",
                return_value=http_exc,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_compat_chat(request, body)
            assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# execute_compat_chat — reply parsing (requires_token in reply)
# ---------------------------------------------------------------------------


class TestExecuteCompatChatReplyParsing:
    @pytest.mark.asyncio
    async def test_reply_dict_with_requires_token(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        reply_dict = {
            "requires_token": True,
            "token_name": "DB_READ_TOKEN",
            "token_description": "desc",
            "message": "需要令牌",
        }

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value=reply_dict,
            ),
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True
            assert result["requires_token"] is True
            assert result["token_name"] == "DB_READ_TOKEN"

    @pytest.mark.asyncio
    async def test_reply_string_with_requires_token_json(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        import json

        reply_str = json.dumps(
            {
                "requires_token": True,
                "token_name": "DB_TOKEN",
                "token_description": "desc",
                "message": "需要令牌",
            }
        )

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value=reply_str,
            ),
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True
            assert result["requires_token"] is True

    @pytest.mark.asyncio
    async def test_reply_string_invalid_json_falls_through(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.kitten_reply_attachments",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value="not json {",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "not json {"},
            ) as mock_payload,
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True
            mock_payload.assert_called_once()


# ---------------------------------------------------------------------------
# execute_compat_chat — kitten enrich error
# ---------------------------------------------------------------------------


class TestExecuteCompatChatKittenError:
    @pytest.mark.asyncio
    async def test_kitten_enrich_error_skipped(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
                new_callable=AsyncMock,
                side_effect=RuntimeError("kitten failed"),
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value="ok",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "ok"},
            ),
        ):
            result = await execute_compat_chat(request, body)
            assert result["success"] is True


# ---------------------------------------------------------------------------
# execute_compat_chat_batch
# ---------------------------------------------------------------------------


class TestExecuteCompatChatBatch:
    @pytest.mark.asyncio
    async def test_empty_messages_raises_400(self):
        body = XcagiCompatChatBatchBody(messages=[])
        request = _make_request()

        with patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"):
            with pytest.raises(HTTPException) as exc_info:
                await execute_compat_chat_batch(request, body)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_only_messages_raises_400(self):
        body = XcagiCompatChatBatchBody(messages=["  ", "", "  "])
        request = _make_request()

        with patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"):
            with pytest.raises(HTTPException) as exc_info:
                await execute_compat_chat_batch(request, body)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_all_success(self):
        body = XcagiCompatChatBatchBody(messages=["msg1", "msg2"])
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                return_value="reply",
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "reply"},
            ),
        ):
            result = await execute_compat_chat_batch(request, body)
            assert result["success"] is True
            assert result["batch"] is True
            assert result["count"] == 2
            assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_with_db_read_token_required(self):
        body = XcagiCompatChatBatchBody(messages=["查看数据库"])
        request = _make_request()

        read_req = {
            "token_name": "DB_READ_TOKEN",
            "token_description": "desc",
            "message": "需要令牌",
        }

        with (
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(False, read_req),
            ),
        ):
            result = await execute_compat_chat_batch(request, body)
            assert result["success"] is True  # token required counts as success
            assert result["results"][0]["requires_token"] is True

    @pytest.mark.asyncio
    async def test_with_workflow_interrupt(self):
        body = XcagiCompatChatBatchBody(messages=["中断流程"])
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value="已中断",
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_after_workflow_interrupt",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._xcagi_compat_reply_payload",
                return_value={"success": True, "response": "已中断"},
            ),
        ):
            result = await execute_compat_chat_batch(request, body)
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_with_timeout(self):
        body = XcagiCompatChatBatchBody(messages=["msg1"])
        request = _make_request()

        with (
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                side_effect=TimeoutError("timed out"),
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_error_payload",
                return_value={"success": False, "message": "timeout"},
            ),
        ):
            result = await execute_compat_chat_batch(request, body)
            assert result["success"] is False  # one failed
            assert result["results"][0]["success"] is False

    @pytest.mark.asyncio
    async def test_with_recoverable_error(self):
        body = XcagiCompatChatBatchBody(messages=["msg1"])
        request = _make_request()

        http_exc = HTTPException(status_code=503, detail="service down")

        with (
            patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch("app.application.planner_compat_service.set_llm_mode"),
            patch(
                "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
                return_value=({}, None),
            ),
            patch(
                "app.application.planner_compat_service.runtime_context_with_tier",
                return_value={},
            ),
            patch(
                "app.application.planner_compat_service._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.application.planner_compat_service._message_requires_db_read_token",
                return_value=False,
            ),
            patch(
                "app.application.planner_compat_service.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
                return_value=30.0,
            ),
            patch(
                "app.application.planner_compat_service.create_modstore_openai_client_from_request",
                return_value=MagicMock(),
            ),
            patch(
                "app.application.planner_compat_service.run_agent_chat",
                side_effect=RuntimeError("db error"),
            ),
            patch(
                "app.application.planner_compat_service._xcagi_chat_http_exc",
                return_value=http_exc,
            ),
        ):
            result = await execute_compat_chat_batch(request, body)
            assert result["success"] is False
            assert result["results"][0]["success"] is False


# ---------------------------------------------------------------------------
# compat_chat_stream_async
# ---------------------------------------------------------------------------


class TestCompatChatStreamAsync:
    @staticmethod
    def _event(chunk: bytes) -> dict[str, Any]:
        text = chunk.decode("utf-8")
        assert text.startswith("data: ")
        return json.loads(text[6:].strip())

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        async def mock_stream(*args, **kwargs):
            yield b"chunk1"
            yield b"chunk2"

        with (
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service._xcagi_planner_stream_bytes_async",
                return_value=mock_stream(),
            ),
        ):
            chunks = []
            async for chunk in compat_chat_stream_async(request, body):
                chunks.append(chunk)
            assert self._event(chunks[0]) == {
                "type": "tool_progress",
                "label": "正在连接模型服务",
                "phase": "model_connect",
            }
            assert chunks[1:] == [b"chunk1", b"chunk2"]

    @pytest.mark.asyncio
    async def test_stream_with_explicit_ai_tier(self):
        body = XcagiCompatChatBody(message="hi")
        request = _make_request()

        async def mock_stream(*args, **kwargs):
            yield b"data"

        with (
            patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
            patch(
                "app.application.planner_compat_service._xcagi_planner_stream_bytes_async",
                return_value=mock_stream(),
            ) as mock_planner_stream,
        ):
            chunks = []
            async for chunk in compat_chat_stream_async(request, body, ai_tier="p2"):
                chunks.append(chunk)
            assert self._event(chunks[0])["type"] == "tool_progress"
            assert chunks[1:] == [b"data"]
            # Verify ai_tier was passed through
            _, kwargs = mock_planner_stream.call_args
            assert kwargs.get("ai_tier") == "p2"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("source,mode", [("normal", "basic"), ("pro", "professional")])
    async def test_shipment_phrase_returns_confirmation_without_llm_or_execution(
        self, source: str, mode: str
    ):
        """The exact desktop stream path must only issue a preview card.

        This is intentionally tested for both profiles because the stream
        endpoint is shared.  The task remains an unexecuted shipment_generate
        request; no print or database write is allowed here.
        """

        body = XcagiCompatChatBody(
            message="打印侯雪梅发货单，编号9803，规格28，3桶",
            source=source,
            mode=mode,
        )
        request = _make_request()
        preview = {
            "success": True,
            "message": "已识别订单，请确认执行",
            "response": '已识别订单，请点击"确认执行"生成发货单。',
            "task": {
                "type": "shipment_generate",
                "title": "发货单预览",
                "payload": {"tool_id": "shipment_generate", "action": "执行"},
            },
        }

        with (
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "shipment", "slots": {}},
            ),
            patch(
                "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
                return_value=preview,
            ) as preview_fn,
            patch(
                "app.application.planner_compat_service._xcagi_planner_stream_bytes_async",
                side_effect=AssertionError("shipment preview must not invoke the LLM stream"),
            ) as stream_fn,
        ):
            chunks = []
            async for chunk in compat_chat_stream_async(request, body):
                chunks.append(chunk)

        assert preview_fn.call_args.args == (body.message,)
        stream_fn.assert_not_called()
        events = [self._event(chunk) for chunk in chunks]
        assert events == [
            {"type": "token", "text": preview["response"]},
            {"type": "done", "result": preview},
        ]
        assert events[-1]["result"]["task"]["type"] == "shipment_generate"
        assert "print" not in events[-1]["result"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("message", "intent", "builder_name", "response"),
        [
            ("有哪些客户？", "customers_query", "build_customers_query_response_dict", "共找到 2 位客户：\n- 甲公司"),
            ("查产品", "product_query", "build_product_query_response_dict", "已打开产品副窗。"),
        ],
    )
    async def test_read_only_business_query_bypasses_llm_when_provider_is_unavailable(
        self, message: str, intent: str, builder_name: str, response: str
    ):
        """客户/产品读取走本地槽位，绝不因模型配额耗尽而失败。"""

        body = XcagiCompatChatBody(message=message)
        request = _make_request()
        payload = {"success": True, "response": response, "data": {"intent": intent}}

        with (
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": intent, "slots": {"keyword": ""}},
            ),
            patch(
                f"app.application.normal_chat_dispatch.{builder_name}",
                return_value=payload,
            ) as builder,
            patch(
                "app.application.planner_compat_service._xcagi_planner_stream_bytes_async",
                side_effect=AssertionError("read-only business query must not invoke the LLM stream"),
            ) as stream_fn,
        ):
            chunks = []
            async for chunk in compat_chat_stream_async(request, body):
                chunks.append(chunk)

        builder.assert_called_once()
        stream_fn.assert_not_called()
        assert [self._event(chunk) for chunk in chunks] == [
            {"type": "token", "text": response},
            {"type": "done", "result": payload},
        ]

    @pytest.mark.asyncio
    async def test_raw_database_phrase_does_not_bypass_existing_read_token_guard(self):
        """快捷只覆盖受控客户/产品读取，不能偷跑原始数据库读取。"""

        body = XcagiCompatChatBody(message="查客户数据库", system_prompt="test")
        request = _make_request()

        async def mock_stream(*args, **kwargs):
            yield b"normal-path"

        with (
            patch(
                "app.application.planner_compat_service._xcagi_planner_stream_bytes_async",
                return_value=mock_stream(),
            ) as stream_fn,
        ):
            chunks = []
            async for chunk in compat_chat_stream_async(request, body):
                chunks.append(chunk)

        stream_fn.assert_called_once()
        assert self._event(chunks[0])["type"] == "tool_progress"
        assert chunks[1:] == [b"normal-path"]
