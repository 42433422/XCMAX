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


@pytest.fixture
def durable_compat_history(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.db.models import AIConversation, AIConversationSession, User
    from app.domain.conversation.legacy_services_service import ConversationService

    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    User.__table__.create(engine)
    AIConversationSession.__table__.create(engine)
    AIConversation.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(id=2, username="compat-test", password="disabled-fixture", tenant_id=1))
        session.commit()

    @contextmanager
    def db():
        with sessions() as session:
            yield session

    conversation = ConversationService()
    service = AIChatApplicationService.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    monkeypatch.setattr("app.services.get_conversation_service", lambda: conversation)
    monkeypatch.setattr("app.domain.conversation.legacy_services_service.get_db", db)
    monkeypatch.setattr("app.domain.conversation.legacy_services_service.notify_user", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda req: SimpleNamespace(id=2),
    )
    monkeypatch.setattr("app.infrastructure.auth.tenant_context.resolve_tenant_id", lambda req: 1)
    yield conversation, service
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["slot", "legacy", "mainline", "stream", "batch"])
async def test_compat_turn_survives_history_reload_without_duplicates(
    route, durable_compat_history, monkeypatch
):
    from app.application import planner_compat_service as compat

    conversation, service = durable_compat_history
    reply = {"success": True, "response": "客户 ID 10：联系人为验收员", "data": {}}
    body = XcagiCompatChatBody(
        message="查询客户 ID10",
        user_id="forged-owner",
        system_prompt="synthetic history regression",
        context={
            "session_id": "history-session",
            "turn_id": "history-turn",
            "local_user_id": 999,
            "tenant_id": 999,
            "api_key": "transient-test-secret",
        },
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        lambda: InMemoryAgentRunRepository(),
    )
    monkeypatch.setattr(
        "app.application.normal_chat_dispatch.try_normal_slot_read_payload",
        lambda *a, **kw: reply if route == "slot" else None,
    )
    monkeypatch.setattr(compat, "assert_p2_elevated_claim_or_raise", lambda req: None)
    monkeypatch.setattr(compat, "resolve_ai_tier", lambda req: "p1")
    monkeypatch.setattr(compat, "_ensure_chat_db_read_authorized", lambda *a, **kw: (True, None))
    monkeypatch.setattr(compat, "_ensure_vector_index_if_needed", lambda *a: None)
    monkeypatch.setattr(compat, "planner_workflow_interrupt_reply", lambda msg: None)
    monkeypatch.setattr(
        compat, "create_modstore_openai_client_from_request", lambda req: MagicMock()
    )
    monkeypatch.setattr(compat, "run_agent_chat", lambda *a, **kw: reply["response"])
    monkeypatch.setattr(compat, "_use_ai_chat_mainline", lambda ctx: route == "mainline")
    monkeypatch.setattr(
        "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
        AsyncMock(side_effect=lambda ctx, msg: ctx),
    )
    monkeypatch.setattr(
        "app.application.kitten_planner_context.kitten_reply_attachments", lambda ctx: {}
    )

    async def mainline(single, context, **kwargs):
        service._persist_chat_turn(single.user_id, single.message, context, reply)
        return reply

    async def fragmented_stream(*args, **kwargs):
        raw = stream_helpers._sse_event_line({"type": "done", "result": reply})
        for index in range(0, len(raw), 7):
            yield raw[index : index + 7]

    monkeypatch.setattr(compat, "_execute_ai_chat_mainline", mainline)
    monkeypatch.setattr(compat, "_xcagi_planner_stream_bytes_async", fragmented_stream)
    for _ in range(2):
        if route == "batch":
            await compat.execute_compat_chat_batch(
                _make_request(),
                XcagiCompatChatBatchBody(
                    messages=["查询客户 ID10", "继续查询"],
                    context=body.context,
                    user_id=body.user_id,
                ),
            )
        elif route == "stream":
            chunks = [part async for part in compat.compat_chat_stream_async(_make_request(), body)]
            assert _sse_payloads(chunks)[0]["result"] == reply
        else:
            result = await compat.execute_compat_chat(_make_request(), body)
            assert result["response"] == reply["response"]
    rows = conversation.get_session_messages("history-session")
    assert len(rows) == (4 if route == "batch" else 2)
    assert {row[2] for row in rows} == {"2"}
    assert {row[3] for row in rows} == {"user", "assistant"}
    assert all("transient-test-secret" not in row[6] for row in rows)


@pytest.mark.asyncio
async def test_compat_history_rejects_body_owner_without_authenticated_actor(
    durable_compat_history, monkeypatch
):
    from app.application import planner_compat_service as compat

    conversation, _ = durable_compat_history
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda req: None
    )
    monkeypatch.setattr(
        compat,
        "_execute_compat_chat_impl",
        AsyncMock(return_value={"success": True, "response": "reply"}),
    )
    await compat.execute_compat_chat(
        _make_request(),
        XcagiCompatChatBody(
            message="查询",
            user_id="2",
            context={"session_id": "history-session", "local_user_id": 2},
        ),
    )
    assert conversation.get_session_messages("history-session") == []


@pytest.mark.asyncio
async def test_execute_compat_chat_attaches_agent_run_id() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="查库存", user_id="u42", source="desktop")

    with (
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.normal_chat_dispatch.try_normal_slot_read_payload", return_value=None
        ),
        patch("app.application.planner_compat_service.set_llm_mode"),
        patch(
            "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
            return_value=({"workspace": "demo"}, []),
        ),
        patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
        patch(
            "app.application.planner_compat_service.resolve_ai_tier",
            return_value="p1",
        ),
        patch(
            "app.application.planner_compat_service.runtime_context_with_tier",
            return_value={"workspace": "demo", "ai_tier": "p1"},
        ),
        patch(
            "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
            new_callable=AsyncMock,
            return_value={"workspace": "demo", "ai_tier": "p1"},
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
            return_value="库存正常",
        ) as mock_chat,
    ):
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
@pytest.mark.parametrize("pending_user", ["u42", "another-conversation"])
async def test_execute_compat_chat_uses_ai_chat_mainline_when_enabled(pending_user: str) -> None:
    body = XcagiCompatChatBody(
        message="查询客户 Mac补参验收客户",
        user_id="u42",
        source="normal",
        context={"use_ai_chat_mainline": True},
    )

    with (
        patch(
            "app.application.get_ai_chat_app_service",
            return_value=MagicMock(_pending_workflows={pending_user: {"kind": "clarification"}}),
        ),
        patch(
            "app.application.normal_chat_dispatch.build_customers_query_response_dict",
            return_value={"success": True, "response": "query"},
        ) as mock_query,
        patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
        patch("app.application.planner_compat_service.resolve_ai_tier", return_value="p1"),
        patch(
            "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
            new_callable=AsyncMock,
            return_value={"use_ai_chat_mainline": True, "ai_tier": "p1"},
        ),
        patch("app.application.kitten_planner_context.kitten_reply_attachments", return_value={}),
        patch(
            "app.application.planner_compat_service._ensure_chat_db_read_authorized",
            return_value=(True, None),
        ),
        patch(
            "app.application.planner_compat_service._attach_compat_chat_trace",
            side_effect=lambda payload, *_args, **_kwargs: payload,
        ),
        patch(
            "app.application.planner_compat_service._execute_ai_chat_mainline",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "response": "mainline",
                "data": {"text": "mainline"},
            },
        ) as mock_mainline,
        patch("app.application.planner_compat_service.run_agent_chat") as mock_legacy,
    ):
        result = await execute_compat_chat(_make_request(), body)

    assert result["success"] is True
    if pending_user == "u42":
        assert result["response"] == "mainline"
        mock_mainline.assert_awaited_once()
        mock_query.assert_not_called()
    else:
        assert result["response"] == "query"
        mock_mainline.assert_not_called()
        mock_query.assert_called_once()
    mock_legacy.assert_not_called()


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

    with (
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.normal_chat_dispatch.try_normal_slot_read_payload", return_value=None
        ),
        patch("app.application.planner_compat_service.set_llm_mode"),
        patch(
            "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
            return_value=({"workspace": "demo"}, []),
        ),
        patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
        patch(
            "app.application.planner_compat_service.resolve_ai_tier",
            return_value="p1",
        ),
        patch(
            "app.application.planner_compat_service.runtime_context_with_tier",
            return_value={"workspace": "demo", "ai_tier": "p1"},
        ),
        patch(
            "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
            new_callable=AsyncMock,
            return_value={"workspace": "demo", "ai_tier": "p1"},
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
            return_value=reply,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
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

    with (
        patch(
            "app.application.normal_chat_dispatch.try_normal_slot_read_payload", return_value=None
        ),
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.application.planner_compat_service.set_llm_mode"),
        patch(
            "app.application.planner_compat_service._merge_runtime_context_with_message_paths",
            side_effect=lambda _ctx, msg: ({"workspace": "demo", "message": msg}, []),
        ),
        patch("app.application.planner_compat_service.assert_p2_elevated_claim_or_raise"),
        patch(
            "app.application.planner_compat_service.resolve_ai_tier",
            return_value="p1",
        ),
        patch(
            "app.application.planner_compat_service.runtime_context_with_tier",
            side_effect=runtime_with_tier,
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
            side_effect=lambda message, **_kwargs: f"{message}完成",
        ) as mock_chat,
    ):
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
        assert run.metadata["channel"] == "compat_chat"
        assert run.metadata["trace_mode"] == "legacy_planner_run"
        assert "planner.started" in [event.event_type for event in run.events]
        assert "planner.completed" in [event.event_type for event in run.events]
        runtime_context = mock_chat.call_args_list[idx].kwargs["runtime_context"]
        assert runtime_context["run_id"] == run_id
        assert runtime_context["agent_run_id"] == run_id


@pytest.mark.parametrize("failed_tool", [False, True])
def test_stream_done_result_attaches_agent_run_id(failed_tool: bool) -> None:
    records = (
        [
            {
                "tool_name": "execute_erp_capability",
                "tool_id": "sales",
                "action": "create_order",
                "params": {},
                "success": False,
                "output": {"success": False, "error": "customer not found"},
            }
        ]
        if failed_tool
        else []
    )
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="hello", user_id="stream-user", source="desktop")

    with (
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
        patch.object(
            stream_helpers,
            "effective_db_read_token",
            return_value="",
        ),
        patch.object(
            stream_helpers,
            "_merge_runtime_context_with_message_paths",
            return_value=({"workspace": "demo"}, []),
        ),
        patch.object(
            stream_helpers,
            "runtime_context_with_tier",
            return_value={"workspace": "demo", "ai_tier": "p1"},
        ),
        patch.object(
            stream_helpers,
            "planner_workflow_interrupt_reply",
            return_value=None,
        ),
        patch.object(
            stream_helpers,
            "_ensure_vector_index_if_needed",
            return_value=None,
        ),
        patch.object(
            stream_helpers,
            "create_modstore_openai_client_from_request",
            return_value=MagicMock(),
        ),
        patch.object(
            stream_helpers,
            "_xcagi_guarded_planner_stream_events",
            return_value=iter(
                [
                    {"type": "token", "text": "hello"},
                    {"type": "done", "result": {"legacy_tool_records": records}},
                ]
            ),
        ) as mock_stream,
    ):
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
    assert run.metadata["trace_mode"] == (
        "legacy_planner_run_with_tools" if failed_tool else "legacy_planner_run"
    )
    assert run.status == ("failed" if failed_tool else "completed")
    assert len(run.tool_calls) == int(failed_tool)
    assert "planner.started" in [event.event_type for event in run.events]
    assert "planner.completed" in [event.event_type for event in run.events]
    runtime_context = mock_stream.call_args.kwargs["runtime_context"]
    assert runtime_context["run_id"] == run_id
    assert runtime_context["agent_run_id"] == run_id


def test_stream_requires_token_event_finalizes_waiting_agent_run() -> None:
    repo = InMemoryAgentRunRepository()
    body = XcagiCompatChatBody(message="写入数据库", user_id="stream-user", source="desktop")

    with (
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
        patch.object(
            stream_helpers,
            "effective_db_read_token",
            return_value="",
        ),
        patch.object(
            stream_helpers,
            "_merge_runtime_context_with_message_paths",
            return_value=({"workspace": "demo"}, []),
        ),
        patch.object(
            stream_helpers,
            "runtime_context_with_tier",
            return_value={"workspace": "demo", "ai_tier": "p1"},
        ),
        patch.object(
            stream_helpers,
            "planner_workflow_interrupt_reply",
            return_value=None,
        ),
        patch.object(
            stream_helpers,
            "_ensure_vector_index_if_needed",
            return_value=None,
        ),
        patch.object(
            stream_helpers,
            "create_modstore_openai_client_from_request",
            return_value=MagicMock(),
        ),
        patch.object(
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

    with (
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
        patch.object(
            stream_helpers,
            "effective_db_read_token",
            return_value="",
        ),
        patch.object(
            stream_helpers,
            "_merge_runtime_context_with_message_paths",
            return_value=({"workspace": "demo"}, []),
        ),
        patch.object(
            stream_helpers,
            "runtime_context_with_tier",
            return_value={"workspace": "demo", "ai_tier": "p1"},
        ),
        patch.object(
            stream_helpers,
            "planner_workflow_interrupt_reply",
            return_value=None,
        ),
        patch.object(
            stream_helpers,
            "_ensure_vector_index_if_needed",
            return_value=None,
        ),
        patch.object(
            stream_helpers,
            "create_modstore_openai_client_from_request",
            return_value=MagicMock(),
        ),
        patch.object(
            stream_helpers,
            "_xcagi_guarded_planner_stream_events",
            return_value=iter([{"type": "error", "message": "stream error", "status_code": 503}]),
        ),
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
