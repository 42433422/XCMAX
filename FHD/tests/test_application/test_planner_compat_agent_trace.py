from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.planner_compat_service import execute_compat_chat, execute_compat_chat_batch
from app.fastapi_routes import xcagi_compat_chat_helpers as stream_helpers
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)


def _make_request() -> Request:
    scope = {
        "type": "http",
        "headers": [],
        "method": "POST",
        "path": "/api/ai/chat",
        "client": ("127.0.0.1", 12345),
        "state": {"lan_client_ip": "127.0.0.1", "lan_is_admin": True},
    }
    return Request(scope)


def _sse_payloads(chunks: list[bytes]) -> list[dict]:
    payloads: list[dict] = []
    for item in b"".join(chunks).decode("utf-8").split("\n\n"):
        if not item.startswith("data: "):
            continue
        payloads.append(json.loads(item[len("data: ") :]))
    return payloads


@pytest.mark.asyncio
async def test_execute_compat_chat_attaches_agent_run_id() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="查库存", user_id="u42", source="desktop")

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ), patch(
        "app.application.planner_compat_service.set_llm_mode"
    ), patch(
        "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
        return_value=({"workspace": "demo"}, []),
    ), patch(
        "app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"
    ), patch(
        "app.application.planner_compat_service.resolve_ai_tier",
        return_value="p1",
    ), patch(
        "app.application.planner_compat_service.runtime_context_with_tier",
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch(
        "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
        new_callable=AsyncMock,
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch(
        "app.application.kitten_planner_context.kitten_reply_attachments",
        return_value={},
    ), patch(
        "app.application.planner_compat_service._ensure_chat_db_read_authorized",
        return_value=(True, None),
    ), patch(
        "app.application.planner_compat_service._message_requires_db_read_token",
        return_value=False,
    ), patch(
        "app.application.planner_compat_service.planner_workflow_interrupt_reply",
        return_value=None,
    ), patch(
        "app.application.planner_compat_service._ensure_vector_index_if_needed",
        return_value=None,
    ), patch(
        "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
        return_value=30.0,
    ), patch(
        "app.application.planner_compat_service.create_modstore_openai_client_from_request",
        return_value=MagicMock(),
    ), patch(
        "app.application.planner_compat_service.run_agent_chat",
        return_value="库存正常",
    ) as mock_chat:
        result = await execute_compat_chat(_make_request(), body)

    run_id = result["run_id"]
    assert result["success"] is True
    assert result["data"]["run_id"] == run_id

    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "u42"
    assert run.status == "completed"
    assert run.metadata["source"] == "desktop"
    assert run.metadata["channel"] == "compat_chat"
    assert run.metadata["trace_mode"] == "legacy_planner_run"
    assert "planner.started" in [event.event_type for event in run.events]
    assert "planner.completed" in [event.event_type for event in run.events]
    runtime_context = mock_chat.call_args.kwargs["runtime_context"]
    assert runtime_context["run_id"] == run_id
    assert runtime_context["agent_run_id"] == run_id


@pytest.mark.asyncio
async def test_execute_compat_chat_observes_reply_tool_records_across_thread() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="查产品 5003", user_id="u42", source="desktop")
    reply = {
        "response": "查询完成",
        "text": "查询完成",
        "legacy_tool_records": [
            {
                "tool_id": "products",
                "tool_name": "products",
                "action": "query",
                "params": {"keyword": "5003"},
                "output": {"success": True, "data": [{"model_number": "5003"}]},
                "tool_call_id": "tc-products",
            }
        ],
    }

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ), patch(
        "app.application.planner_compat_service.set_llm_mode"
    ), patch(
        "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
        return_value=({"workspace": "demo"}, []),
    ), patch(
        "app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"
    ), patch(
        "app.application.planner_compat_service.resolve_ai_tier",
        return_value="p1",
    ), patch(
        "app.application.planner_compat_service.runtime_context_with_tier",
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch(
        "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
        new_callable=AsyncMock,
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch(
        "app.application.kitten_planner_context.kitten_reply_attachments",
        return_value={},
    ), patch(
        "app.application.planner_compat_service._ensure_chat_db_read_authorized",
        return_value=(True, None),
    ), patch(
        "app.application.planner_compat_service._message_requires_db_read_token",
        return_value=False,
    ), patch(
        "app.application.planner_compat_service.planner_workflow_interrupt_reply",
        return_value=None,
    ), patch(
        "app.application.planner_compat_service._ensure_vector_index_if_needed",
        return_value=None,
    ), patch(
        "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
        return_value=30.0,
    ), patch(
        "app.application.planner_compat_service.create_modstore_openai_client_from_request",
        return_value=MagicMock(),
    ), patch(
        "app.application.planner_compat_service.run_agent_chat",
        return_value=reply,
    ), patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool"
    ) as mock_execute:
        result = await execute_compat_chat(_make_request(), body)

    run = repo.get(result["run_id"])
    assert run is not None
    assert result["data"]["legacy_tool_records"][0]["tool_call_id"] == "tc-products"
    assert run.intent == "legacy_chat_adapter"
    assert run.metadata["trace_mode"] == "legacy_planner_run_with_tools"
    assert run.tool_calls[0].metadata["observed"] is True
    assert run.tool_calls[0].tool_id == "products"
    assert run.tool_calls[0].action == "query"
    assert run.metadata["cost_units_total"] == 1
    mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_execute_compat_chat_batch_precreates_agent_run_per_message() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBatchBody(
        messages=["查库存", "查客户"],
        user_id="batch-user",
        source="desktop",
    )

    def runtime_with_tier(ctx: dict, tier: str) -> dict:
        return {**ctx, "ai_tier": tier}

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ), patch(
        "app.application.planner_compat_service.set_llm_mode"
    ), patch(
        "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
        side_effect=lambda _ctx, msg: ({"workspace": "demo", "message": msg}, []),
    ), patch(
        "app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"
    ), patch(
        "app.application.planner_compat_service.resolve_ai_tier",
        return_value="p1",
    ), patch(
        "app.application.planner_compat_service.runtime_context_with_tier",
        side_effect=runtime_with_tier,
    ), patch(
        "app.application.planner_compat_service._ensure_chat_db_read_authorized",
        return_value=(True, None),
    ), patch(
        "app.application.planner_compat_service._message_requires_db_read_token",
        return_value=False,
    ), patch(
        "app.application.planner_compat_service.planner_workflow_interrupt_reply",
        return_value=None,
    ), patch(
        "app.application.planner_compat_service._ensure_vector_index_if_needed",
        return_value=None,
    ), patch(
        "app.application.planner_compat_service._xcagi_chat_timeout_seconds",
        return_value=30.0,
    ), patch(
        "app.application.planner_compat_service.create_modstore_openai_client_from_request",
        return_value=MagicMock(),
    ), patch(
        "app.application.planner_compat_service.run_agent_chat",
        side_effect=lambda message, **_kwargs: f"{message}完成",
    ) as mock_chat:
        result = await execute_compat_chat_batch(_make_request(), body)

    assert result["success"] is True
    assert result["count"] == 2
    run_ids = [item["run_id"] for item in result["results"]]
    assert len(set(run_ids)) == 2

    for idx, run_id in enumerate(run_ids):
        run = repo.get(run_id)
        assert run is not None
        assert run.user_id == "batch-user"
        assert run.message == body.messages[idx]
        assert run.status == "completed"
        assert run.metadata["source"] == "desktop"
        assert run.metadata["channel"] == "compat_chat_batch"
        assert run.metadata["trace_mode"] == "legacy_planner_run"
        assert "planner.started" in [event.event_type for event in run.events]
        assert "planner.completed" in [event.event_type for event in run.events]
        runtime_context = mock_chat.call_args_list[idx].kwargs["runtime_context"]
        assert runtime_context["run_id"] == run_id
        assert runtime_context["agent_run_id"] == run_id


def test_stream_done_result_attaches_agent_run_id() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="hello", user_id="stream-user", source="desktop")

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ), patch.object(
        stream_helpers,
        "effective_db_read_token",
        return_value="",
    ), patch.object(
        stream_helpers,
        "_merge_runtime_context_with_message_paths",
        return_value=({"workspace": "demo"}, []),
    ), patch.object(
        stream_helpers,
        "runtime_context_with_tier",
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch.object(
        stream_helpers,
        "planner_workflow_interrupt_reply",
        return_value=None,
    ), patch.object(
        stream_helpers,
        "_ensure_vector_index_if_needed",
        return_value=None,
    ), patch.object(
        stream_helpers,
        "create_modstore_openai_client_from_request",
        return_value=MagicMock(),
    ), patch.object(
        stream_helpers,
        "_xcagi_guarded_planner_stream_events",
        return_value=iter([{"type": "token", "text": "hello"}, {"type": "done"}]),
    ) as mock_stream:
        chunks = list(
            stream_helpers._xcagi_planner_stream_bytes(
                _make_request(),
                body,
                ai_tier="p1",
            )
        )

    done = [payload for payload in _sse_payloads(chunks) if payload.get("type") == "done"][0]
    result = done["result"]
    run_id = result["run_id"]
    assert result["data"]["run_id"] == run_id

    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "stream-user"
    assert run.metadata["channel"] == "compat_chat_stream"
    assert run.metadata["trace_mode"] == "legacy_planner_run"
    assert "planner.started" in [event.event_type for event in run.events]
    assert "planner.completed" in [event.event_type for event in run.events]
    runtime_context = mock_stream.call_args.kwargs["runtime_context"]
    assert runtime_context["run_id"] == run_id
    assert runtime_context["agent_run_id"] == run_id


def test_stream_requires_token_event_finalizes_waiting_agent_run() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="写入数据库", user_id="stream-user", source="desktop")

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ), patch.object(
        stream_helpers,
        "effective_db_read_token",
        return_value="",
    ), patch.object(
        stream_helpers,
        "_merge_runtime_context_with_message_paths",
        return_value=({"workspace": "demo"}, []),
    ), patch.object(
        stream_helpers,
        "runtime_context_with_tier",
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch.object(
        stream_helpers,
        "planner_workflow_interrupt_reply",
        return_value=None,
    ), patch.object(
        stream_helpers,
        "_ensure_vector_index_if_needed",
        return_value=None,
    ), patch.object(
        stream_helpers,
        "create_modstore_openai_client_from_request",
        return_value=MagicMock(),
    ), patch.object(
        stream_helpers,
        "_xcagi_guarded_planner_stream_events",
        return_value=iter(
            [
                {"type": "token", "text": "partial"},
                {
                    "type": "requires_token",
                    "token_name": "DB_WRITE_TOKEN",
                    "token_description": "数据库写入令牌",
                    "message": "需要写入授权",
                },
            ]
        ),
    ):
        chunks = list(
            stream_helpers._xcagi_planner_stream_bytes(
                _make_request(),
                body,
                ai_tier="p1",
            )
        )

    requires_token = [
        payload for payload in _sse_payloads(chunks) if payload.get("type") == "requires_token"
    ][0]
    run_id = requires_token["run_id"]
    run = repo.get(run_id)
    assert run is not None
    assert run.status == "waiting_user"
    assert run.metadata["channel"] == "compat_chat_stream"
    assert "planner.completed" in [event.event_type for event in run.events]
    assert "step.waiting_user" in [event.event_type for event in run.events]


def test_stream_error_event_finalizes_failed_agent_run() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="hello", user_id="stream-user", source="desktop")

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ), patch.object(
        stream_helpers,
        "effective_db_read_token",
        return_value="",
    ), patch.object(
        stream_helpers,
        "_merge_runtime_context_with_message_paths",
        return_value=({"workspace": "demo"}, []),
    ), patch.object(
        stream_helpers,
        "runtime_context_with_tier",
        return_value={"workspace": "demo", "ai_tier": "p1"},
    ), patch.object(
        stream_helpers,
        "planner_workflow_interrupt_reply",
        return_value=None,
    ), patch.object(
        stream_helpers,
        "_ensure_vector_index_if_needed",
        return_value=None,
    ), patch.object(
        stream_helpers,
        "create_modstore_openai_client_from_request",
        return_value=MagicMock(),
    ), patch.object(
        stream_helpers,
        "_xcagi_guarded_planner_stream_events",
        return_value=iter([{"type": "error", "message": "stream error", "status_code": 503}]),
    ):
        chunks = list(
            stream_helpers._xcagi_planner_stream_bytes(
                _make_request(),
                body,
                ai_tier="p1",
            )
        )

    error = [payload for payload in _sse_payloads(chunks) if payload.get("type") == "error"][0]
    run_id = error["run_id"]
    run = repo.get(run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.error == "stream error"
    assert run.metadata["channel"] == "compat_chat_stream"
