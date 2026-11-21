"""Model failures remain typed across planning and never create a user-input task."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APIStatusError

from app.application.tool_execution_deadline import InvocationBudget, invocation_deadline
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.planner_llm_gateway import (
    request_planner_completion,
    stream_planner_completion,
)
from app.application.workflow.retry_policy import RetryPolicy, call_with_retry
from app.infrastructure.llm.model_context_windows import ModelLimits
from app.infrastructure.modstore_transport import MarketModelError


def _response(content="ok", **choice):
    return {"choices": [{"message": {"content": content}, **choice}]}


@pytest.fixture
def provider(monkeypatch):
    provider = SimpleNamespace(chat_completion=AsyncMock(return_value=_response()))
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    monkeypatch.setattr(
        "app.infrastructure.llm.model_context_windows.resolve_model_limits",
        AsyncMock(return_value=ModelLimits(context_window=8192)),
    )
    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway._meter_planner_completion", Mock()
    )
    return provider


def _complete(context=None):
    return request_planner_completion(ai_service=None, context=context, messages=[])


def test_no_provider_is_configuration_failure_for_both_entrypoints(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: None
    )
    for complete in (request_planner_completion, stream_planner_completion):
        with pytest.raises(MarketModelError) as failure:
            complete(ai_service=None, context={}, messages=[])
        assert failure.value.code == "model_not_configured"
        assert failure.value.retryable is False


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "model_authentication_failed", False),
        (403, "model_access_denied", False),
        (429, "model_rate_limited", True),
        (503, "model_unavailable", True),
    ],
)
def test_sdk_status_is_preserved_without_private_provider_text(provider, status, code, retryable):
    response = httpx.Response(status, request=httpx.Request("POST", "https://secret.invalid/key"))
    provider.chat_completion.side_effect = APIStatusError(
        "api_key=synthetic-secret", response=response, body={"private": "synthetic-secret"}
    )
    with pytest.raises(MarketModelError) as failure:
        call_with_retry(_complete, policy=RetryPolicy(max_attempts=4))
    assert (failure.value.code, failure.value.status_code, failure.value.retryable) == (
        code,
        status,
        retryable,
    )
    assert "synthetic-secret" not in str(failure.value)
    assert "secret.invalid" not in str(failure.value)
    assert provider.chat_completion.call_count == 1


@pytest.mark.parametrize(
    "response,code",
    [
        (None, "model_response_invalid"),
        ({}, "model_response_invalid"),
        (_response("", finish_reason="length"), "model_output_truncated"),
        (_response("", finish_reason="content_filter"), "model_response_blocked"),
    ],
)
def test_unusable_response_is_not_provider_absence(provider, response, code):
    provider.chat_completion.return_value = response
    with pytest.raises(MarketModelError) as failure:
        _complete({})
    assert failure.value.code == code
    assert failure.value.retryable is False


def test_native_tool_message_survives_response_validation(provider):
    response = {"choices": [{"message": {"tool_calls": [{"type": "function"}]}}]}
    provider.chat_completion.return_value = response
    assert _complete({}) is response


def test_deadline_cancels_async_provider_without_retry(provider):
    closed = []

    async def wait_forever(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    provider.chat_completion.side_effect = wait_forever
    context = {"_planner_model_budget": InvocationBudget(time.monotonic() + 0.03)}
    started = time.monotonic()
    with pytest.raises(MarketModelError) as failure:
        call_with_retry(lambda: _complete(context), policy=RetryPolicy(max_attempts=4))
    assert failure.value.code == "model_deadline_exceeded"
    assert closed == [True] and provider.chat_completion.call_count == 1
    assert time.monotonic() - started < 1


def test_new_stage_does_not_reset_shared_budget_and_json_cannot_set_it(provider):
    context = {"_planner_model_budget": {"deadline": 0}}
    _complete(context)
    assert isinstance(context["_planner_model_budget"], InvocationBudget)
    context["_planner_model_budget"].deadline = time.monotonic() - 1
    with pytest.raises(MarketModelError) as failure:
        _complete(context)
    assert failure.value.code == "model_deadline_exceeded"
    assert provider.chat_completion.call_count == 1


def test_retry_backoff_cannot_start_a_call_outside_the_deadline(monkeypatch):
    call = Mock(side_effect=httpx.ConnectError("private-network-detail"))
    sleep = Mock()
    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", sleep)
    with invocation_deadline(time.monotonic() + 0.01), pytest.raises(MarketModelError) as failure:
        call_with_retry(call, policy=RetryPolicy(max_attempts=4, base_delay=1))
    assert failure.value.code == "model_deadline_exceeded"
    call.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "response", [None, _response("malformed-json"), MarketModelError({"status": 401})]
)
def test_review_failure_has_no_clarification_nodes_or_false_semantic_rejection(response):
    plan = _response(
        json.dumps(
            {
                "mode": "workflow",
                "intent": "query",
                "nodes": [{"node_id": "a", "tool_id": "products", "action": "query", "params": {}}],
            }
        )
    )
    completion = Mock(side_effect=[plan, response])
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    registry = {"products": {"actions": {"query": {"risk": "low", "idempotent": True}}}}
    result = planner.plan("owner", "查询产品", registry)
    assert result.metadata["planning_rejected"] is True
    assert not result.metadata.get("goal_coverage_rejected")
    assert result.nodes == []
    expected = (
        "model_authentication_failed"
        if isinstance(response, Exception)
        else "goal_review_unavailable"
    )
    assert result.metadata["planning_failure_code"] == expected
    assert result.metadata["planning_failure_stage"] == "goal_review"
    assert completion.call_count == 2
    assert "_planner_model_budget" not in json.dumps(result.metadata)


def test_sdk_worker_uses_remaining_budget_and_no_second_retry_layer(monkeypatch):
    from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider

    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(model_dump=lambda: _response())
    monkeypatch.setattr("app.infrastructure.llm.client.get_llm_client", lambda: client)
    monkeypatch.setattr("app.infrastructure.llm.client.require_api_key", lambda: None)
    with invocation_deadline(time.monotonic() + 0.5):
        asyncio.run(OpenAISdkProvider().chat_completion(messages=[], model="test-model"))
    client.with_options.assert_called_once_with(max_retries=0)
    assert 0 < client.chat.completions.create.call_args.kwargs["timeout"] <= 0.5


def test_missing_sdk_credentials_do_not_raise_during_provider_selection(monkeypatch):
    from app.infrastructure.llm import client
    from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider

    monkeypatch.setattr(client, "_first_api_key", lambda: ("", None))
    monkeypatch.setattr(client, "resolve_mode", lambda: "online")
    token = client._scoped_client.set(None)
    try:
        assert OpenAISdkProvider().is_configured is False
    finally:
        client._scoped_client.reset(token)


@pytest.mark.parametrize(
    "ending,code",
    [
        ("error", "model_unavailable"),
        ("timeout", "model_deadline_exceeded"),
        ("truncated", "model_output_truncated"),
        ("empty", "model_response_invalid"),
    ],
)
def test_started_stream_never_replays_or_fabricates_completion(provider, ending, code):
    from app.application.workflow.llm_plan_generation import LlmPlanGeneration
    from app.infrastructure.chat_stream_lifetime import current_lifetime

    closed = []

    async def chunks(**kwargs):
        try:
            if ending == "empty":
                return
            yield '{"mode":"reply","reply":"部分正文'
            if ending == "error":
                raise MarketModelError({"status": 503})
            if ending == "timeout":
                await asyncio.Event().wait()
        finally:
            closed.append(True)

    provider.stream_chat_completion = chunks
    fallback, lifetime = Mock(), Mock()
    generation = LlmPlanGeneration(Mock(), fallback, Mock())
    context = {"_planner_model_budget": InvocationBudget(time.monotonic() + 0.05)}
    token = current_lifetime.set(lifetime)
    try:
        with pytest.raises(MarketModelError) as failure:
            generation._light_reply("turn", "你好", context)
    finally:
        current_lifetime.reset(token)
    assert failure.value.code == code
    assert closed == [True]
    fallback.assert_not_called()
    provider.chat_completion.assert_not_called()
    if ending != "empty":
        lifetime.publish_delta.assert_called_once_with("部分正文")


def test_provider_without_stream_capability_uses_one_completion(provider):
    from app.application.workflow.llm_plan_generation import LlmPlanGeneration
    from app.infrastructure.chat_stream_lifetime import current_lifetime

    completion = Mock(return_value=_response('{"mode":"reply","reply":"你好"}'))
    token = current_lifetime.set(Mock())
    try:
        result = LlmPlanGeneration(Mock(), completion, Mock())._light_reply("turn", "你好", {})
    finally:
        current_lifetime.reset(token)
    assert result.metadata["reply"] == "你好"
    completion.assert_called_once()


@pytest.mark.parametrize("wire", ["sdk", "modstore", "modstore_done"])
@pytest.mark.parametrize(
    "ending,code",
    [
        ("length", "model_output_truncated"),
        ("content_filter", "model_response_blocked"),
        ("refusal", "model_response_blocked"),
        ("stop", None),
    ],
)
def test_complete_stream_json_cannot_hide_provider_failure(
    monkeypatch, provider, wire, ending, code
):
    from openai.types.chat import ChatCompletionChunk

    from app.application.workflow import model_response_metrics as evidence
    from app.infrastructure.chat_stream_lifetime import current_lifetime
    from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
    from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider

    closed, observed = [], []
    monkeypatch.setattr(evidence, "observe_plan_stage", lambda **kw: observed.append(kw["outcome"]))
    terminal = (
        {"delta": {"refusal": "private-refusal"}, "finish_reason": None}
        if ending == "refusal"
        else {"delta": {}, "finish_reason": ending}
    )
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": '{"mode":"reply","reply":"你好"}'}}]},
        {"choices": [{"index": 0, **terminal}]},
    ]
    if wire == "sdk":

        def source(**kwargs):
            try:
                for chunk in chunks:
                    yield ChatCompletionChunk(
                        id="fixture",
                        created=0,
                        model="fixture",
                        object="chat.completion.chunk",
                        **chunk,
                    )
            finally:
                closed.append(True)

        call = Mock(side_effect=source)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=call)))
        monkeypatch.setattr("app.infrastructure.llm.client.require_api_key", lambda: None)
        monkeypatch.setattr("app.infrastructure.llm.client.get_llm_client", lambda: client)
        actual = OpenAISdkProvider()
    else:
        if wire == "modstore_done":
            chunks[-1] = (
                {"refusal": "private-refusal"} if ending == "refusal" else {"finish_reason": ending}
            )

        async def source(**kwargs):
            try:
                for chunk in chunks:
                    yield json.dumps(chunk)
                yield "[DONE]"
            finally:
                closed.append(True)

        call = Mock(side_effect=source)
        actual = ModstoreProvider(SimpleNamespace(stream_chat_completion=call))
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: actual
    )
    completion, lifetime = Mock(), Mock()
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    token = current_lifetime.set(lifetime)
    try:
        result = planner.plan("owner", "你好", {})
    finally:
        current_lifetime.reset(token)
    assert call.call_count == 1 and closed == [True]
    completion.assert_not_called()
    lifetime.publish_delta.assert_called_once_with("你好")
    if code:
        assert result.metadata["planning_rejected"] is True
        assert result.metadata["planning_failure_code"] == code
        assert result.metadata["planning_failure_retryable"] is False
        assert result.nodes == []
        assert observed == ["error"]
        assert "private-refusal" not in json.dumps(result.metadata)
    else:
        assert result.metadata["response_mode"] == "reply"
        assert result.metadata["reply"] == "你好"
        assert observed == ["returned"]
