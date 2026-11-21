"""Capture real planner provider IO without a paid model or external storage."""

import asyncio
import copy
import json
import re
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
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

    original_resolve = model_context_windows.resolve_model_limits

    async def resolve_model(*args, **kwargs):
        stored["revision"] = 4
        return await original_resolve(*args, **kwargs)

    monkeypatch.setattr(model_context_windows, "resolve_model_limits", resolve_model)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_platform_alias_full_catalog_reaches_original_provider(monkeypatch, streaming):
    """The reported greeting must fit without deleting any registered contract."""
    from app.application.facades.tools_facade import get_workflow_tool_registry
    from app.application.workflow.tool_calling import plan_function_tools

    registry = get_workflow_tool_registry()
    original = generation._tool_specs(registry)
    prompt = {
        "user_message": "你好，请只回复收到",
        "rules": list(generation.BASE_RULES),
        "conversation_history": [],
        "tool_registry": original,
    }
    messages = [
        {"role": "system", "content": "根据用户输入回复或规划，只输出约定 JSON。"},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    assert windows.estimate_messages_tokens(messages) > 8192
    provider = RecordingProvider()
    provider.provider_id = "modstore"
    provider._adapter = SimpleNamespace(
        resolve_chat_route=AsyncMock(return_value=("litellm", "xcmax-doubao-code")),
        resolve_model_capabilities=AsyncMock(
            return_value={
                "context_window": 65536,
                "max_output_tokens": 8192,
                "resolved_model": "doubao/verified-test-deployment",
                "source": "litellm_model_info",
            }
        ),
    )
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    extra = {"tools": plan_function_tools(), "tool_choice": "auto"}
    monkeypatch.setattr(
        windows,
        "get_context_window_manager",
        lambda: windows.ContextWindowManager(token_budget=8192),
    )
    with pytest.raises(windows.ContextWindowExceeded):
        await gateway._prepare_model_messages(provider, {}, messages, 4096, extra)
    assert not provider.requests and not provider.summaries

    monkeypatch.setattr(windows, "get_context_window_manager", windows.ContextWindowManager)
    context = {}
    if streaming:
        stream = gateway.stream_planner_completion(
            ai_service=None, context=context, messages=messages, max_tokens=4096, **extra
        )
        assert [part async for part in stream]
    else:
        result = await asyncio.to_thread(
            gateway.request_planner_completion,
            ai_service=None,
            context=context,
            messages=messages,
            max_tokens=4096,
            **extra,
        )
        assert json.loads(result["choices"][0]["message"]["content"])["reply"] == "收到"
    assert len(provider.requests) == 1 and not provider.summaries
    sent = provider.requests[0]
    rebuilt = json.loads(sent["messages"][-1]["content"])
    for tool in rebuilt["tool_registry"]:
        for action in tool["actions"]:
            for key in ("input_schema", "output_schema"):
                reference = action.pop(f"{key}_ref", None)
                if reference is not None:
                    action[key] = rebuilt["tool_schemas"][reference]
            action.setdefault("description", tool["description"])
    assert rebuilt["tool_registry"] == original
    assert rebuilt["user_message"] == prompt["user_message"]
    assert sent["tools"] == extra["tools"] and sent["max_tokens"] == 4096
    assert context["_context_budget"]["capability_source"] == "litellm_model_info"
    assert context["_context_budget"]["context_window"] == 65536
    assert sent.get("model") != "doubao/verified-test-deployment"


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("vision_window", [None, 4000, 65536])
async def test_scoped_sdk_budgets_and_calls_the_same_selected_route(
    monkeypatch, streaming, vision_window
):
    from app.application.facades.tools_facade import get_workflow_tool_registry
    from app.domain.shared_services.conversation import modstore_adapter as facade
    from app.infrastructure.llm.client import llm_client_factory_scope
    from app.infrastructure.llm.providers import registry

    requests, operations = [], []

    def respond(request):
        assert request.headers["authorization"] == "Bearer synthetic-budget-owner"
        if request.url.path == "/api/llm/resolve-chat-default":
            operation = request.url.params.get("operation", "chat")
            operations.append(operation)
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "provider": "litellm",
                    "model": "vision-alias" if operation == "vision" else "xcmax-doubao-code",
                    "operation": operation,
                    "route_source": "platform_gateway",
                    "key_source": "platform",
                    "route_token": f"synthetic-{operation}-route",
                    "config_revision": "budget-fixture-v1",
                    "model_capabilities": {
                        "context_window": vision_window if operation == "vision" else 65536,
                        "source": "litellm_model_info",
                    },
                },
            )
        assert request.url.path == "/api/llm/chat/stream"
        requests.append(json.loads(request.content))
        return httpx.Response(200, text='data: {"delta":"收到"}\n\ndata: [DONE]\n\n')

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(**(kwargs | {"transport": httpx.MockTransport(respond)})),
    )
    monkeypatch.setattr(registry, "_maybe_instrument", lambda provider: provider)
    monkeypatch.setattr(windows, "get_context_window_manager", windows.ContextWindowManager)
    adapter = facade.ModstorePlatformAdapter(
        platform_url="https://market.invalid", auth_token="synthetic-budget-owner"
    )
    adapter._use_account_default = True
    prompt = json.dumps(
        {
            "user_message": "你好，请只回复收到",
            "tool_registry": generation._tool_specs(get_workflow_tool_registry()),
        },
        ensure_ascii=False,
    )
    content = (
        [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "https://image.invalid/fixture.png"}},
        ]
        if vision_window is not None
        else prompt
    )
    messages = [{"role": "user", "content": content}]
    context = {}

    async def invoke():
        if streaming:
            return "".join(
                [
                    part
                    async for part in gateway.stream_planner_completion(
                        ai_service=None, context=context, messages=messages, max_tokens=512
                    )
                ]
            )
        result = await asyncio.to_thread(
            gateway.request_planner_completion,
            ai_service=None,
            context=context,
            messages=messages,
            max_tokens=512,
        )
        return result["choices"][0]["message"]["content"]

    with llm_client_factory_scope(lambda: facade.ModstoreOpenAICompatibleClient(adapter)):
        if vision_window == 4000:
            with pytest.raises(windows.ContextWindowExceeded):
                await invoke()
            assert not requests
        else:
            assert await invoke() == "收到"
            assert len(requests) == 1
            sent = requests[0]
            assert sent["provider"] == "litellm"
            assert sent["model"] == (
                "vision-alias" if vision_window is not None else "xcmax-doubao-code"
            )
            assert "_prepared_chat_route" not in sent
            assert sent["allow_failover"] is False
            if vision_window is not None:
                assert sent["messages"] == messages
    assert context["_context_budget"]["context_window"] == (vision_window or 65536)
    assert operations.count("vision") == (1 if vision_window is not None else 0)
    assert adapter.resolve_default_route() == ("litellm", "xcmax-doubao-code")


@pytest.mark.asyncio
async def test_unknown_alias_still_reports_missing_capability_without_paid_retry(monkeypatch):
    provider = RecordingProvider()
    provider.provider_id = "modstore"
    provider._adapter = SimpleNamespace(
        resolve_chat_route=AsyncMock(return_value=("litellm", "unregistered-alias")),
        resolve_model_capabilities=AsyncMock(return_value={}),
    )
    messages = [
        {"role": "system", "content": "必要工具约束" * 5000},
        {"role": "user", "content": "你好，请只回复收到"},
    ]
    context = {}
    with pytest.raises(windows.ContextWindowExceeded):
        await gateway._prepare_model_messages(provider, context, messages, 4096, {})
    assert context["_context_budget"]["capability_source"] == "catalog:default"
    assert not provider.requests and not provider.summaries


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("requested,expected", [(None, 2048), (1024, 1024), (4096, None)])
async def test_planner_default_output_fits_selected_model_without_changing_explicit_requests(
    monkeypatch, streaming, requested, expected
):
    provider = RecordingProvider()
    provider.model_info = {"context_window": 32768, "max_output_tokens": 2048}
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", "4096")
    monkeypatch.setattr(windows, "get_context_window_manager", windows.ContextWindowManager)
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    context = {}
    kwargs = {
        "ai_service": None,
        "context": context,
        "messages": [{"role": "user", "content": "你好，请只回复收到"}],
        "max_tokens": requested,
    }

    async def invoke():
        if streaming:
            return [chunk async for chunk in gateway.stream_planner_completion(**kwargs)]
        return await asyncio.to_thread(gateway.request_planner_completion, **kwargs)

    if expected is None:
        with pytest.raises(windows.ContextWindowExceeded) as error:
            await invoke()
        assert error.value.reason == "model_output_limit_exceeded"
        assert not provider.requests and not provider.summaries
    else:
        assert await invoke()
        assert len(provider.requests) == 1
        assert provider.requests[0]["max_tokens"] == expected
        assert context["_context_budget"]["requested_output_tokens"] == expected
        assert not provider.summaries


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_account_change_during_summary_stops_the_original_primary_call(
    monkeypatch, streaming
):
    from app.infrastructure.modstore_transport import MarketModelError

    provider = RecordingProvider()
    provider.provider_id = "modstore"
    identity = ["original-account"]
    provider._adapter = SimpleNamespace(
        _connection=lambda: identity[0],
        resolve_chat_route=AsyncMock(return_value=("litellm", "shared-alias")),
        resolve_model_capabilities=AsyncMock(return_value={"context_window": 4000}),
    )
    original_complete = provider.chat_completion

    async def change_account(**request):
        result = await original_complete(**request)
        assert provider.summaries and not provider.requests
        identity[0] = "different-account"
        return result

    monkeypatch.setattr(provider, "chat_completion", change_account)
    monkeypatch.setattr(windows.ContextWindowManager, "_record_summary_usage", lambda *_: None)
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    messages = [
        {"role": "system", "content": "保留原任务"},
        *[{"role": "user", "content": "历史事实" * 100} for _ in range(16)],
        {"role": "user", "content": "继续原任务"},
    ]
    with pytest.raises(MarketModelError) as error:
        if streaming:
            stream = gateway.stream_planner_completion(
                ai_service=None, context={}, messages=messages, max_tokens=512
            )
            _ = [chunk async for chunk in stream]
        else:
            await asyncio.to_thread(
                gateway.request_planner_completion,
                ai_service=None,
                context={},
                messages=messages,
                max_tokens=512,
            )
    assert error.value.status_code == 409
    assert len(provider.summaries) == 1 and not provider.requests


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
