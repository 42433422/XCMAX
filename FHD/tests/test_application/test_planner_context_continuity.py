"""Capture real planner provider IO without a paid model or external storage."""

import copy
import json
import re
import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import context_window_manager as windows
from app.application.ai_chat import dialogue_memory as memory
from app.application.workflow import llm_plan_generation as generation
from app.application.workflow import planner_llm_gateway as gateway


class RecordingProvider:
    provider_id = "test"
    model_name = "test"

    def __init__(self):
        self.summaries, self.requests = [], []

    async def chat_completion(self, **request):
        text = json.dumps(request["messages"], ensure_ascii=False)
        if "<message type=" in text:
            self.summaries.append(copy.deepcopy(request))
            facts = sorted(set(re.findall(r"FACT_\d+", text)))
            content = "已确认事实：" + " ".join(facts)
        else:
            self.requests.append(copy.deepcopy(request))
            content = json.dumps({"mode": "reply", "reply": "收到"}, ensure_ascii=False)
        return {"choices": [{"message": {"content": content}}], "model": "test"}

    async def stream_chat_completion(self, **request):
        self.requests.append(copy.deepcopy(request))
        yield '{"mode":"reply","reply":"收到"}'


@pytest.fixture
def model_boundary(monkeypatch):
    provider = RecordingProvider()
    manager = windows.ContextWindowManager(token_budget=18_000, recent_keep=6)
    monkeypatch.setattr(windows, "get_context_window_manager", lambda: manager)
    monkeypatch.setattr(windows.ContextWindowManager, "_record_summary_usage", lambda *_: None)
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", "512")
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "0")
    return provider, manager


def long_history(count=180):
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": (f"FACT_{index} " if index in {0, 85} else f"ROW_{index} ") + "中" * 100,
            "at": time.time(),
            "turn_id": str(index // 2),
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_count", [100, 220])
async def test_conversation_provider_uses_full_owned_history_once(
    monkeypatch, model_boundary, turn_count
):
    from app.domain.shared_services.conversation.api import ApiMixin
    from app.domain.shared_services.conversation.context import ConversationContext

    provider, _ = model_boundary
    rows = long_history(turn_count * 2)
    for index, row in enumerate(rows):
        row["content"] = f"EXACT_MESSAGE_{index:04d}"
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": rows[-400:], "summary": None})
    request_context = {
        "local_user_id": 1,
        "tenant_id": "tenant",
        "session_id": "full-transcript",
        "_chat_evidence_authorized": True,
        "_chat_history_messages": rows,
    }
    context = ConversationContext(
        user_id="scoped-user",
        conversation_history=[{"role": "assistant", "content": "STALE_LOCAL_ONLY"}],
        metadata={"request_context": request_context},
    )
    service = ApiMixin()
    service.model = "test"
    service._metadata_cache_hash = lambda _: ""
    service._build_context_prompt = lambda _: ""
    service.add_to_history = lambda *_: None

    assert (await service._call_ai("根据原文继续", context, {}))["action"] == "ai_response"
    wire = json.dumps(provider.requests[-1]["messages"], ensure_ascii=False)
    assert "STALE_LOCAL_ONLY" not in wire
    assert all(wire.count(row["content"]) == 1 for row in rows)
    assert not provider.summaries


def test_conversation_enrichment_does_not_accept_unowned_history(monkeypatch):
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": [], "summary": None})
    context = {
        "local_user_id": 1,
        "session_id": "owned",
        "_chat_history_messages": [{"role": "user", "content": "CLIENT_INJECTED_HISTORY"}],
    }
    current = {"role": "user", "content": [{"type": "text", "text": "分析图片"}]}
    result = memory.enrich_model_messages([current], "分析图片", context)
    assert result[-1] is current
    assert "CLIENT_INJECTED_HISTORY" not in json.dumps(result)


@pytest.mark.parametrize("authorized", [False, True])
@pytest.mark.parametrize("message", ["A", " A "])
def test_enrichment_excludes_current_turn_by_identity_not_equal_text(
    monkeypatch, authorized, message
):
    rows = [
        {"role": "user", "content": "A", "turn_id": "before", "at": time.time()},
        {"role": "assistant", "content": "A", "turn_id": "before", "at": time.time()},
        {"role": "user", "content": message, "turn_id": "current", "at": time.time()},
    ]
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": rows})
    context = {
        "local_user_id": 1,
        "session_id": "same",
        "turn_id": "current",
        "_chat_evidence_authorized": authorized,
        "_chat_history_messages": rows[:-1],
    }
    current = {"role": "user", "content": message}
    result = memory.enrich_model_messages([current], message, context)
    assert result[1:] == [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "A"},
        current,
    ]


@pytest.mark.asyncio
async def test_conversation_rejects_stale_history_before_cached_reply(monkeypatch, model_boundary):
    from app.domain.shared_services.conversation import api
    from app.domain.shared_services.conversation.context import ConversationContext
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    provider, _ = model_boundary
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": [], "revision": 4})
    context = ConversationContext(
        user_id="owner",
        metadata={
            "request_context": {
                "local_user_id": 1,
                "session_id": "recalled",
                "_chat_evidence_authorized": True,
                "_chat_history_source": "sql",
                "_chat_history_revision": 3,
                "_chat_history_messages": [{"role": "user", "content": "RECALLED_FACT"}],
            }
        },
    )
    service = api.ApiMixin()
    service.model = "test"
    service._metadata_cache_hash = lambda _: "cached-key"
    monkeypatch.setattr(api, "_ai_response_cache", SimpleNamespace(get=lambda _: "RECALLED_FACT"))
    with pytest.raises(ConversationRevisionError):
        await service._call_ai("继续", context, {})
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["conversation", "planner", "stream"])
@pytest.mark.parametrize("needs_summary", [False, True])
async def test_revision_change_during_budget_resolution_blocks_provider_io(
    monkeypatch, model_boundary, channel, needs_summary
):
    import asyncio

    from app.domain.shared_services.conversation.api import ApiMixin
    from app.domain.shared_services.conversation.context import ConversationContext
    from app.domain.shared_services.conversation_service import ConversationRevisionError
    from app.infrastructure.llm import model_context_windows

    provider, _ = model_boundary
    stored = {"turns": [], "revision": 3}
    monkeypatch.setattr(memory, "_read", lambda *_: stored)
    request_context = {
        "local_user_id": 1,
        "session_id": "recalled-during-await",
        "_chat_history_source": "sql",
        "_chat_history_revision": 3,
    }

    async def resolve_model(*_):
        stored["revision"] = 4
        return "test"

    monkeypatch.setattr(model_context_windows, "model_for_budget", resolve_model)
    messages = [*(long_history() if needs_summary else []), {"role": "user", "content": "continue"}]
    with pytest.raises(ConversationRevisionError):
        if channel == "conversation":
            service = ApiMixin()
            context = ConversationContext(
                user_id="owner", metadata={"request_context": request_context}
            )
            await service.call_llm_api(messages, conversation_context=context)
        elif channel == "planner":
            await asyncio.to_thread(
                gateway.request_planner_completion,
                ai_service=None,
                context=request_context,
                messages=messages,
            )
        else:
            _ = [
                part
                async for part in gateway.stream_planner_completion(
                    ai_service=None, context=request_context, messages=messages
                )
            ]
    assert not provider.requests and not provider.summaries


@pytest.mark.asyncio
async def test_revision_change_between_summary_batches_stops_further_model_io(
    monkeypatch, model_boundary
):
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    provider, _ = model_boundary
    monkeypatch.setattr(
        windows,
        "get_context_window_manager",
        lambda: windows.ContextWindowManager(token_budget=3000),
    )
    stored = {"turns": [], "revision": 3}
    monkeypatch.setattr(memory, "_read", lambda *_: stored)
    complete = provider.chat_completion

    async def revoke_after_summary(**request):
        result = await complete(**request)
        stored["revision"] = 4
        return result

    monkeypatch.setattr(provider, "chat_completion", revoke_after_summary)
    context = {
        "local_user_id": 1,
        "session_id": "recalled-between-batches",
        "_chat_history_source": "sql",
        "_chat_history_revision": 3,
    }
    with pytest.raises(ConversationRevisionError):
        await gateway._prepare_model_messages(
            provider, context, [*long_history(), {"role": "user", "content": "continue"}], 500, {}
        )
    assert len(provider.summaries) == 1 and not provider.requests
    assert stored.get("summary") is None


def test_batch_attachment_import_fits_default_budget_with_every_file(monkeypatch, model_boundary):
    provider, _ = model_boundary
    monkeypatch.setattr(windows, "get_context_window_manager", windows.ContextWindowManager)
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", "4096")
    files = [{"id": str(i), "name": f"表格{i}.xlsx", "suffix": ".xlsx"} for i in range(22)]
    context = {
        "artifact_ids": [file["id"] for file in files],
        "file_context": {"attachment_manifest": files},
        "available_employees": ["员工介绍" * 50] * 80,
    }
    registry = {
        "elt_import": {"actions": {"preview": {}, "execute": {}}},
        "unrelated": {"description": "业务说明" * 8000, "actions": {"query": {}}},
    }
    planner = generation.LlmPlanGeneration(
        SimpleNamespace(get_context=lambda _: None),
        gateway.request_planner_completion,
        lambda: None,
    )
    assert planner.generate("p", "1", "导入", registry, context) is not None
    prompt = json.loads(provider.requests[-1]["messages"][-1]["content"])
    assert [tool["tool_id"] for tool in prompt["tool_registry"]] == ["elt_import"]
    actions = prompt["tool_registry"][0]["actions"]
    assert [item["action"] for item in actions] == ["execute"]
    assert "file_paths" in actions[0]["input_schema"]["properties"]
    assert prompt["context"] == {
        "file_context": {"attachment_manifest": [file["name"] for file in files]}
    }


@pytest.mark.parametrize("field", ["file_context", "file_analysis"])
def test_short_attachment_followup_preserves_evidence_in_real_provider_request(
    model_boundary, field
):
    provider, _ = model_boundary
    evidence = {"attachment_evidence": "attachment-data " * 900 + "ATTACHMENT_FINAL_FACT"}
    planner = generation.LlmPlanGeneration(
        SimpleNamespace(get_context=lambda _: None),
        gateway.request_planner_completion,
        lambda: None,
    )
    context = {"memory_v2": "prior context " * 2200, field: evidence}
    assert planner.generate("p", "1", "这个呢", {}, context) is not None
    prompt = json.loads(provider.requests[-1]["messages"][-1]["content"])
    assert prompt["context"][field] == evidence


@pytest.mark.parametrize("tier", ["light", "full"])
def test_generate_sends_middle_fact_and_reuses_persisted_summary(monkeypatch, model_boundary, tier):
    provider, manager = model_boundary
    data = {"turns": long_history(), "summary": None}
    monkeypatch.setattr(memory, "_read", lambda key, context=None: data)
    monkeypatch.setattr(memory, "_write", lambda key, value: data.update(value))
    monkeypatch.setattr(generation, "_conversational_turn", lambda *_: tier == "light")
    context = {"local_user_id": 1, "session_id": "same", "tenant_id": "tenant"}
    planner = generation.LlmPlanGeneration(
        SimpleNamespace(get_context=lambda _: None),
        gateway.request_planner_completion,
        lambda: None,
    )
    plan = planner.generate("p", "1", "你好" if tier == "light" else "查询客户", {}, context)
    assert plan is not None and provider.requests
    request = provider.requests[-1]
    wire = json.dumps(request["messages"], ensure_ascii=False)
    assert "FACT_0" in wire and "FACT_85" in wire
    prompt = json.loads(request["messages"][-1]["content"])
    assert "conversation_history" not in prompt and "recent_messages" not in prompt
    assert not {"chat_owned_history", "recent_messages", "chat_history_summary"} & set(
        prompt.get("context", {})
    )
    assert (
        windows.estimate_messages_tokens(request["messages"]) + request["max_tokens"]
        <= manager.token_budget
    )
    assert data["summary"]["kind"] == "langchain"
    assert 0 < data["summary"]["count"] < len(data["turns"])
    summary_source = "\n".join(
        json.dumps(item["messages"], ensure_ascii=False) for item in provider.summaries
    )
    for row in data["turns"][: data["summary"]["count"]]:
        assert row["content"].split()[0] in summary_source
    paid_summaries = len(provider.summaries)
    # A new request context simulates losing all process-local compression state.
    fresh = {key: value for key, value in context.items() if not key.startswith("_")}
    assert planner.generate("p2", "1", "继续", {}, fresh) is not None
    assert len(provider.summaries) == paid_summaries
    assert "FACT_85" in json.dumps(provider.requests[-1]["messages"], ensure_ascii=False)


@pytest.mark.parametrize("count", [60, 120, 121, 240])
def test_old_excerpt_cache_never_discards_unsummarized_middle_or_120_boundary(count):
    rows = long_history(count)
    rows[count // 2]["content"] = "MIDDLE_ORIGINAL_FACT"
    legacy = {
        "text": "only the start",
        "count": count - 12,
        "fingerprint": memory._turns_fingerprint(rows[:-12]),
    }
    messages = memory._model_messages({"turns": rows, "summary": legacy}, "")
    assert "MIDDLE_ORIGINAL_FACT" in json.dumps(messages)
    assert len(messages) == count + 1
    assert memory._build_summary(rows, legacy) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_both_gateways_reserve_tool_schema_and_preserve_complete_latest_turn(
    monkeypatch, model_boundary, streaming
):
    provider, _ = model_boundary
    manager = windows.ContextWindowManager(token_budget=3000, recent_keep=2)
    monkeypatch.setattr(windows, "get_context_window_manager", lambda: manager)
    latest = [
        {"role": "user", "content": "完整当前请求"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"key":1}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "完整工具结果"},
    ]
    tools = [{"type": "function", "function": {"name": "read", "description": "工具说明" * 40}}]
    messages = [{"role": "user", "content": "旧" * 100} for _ in range(30)] + latest
    if streaming:
        stream = gateway.stream_planner_completion(
            ai_service=None, context={}, messages=messages, tools=tools, max_tokens=300
        )
        assert [part async for part in stream]
    else:
        # The sync boundary deliberately owns its own event loop.
        import asyncio

        assert await asyncio.to_thread(
            gateway.request_planner_completion,
            ai_service=None,
            context={},
            messages=messages,
            tools=tools,
            max_tokens=300,
        )
    request = provider.requests[-1]
    assert request["messages"][-3:] == latest
    assert request["tools"] == tools
    schemas = windows.estimate_messages_tokens(
        [{"role": "system", "content": json.dumps({"tools": tools}, ensure_ascii=False)}]
    )
    assert (
        windows.estimate_messages_tokens(request["messages"]) + 300 + schemas
        <= manager.token_budget
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_oversized_latest_turn_or_schema_never_reaches_provider(
    monkeypatch, model_boundary, streaming
):
    provider, _ = model_boundary
    monkeypatch.setattr(
        windows,
        "get_context_window_manager",
        lambda: windows.ContextWindowManager(token_budget=500),
    )
    messages = [{"role": "user", "content": "完整当前请求"}]
    tools = [{"type": "function", "function": {"name": "read", "description": "中" * 1000}}]
    with pytest.raises(windows.ContextWindowExceeded):
        if streaming:
            stream = gateway.stream_planner_completion(
                ai_service=None, context={}, messages=messages, tools=tools, max_tokens=100
            )
            _ = [part async for part in stream]
        else:
            import asyncio

            await asyncio.to_thread(
                gateway.request_planner_completion,
                ai_service=None,
                context={},
                messages=messages,
                tools=tools,
                max_tokens=100,
            )
    assert not provider.requests and not provider.summaries


def test_sql_projection_reads_only_uncovered_suffix_and_keeps_whole_long_messages(monkeypatch):
    from app.application import task_conversation_store
    from app.application.ai_chat import chat_evidence

    monkeypatch.setattr(
        task_conversation_store, "ConversationRevisionError", ValueError, raising=False
    )
    saved = {
        "kind": "langchain",
        "source": "sql",
        "revision": 3,
        "covered_through_id": 80,
        "count": 80,
        "text": "FACT_0",
    }
    monkeypatch.setattr(memory, "conversation_summary", lambda _: saved)
    calls = []

    def page(**request):
        calls.append(request)
        first = request["after_id"] == 80
        return {
            "session": {"revision": 3},
            "snapshot_latest_id": 84,
            "has_more": first,
            "next_after_id": 82 if first else None,
            "messages": [
                {"id": value, "role": "user" if value % 2 else "assistant", "content": "长" * 4000}
                for value in ([81, 82] if first else [83, 84])
            ],
        }

    result = chat_evidence._prepare_history(SimpleNamespace(get_conversation=page), {}, "s", 1)
    assert calls[0]["after_id"] == 80 and calls[1]["through_id"] == 84
    assert result["_chat_history_ids"] == [None, 81, 82, 83, 84]
    assert all("长" * 4000 in row["content"] for row in result["_chat_history_messages"][1:])
    assert result["_chat_history_messages"][0]["content"].endswith("FACT_0")


def test_later_finishing_old_summary_cannot_move_sql_cursor_backwards(monkeypatch):
    from contextlib import nullcontext

    previous = {
        "kind": "langchain",
        "source": "sql",
        "revision": 3,
        "covered_through_id": 90,
        "count": 90,
        "text": "newer",
    }
    data = {"revision": 3, "summary": previous}
    writes = []
    monkeypatch.setattr(memory, "_read", lambda *_: data)
    monkeypatch.setattr(memory, "_write", lambda *args: writes.append(args))
    monkeypatch.setattr(memory, "_lock", lambda _: nullcontext())
    context = {
        "local_user_id": 1,
        "session_id": "same",
        "_chat_history_source": "sql",
        "_chat_history_revision": 3,
        "_chat_history_ids": [None, 81, 82],
        "_chat_history_prior_summary": {"count": 80, "covered_through_id": 80},
    }
    history = [{"role": "user", "content": str(index)} for index in range(3)]
    memory.save_conversation_summary(context, history, 3, "older computation finished later")
    assert not writes and data["summary"] is previous


def test_light_history_readback_falls_through_to_full_workflow(monkeypatch, model_boundary):
    provider, _ = model_boundary
    monkeypatch.setattr(generation, "_conversational_turn", lambda *_: True)

    async def complete(**request):
        provider.requests.append(request)
        payload = {"mode": "workflow"}
        if len(provider.requests) == 2:
            payload.update(
                intent="history",
                nodes=[
                    {
                        "node_id": "read",
                        "tool_id": "conversation_history",
                        "action": "read",
                        "params": {"message_id": 81},
                        "risk": "low",
                        "idempotent": True,
                    }
                ],
            )
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    monkeypatch.setattr(provider, "chat_completion", complete)
    planner = generation.LlmPlanGeneration(
        SimpleNamespace(get_context=lambda _: None),
        gateway.request_planner_completion,
        lambda: None,
    )
    registry = {
        "conversation_history": {
            "description": "读取当前会话原文",
            "actions": {"read": {"risk": "low", "idempotent": True}},
        }
    }
    plan = planner.generate("p", "1", "回看原文消息81", registry, {})
    assert plan and [(node.tool_id, node.action) for node in plan.nodes] == [
        ("conversation_history", "read")
    ]
    assert len(provider.requests) == 2
    full_prompt = json.loads(provider.requests[-1]["messages"][-1]["content"])
    assert full_prompt["tool_registry"][0]["tool_id"] == "conversation_history"


@pytest.mark.parametrize("model_available", [False, True])
@pytest.mark.parametrize("node_count", [1, 2])
def test_history_workflow_result_feeds_whole_evidence_back_and_shows_exact_excerpts(
    monkeypatch, model_boundary, model_available, node_count
):
    from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin

    provider, _ = model_boundary
    rows = [
        {
            "id": 100 + index,
            "role": "user",
            "content": "原" * 900 + f"END_{index}",
            "offset": 400,
            "total_chars": 3000,
            "next_offset": 1305,
            "content_complete": False,
        }
        for index in range(6)
    ]
    node = SimpleNamespace(node_id="read", tool_id="conversation_history", action="read", params={})
    plan = SimpleNamespace(intent="history", plan_id="p", nodes=[node], todo_steps=[], metadata={})
    step = SimpleNamespace(
        **vars(node),
        status="completed",
        duration_ms=1,
        output={"success": True, "message": "已读取", "data": {"messages": rows, "has_more": True}},
    )
    run = SimpleNamespace(
        status="completed", run_id="r", steps=[step], metadata={}, artifacts=[], tool_calls=[]
    )
    if node_count == 2:
        second = copy.deepcopy(step)
        second.node_id = "next-page"
        step.output["data"]["messages"] = rows[:3]
        second.output["data"]["messages"] = rows[3:]
        run.steps.append(second)
    builder = AIChatWorkflowResponseMixin()
    if model_available:
        builder.workflow_planner = SimpleNamespace(
            complete_messages=lambda **kwargs: gateway.request_planner_completion(
                ai_service=None, **kwargs
            )
        )
    result = builder._format_agent_run_response(plan, run, user_message="第六段的最后一句是什么？")
    response = result["response"]
    assert all(row["content"] in response and f"#{row['id']}" in response for row in rows)
    assert "本次为历史片段" in response and "尚未读完" in response
    if model_available:
        wire = json.dumps(provider.requests[-1]["messages"], ensure_ascii=False)
        assert "END_0" in wire and "END_5" in wire and "#105" in wire
    else:
        assert not provider.requests
