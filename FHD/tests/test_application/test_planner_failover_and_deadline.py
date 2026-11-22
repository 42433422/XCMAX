"""Capture real planner provider IO without a paid model or external storage."""

import asyncio
import copy
import json
import re
import threading
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



@pytest.fixture
def platform_failover(monkeypatch):
    from app.application.workflow.retry_policy import planning_model_call, planning_request_scope
    from app.domain.shared_services.conversation import modstore_adapter as facade
    from app.infrastructure.llm.client import llm_client_factory_scope
    from app.infrastructure.llm.providers import registry

    state = SimpleNamespace(
        posts=[],
        gets=[],
        context={},
        primary_status=429,
        backup_status=200,
        primary_source="platform_gateway",
        primary_key="platform",
        backup_key="platform",
        backup_window=8192,
        backup_output=512,
        change_account=False,
        body=None,
    )

    def respond(request):
        assert request.headers["authorization"] == "Bearer synthetic-budget-owner"
        if request.method == "GET":
            state.gets.append((request.url.path, dict(request.url.params)))
            if request.url.path.endswith("/status"):
                return httpx.Response(
                    200, json={"providers": [{"provider": "litellm", "has_platform_key": True}]}
                )
            if request.url.path.endswith("/catalog"):
                return httpx.Response(
                    200,
                    json={
                        "providers": [
                            {
                                "provider": "litellm",
                                "runtime_models": ["primary", "backup", "unused"],
                            }
                        ]
                    },
                )
            assert request.url.path.endswith("/resolve-chat-default")
            model = request.url.params.get("model", "primary")
            primary = model == "primary"
            if not primary and state.change_account:
                state.adapter.auth_token = "synthetic-different-account"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "provider": "litellm",
                    "model": model,
                    "route_source": state.primary_source if primary else "explicit",
                    "key_source": state.primary_key if primary else state.backup_key,
                    "route_token": f"synthetic-{model}-pin",
                    "config_revision": f"{model}-r1",
                    "model_capabilities": {
                        "context_window": 32768 if primary else state.backup_window,
                        "max_output_tokens": 4096 if primary else state.backup_output,
                    },
                },
            )
        payload = json.loads(request.content)
        state.posts.append(payload)
        if state.body is not None:
            return httpx.Response(200, stream=state.body)
        status = state.primary_status if payload["model"] == "primary" else state.backup_status
        if status >= 400:
            return httpx.Response(status, json={"error": "synthetic rate limited"})
        return httpx.Response(200, text='data: {"delta":"收到"}\n\ndata: [DONE]\n\n')

    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "1")
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER_MAX", "2")
    monkeypatch.setenv("XCAGI_PLANNER_MAX_TOKENS", "4096")
    monkeypatch.setattr(facade, "_CATALOG_CACHE", {})
    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(**(kwargs | {"transport": httpx.MockTransport(respond)})),
    )
    monkeypatch.setattr(registry, "_maybe_instrument", lambda provider: provider)
    monkeypatch.setattr(windows, "get_context_window_manager", windows.ContextWindowManager)
    state.adapter = facade.ModstorePlatformAdapter(
        platform_url="https://market.invalid", auth_token="synthetic-budget-owner"
    )
    state.adapter._use_account_default = True

    async def invoke(streaming, **kwargs):
        request = {
            "ai_service": None,
            "context": state.context,
            "messages": [{"role": "user", "content": "你好，请只回复收到"}],
            "client_request_id": "synthetic-plan",
            **kwargs,
        }
        with (
            llm_client_factory_scope(lambda: facade.ModstoreOpenAICompatibleClient(state.adapter)),
            planning_request_scope(state.context),
            planning_model_call(),
        ):
            if streaming:
                return "".join(
                    [part async for part in gateway.stream_planner_completion(**request)]
                )
            result = await asyncio.to_thread(gateway.request_planner_completion, **request)
            return result["choices"][0]["message"]["content"]

    state.invoke = invoke
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_planner_failover_resolves_and_rebudgets_same_gateway_alias(
    platform_failover, streaming
):
    state = platform_failover
    assert await state.invoke(streaming) == "收到"
    assert [row["model"] for row in state.posts] == ["primary", "backup"]
    assert [row["max_tokens"] for row in state.posts] == [4096, 512]
    assert [row["client_request_id"] for row in state.posts] == [
        "synthetic-plan",
        "synthetic-plan-f1",
    ]
    assert all(row["allow_failover"] is False for row in state.posts)
    assert [row["route_token"] for row in state.posts] == [
        "synthetic-primary-pin",
        "synthetic-backup-pin",
    ]
    assert [row["config_revision"] for row in state.posts] == ["primary-r1", "backup-r1"]
    assert state.adapter.resolve_default_route() == ("litellm", "primary")
    assert state.context["_context_budget"]["context_window"] == 8192
    assert state.context["planning_diagnostics"]["model_attempts"] == 2
    assert state.context["planning_diagnostics"]["model_failovers"] == [
        {"from_model": "litellm/primary", "to_model": "litellm/backup", "status": 429}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "policy", ["explicit", "environment", "byok", "preference", "audit", "401", "402", "403"]
)
async def test_planner_failover_preserves_authorization_and_explicit_route_policy(
    monkeypatch, platform_failover, streaming, policy
):
    from app.infrastructure.modstore_transport import MarketModelError

    state = platform_failover
    kwargs = {}
    if policy == "explicit":
        kwargs["allow_failover"] = False
    elif policy == "environment":
        monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "0")
    elif policy == "byok":
        state.primary_key = "user_override"
    elif policy == "preference":
        state.primary_source = "preference"
    elif policy == "audit":
        kwargs["_reviewed_excel_audit_response"] = lambda *args: None
    else:
        state.primary_status = int(policy)
    with pytest.raises(MarketModelError):
        await state.invoke(streaming, **kwargs)
    assert len(state.posts) == 1
    assert not any(path.endswith("/status") for path, params in state.gets)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("failure", ["byok", "account", "output", "context", "exhausted"])
async def test_planner_revalidates_alternate_before_call_and_preserves_terminal_failure(
    platform_failover, streaming, failure
):
    from app.infrastructure.modstore_transport import MarketModelError

    state, kwargs = platform_failover, {}
    if failure == "byok":
        state.backup_key = "user_override"
    elif failure == "account":
        state.change_account = True
    elif failure == "output":
        kwargs["max_tokens"] = 1024
    elif failure == "context":
        state.backup_window = 256
    else:
        state.backup_status = 429
    with pytest.raises((MarketModelError, windows.ContextWindowExceeded)):
        await state.invoke(streaming, **kwargs)
    assert len(state.posts) == (2 if failure == "exhausted" else 1)
    assert state.context["planning_diagnostics"]["model_attempts"] == (
        1 if failure in {"byok", "account"} else 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_exhausted_call_budget_blocks_alternate_preparation(
    monkeypatch, platform_failover, streaming
):
    from app.application.workflow.retry_policy import PlanningBudgetExceeded

    monkeypatch.setenv("XCAGI_PLAN_MAX_MODEL_CALLS", "1")
    prepare = gateway._prepare_model_messages
    prepared_models = []

    async def observed(*args, **kwargs):
        prepared_models.append(kwargs["model_limits"].model)
        return await prepare(*args, **kwargs)

    monkeypatch.setattr(gateway, "_prepare_model_messages", observed)
    with pytest.raises(PlanningBudgetExceeded):
        await platform_failover.invoke(streaming)
    assert prepared_models == ["litellm/primary"]
    assert len(platform_failover.posts) == 1
    assert platform_failover.context["planning_diagnostics"]["exhausted"] == "model_call_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_planner_deadline_cancels_provider_and_closes_stream(monkeypatch, streaming):
    from app.application.tool_execution_deadline import invocation_deadline
    from app.application.workflow.retry_policy import PlanningBudgetExceeded

    closed = []

    class SlowProvider(RecordingProvider):
        async def chat_completion(self, **request):
            try:
                await asyncio.Event().wait()
            finally:
                closed.append("complete")

        async def stream_chat_completion(self, **request):
            try:
                yield "partial"
                await asyncio.Event().wait()
            finally:
                closed.append("stream")

    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: SlowProvider()
    )
    with invocation_deadline(time.monotonic() + 0.05), pytest.raises(PlanningBudgetExceeded):
        kwargs = {
            "ai_service": None,
            "context": {},
            "messages": [{"role": "user", "content": "hi"}],
        }
        if streaming:
            _ = [chunk async for chunk in gateway.stream_planner_completion(**kwargs)]
        else:
            await asyncio.to_thread(gateway.request_planner_completion, **kwargs)
    assert closed == ["stream" if streaming else "complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_planner_deadline_closes_sync_sdk_http_read_in_worker(platform_failover, streaming):
    from app.application.tool_execution_deadline import invocation_deadline
    from app.application.workflow.retry_policy import PlanningBudgetExceeded

    released = threading.Event()

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            if released.wait(1.0):
                raise httpx.ReadError("closed by owner")
            yield b'data: {"delta":"late"}\n\n'

        def close(self):
            released.set()

    platform_failover.body = Body()
    started = time.monotonic()
    with invocation_deadline(started + 0.05), pytest.raises(PlanningBudgetExceeded):
        await platform_failover.invoke(streaming)
    assert released.is_set()
    assert time.monotonic() - started < 0.75
    assert len(platform_failover.posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_summary_save_revision_conflict_propagates_before_planner_call(
    monkeypatch, model_boundary, streaming
):
    from contextlib import nullcontext

    from app.domain.shared_services.conversation_service import ConversationRevisionError

    provider, _ = model_boundary
    history = long_history()
    data = {"turns": history, "summary": None, "revision": 3}
    writes = []
    monkeypatch.setattr(memory, "_read", lambda *_: data)
    monkeypatch.setattr(memory, "_write", lambda *args: writes.append(args))
    monkeypatch.setattr(memory, "_lock", lambda _: nullcontext())
    original = provider.chat_completion

    async def revoke_during_summary(**request):
        result = await original(**request)
        assert provider.summaries and not provider.requests
        data["revision"] = 4
        return result

    monkeypatch.setattr(provider, "chat_completion", revoke_during_summary)
    context = {
        "local_user_id": 1,
        "session_id": "same",
        "_chat_history_source": "sql",
        "_chat_history_revision": 3,
        "_chat_history_ids": list(range(1, len(history) + 1)),
    }
    kwargs = {
        "ai_service": None,
        "context": context,
        "max_tokens": 512,
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": "继续原任务",
                        "conversation_history": history,
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    }
    with pytest.raises(ConversationRevisionError, match="摘要生成期间会话已变更"):
        if streaming:
            _ = [part async for part in gateway.stream_planner_completion(**kwargs)]
        else:
            await asyncio.to_thread(gateway.request_planner_completion, **kwargs)
    assert provider.summaries and not provider.requests
    assert not writes and data["summary"] is None


@pytest.fixture
def native_sdk_planner(monkeypatch):
    from openai import OpenAI

    from app.application.workflow.model_response_metrics import observe_model_response
    from app.application.workflow.retry_policy import planning_model_call, planning_request_scope
    from app.infrastructure.llm import client
    from app.infrastructure.llm.providers import openai_sdk_provider as sdk

    state = SimpleNamespace(posts=[], statuses=[], body=None, before_response=None, workers=[])
    content = {"choices": [{"message": {"content": "{}"}}], "model": "fixture"}

    def dispatch(request):
        state.posts.append(request)
        if state.before_response:
            state.before_response()
        status = state.statuses.pop(0) if state.statuses else 200
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "limited"}})
        if state.body is not None:
            return httpx.Response(200, stream=state.body)
        if json.loads(request.content).get("stream"):
            return httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n'
            )
        return httpx.Response(200, json=content)

    http_client = httpx.Client(transport=httpx.MockTransport(dispatch))
    state.client = OpenAI(
        api_key="fixture",
        base_url="https://sdk.test/v1",
        http_client=http_client,
        timeout=httpx.Timeout(120, connect=0.01, pool=None),
        max_retries=2,
    )
    # Resolve lazy SDK resources before a deliberately short request deadline.
    _ = state.client.chat.completions.with_streaming_response
    monkeypatch.setattr(OpenAI, "_sleep_for_retry", lambda *args, **kwargs: None)
    monkeypatch.setattr(client, "get_llm_client", lambda: state.client)
    monkeypatch.setattr(client, "require_api_key", lambda: None)
    provider = sdk.OpenAISdkProvider()
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    limits = SimpleNamespace(
        model="fixture",
        request_options={"model": "fixture"},
        default_output_tokens=lambda value: value,
        assert_current=lambda: None,
    )
    monkeypatch.setattr(
        "app.infrastructure.llm.model_context_windows.resolve_model_limits",
        AsyncMock(return_value=limits),
    )
    monkeypatch.setattr(gateway, "_prepare_model_messages", AsyncMock(return_value=[]))
    original_worker = sdk.StreamWorker

    def track_worker(*args, **kwargs):
        worker = original_worker(*args, **kwargs)
        state.workers.append(worker)
        return worker

    monkeypatch.setattr(sdk, "StreamWorker", track_worker)
    state.context, state.chunks, state.provider = {}, [], provider

    def invoke(streaming):
        kwargs = {"ai_service": None, "context": state.context, "messages": []}
        with planning_request_scope(state.context):
            if not streaming:
                return observe_model_response(gateway.request_planner_completion)(**kwargs)

            async def consume():
                with planning_model_call():
                    async for chunk in gateway.stream_planner_completion(**kwargs):
                        state.chunks.append(chunk)

            return asyncio.run(consume())

    state.invoke = invoke
    try:
        yield state
    finally:
        state.client.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_native_sdk_deadline_closes_owned_body_without_closing_client(
    native_sdk_planner, streaming
):
    from app.application.tool_execution_deadline import invocation_deadline
    from app.application.workflow.retry_policy import PlanningBudgetExceeded

    state = native_sdk_planner
    entered, closed = threading.Event(), threading.Event()

    class BlockedBody(httpx.SyncByteStream):
        def __iter__(self):
            if streaming:
                yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            entered.set()
            closed.wait(2)
            raise httpx.ReadError("owned body closed")

        def close(self):
            closed.set()

    state.body = BlockedBody()
    started = time.monotonic()
    try:
        with invocation_deadline(started + 0.15), pytest.raises(PlanningBudgetExceeded):
            state.invoke(streaming)
        assert time.monotonic() - started < 0.65
        assert entered.is_set() and closed.wait(0.5)
        assert state.workers[0].finished.wait(0.5)
        assert state.chunks == (["partial"] if streaming else [])
        assert len(state.posts) == 1
        assert not state.client.is_closed()
        assert state.client.max_retries == 2
    finally:
        closed.set()


@pytest.mark.parametrize("streaming", [False, True])
def test_native_sdk_deadline_does_not_wait_for_blocked_headers_or_accept_late_result(
    native_sdk_planner, streaming
):
    from app.application.tool_execution_deadline import invocation_deadline
    from app.application.workflow.retry_policy import PlanningBudgetExceeded

    state = native_sdk_planner
    entered, released = threading.Event(), threading.Event()

    def block_headers():
        entered.set()
        released.wait(2)

    state.before_response = block_headers
    started = time.monotonic()
    try:
        with invocation_deadline(started + 0.15), pytest.raises(PlanningBudgetExceeded):
            state.invoke(streaming)
        assert time.monotonic() - started < 0.65
        assert entered.is_set() and not released.is_set()
        assert state.chunks == []
        assert len(state.posts) == 1
        assert state.context["planning_diagnostics"]["model_attempts"] == 1
        assert not state.client.is_closed()
    finally:
        released.set()
        assert state.workers[0].finished.wait(0.5)


@pytest.mark.parametrize("streaming", [False, True])
def test_native_sdk_trusted_deadline_clamps_timeouts_and_disables_only_scoped_retries(
    native_sdk_planner, streaming
):
    from openai import RateLimitError

    from app.application.tool_execution_deadline import invocation_deadline

    state = native_sdk_planner

    async def request():
        if streaming:
            return [
                chunk async for chunk in state.provider.stream_chat_completion([], model="fixture")
            ]
        return await state.provider.chat_completion([], model="fixture")

    state.statuses = [429, 200]
    with invocation_deadline(time.monotonic() + 2), pytest.raises(RateLimitError):
        asyncio.run(request())
    assert len(state.posts) == 1
    timeouts = state.posts[0].extensions["timeout"]
    assert timeouts["connect"] == 0.01
    assert all(0 < value <= 2 for value in timeouts.values())
    assert state.client.timeout == httpx.Timeout(120, connect=0.01, pool=None)
    assert state.client.max_retries == 2
    assert not state.client.is_closed()

    # Outside a trusted deadline, the very same client keeps its configured policy.
    state.statuses = [429, 200]
    assert asyncio.run(request())
    assert len(state.posts) == 3
    assert state.posts[-1].extensions["timeout"]["read"] == 120
    assert state.posts[-1].extensions["timeout"]["pool"] is None
