"""A partial model answer must retain a failed receipt through chat and history."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.application.ai_chat.conversation_history import persist_chat_turn
from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
from app.application.workflow.planner import LLMWorkflowPlanner
from app.fastapi_routes.xcagi_compat_chat_stream import _token_events
from app.infrastructure import chat_stream_lifetime as lifetime
from tests.fixtures.planner_model import goal_review_response


def _dispatch(monkeypatch, completion):
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    risk = Mock()
    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry", lambda: {}
    )
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    return PlannedWorkflowDispatch({}, callbacks, planner, risk, Mock()), risk


def _assert_failed_history(result):
    store = Mock()
    store.save_turn.return_value = [1, 2]
    persist_chat_turn(
        "owner",
        "你好",
        {"local_user_id": 71, "conversation_id": "partial-reply", "turn_id": "turn-1"},
        result,
        store=store,
    )
    assistant = store.save_turn.call_args.kwargs["messages"][-1]
    assert assistant["content"] == result["response"]
    assert json.loads(assistant["metadata"])["summary"]["status"] == "failed"


@pytest.mark.parametrize("ending", ["disconnect", "eof", "late_error", "mode_changed", "empty"])
def test_incomplete_stream_is_failed_without_replacing_or_replaying_answer(monkeypatch, ending):
    prefix = "" if ending == "empty" else "你好，我可以帮你"

    async def stream(**kwargs):
        if ending == "empty":
            return
        yield '{"mode":"reply","reply":"' + prefix
        if ending == "mode_changed":
            yield '","mode":"workflow","nodes":[{"tool_id":"x","action":"y"}]}'
        elif ending == "late_error":
            yield '"}'
        if ending in {"disconnect", "late_error"}:
            raise OSError("provider-private-diagnostic")

    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway.stream_planner_completion", stream
    )
    completion = Mock(return_value=None)
    dispatch, risk = _dispatch(monkeypatch, completion)
    active = lifetime.StreamLifetime()
    emitted = []
    active.observe_deltas(emitted.append)
    token = lifetime.current_lifetime.set(active)
    try:
        result = dispatch.handle("owner", "你好", "normal", {}, "你好")
    finally:
        lifetime.current_lifetime.reset(token)

    assert result["success"] is False
    assert result["execution_state"] == "failed"
    assert (
        result["data"]["error_code"]
        == {
            "disconnect": "model_connection_failed",
            "late_error": "model_connection_failed",
            "eof": "model_output_truncated",
            "mode_changed": "model_response_invalid",
            "empty": "model_response_invalid",
        }[ending]
    )
    assert result["data"]["execution_started"] is False
    if prefix:
        assert result["response"].startswith(prefix + "\n\n")
    assert "未完整" in result["response"]
    assert "provider-private-diagnostic" not in json.dumps(result)
    completion.assert_not_called()
    risk.evaluate.assert_not_called()
    assert "".join(emitted) == prefix
    tail = list(_token_events(lambda item: item, result["response"], "".join(emitted)))
    assert "".join(emitted) + "".join(item["text"] for item in tail) == result["response"]
    _assert_failed_history(result)


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", None, "", "unknown"])
@pytest.mark.parametrize("message", ["你好", "解释一下 Python 列表推导式"])
def test_sync_incomplete_completion_is_not_repaired_into_success(
    monkeypatch, finish_reason, message
):
    completion = Mock(
        return_value={
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": '{"mode":"reply","reply":"部分回答"}'},
                }
            ]
        }
    )
    dispatch, risk = _dispatch(monkeypatch, completion)
    result = dispatch.handle("owner", message, "normal", {}, message)
    assert result["success"] is False
    assert result["data"]["error_code"] == "model_response_incomplete"
    assert result["data"]["execution_started"] is False
    assert "未完整" in result["response"]
    assert completion.call_count == 1
    risk.evaluate.assert_not_called()
    _assert_failed_history(result)


def test_complete_stream_still_returns_one_successful_answer(monkeypatch):
    async def stream(**kwargs):
        yield '{"mode":"reply","reply":"你'
        yield '好"}'

    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway.stream_planner_completion", stream
    )
    completion = Mock()
    dispatch, risk = _dispatch(monkeypatch, completion)
    active = lifetime.StreamLifetime()
    emitted = []
    active.observe_deltas(emitted.append)
    token = lifetime.current_lifetime.set(active)
    try:
        result = dispatch.handle("owner", "你好", "normal", {}, "你好")
    finally:
        lifetime.current_lifetime.reset(token)
    assert result["success"] is True
    assert result["response"] == "".join(emitted) == "你好"
    assert list(_token_events(lambda item: item, result["response"], "".join(emitted))) == []
    completion.assert_not_called()
    risk.evaluate.assert_not_called()


def test_provider_without_streaming_uses_one_sync_completion(monkeypatch):
    from app.infrastructure.llm.instrumented_provider import InstrumentedProvider
    from app.infrastructure.llm.model_admission import RateLimitedProvider

    wrapped = InstrumentedProvider(RateLimitedProvider(SimpleNamespace(provider_id="sync-only")))
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **kwargs: wrapped
    )
    completion = Mock(
        return_value={"choices": [{"message": {"content": '{"mode":"reply","reply":"你好"}'}}]}
    )
    dispatch, _ = _dispatch(monkeypatch, completion)
    token = lifetime.current_lifetime.set(lifetime.StreamLifetime())
    try:
        result = dispatch.handle("owner", "你好", "normal", {}, "你好")
    finally:
        lifetime.current_lifetime.reset(token)
    assert result["success"] is True
    assert result["response"] == "你好"
    assert completion.call_count == 1


def test_json_repair_cannot_complete_a_truncated_answer(monkeypatch):
    completion = Mock(
        return_value={
            "choices": [
                {"finish_reason": "stop", "message": {"content": '{"mode":"reply","reply":"半句'}}
            ]
        }
    )
    dispatch, _ = _dispatch(monkeypatch, completion)
    result = dispatch.handle("owner", "你好", "normal", {}, "你好")
    assert result["success"] is False
    assert result["data"]["execution_started"] is False
    _assert_failed_history(result)


@pytest.mark.parametrize("shape", ["market", "openai"])
@pytest.mark.parametrize("finish_reason", [None, "length", "end_turn"])
def test_market_normalization_never_invents_successful_finish(monkeypatch, shape, finish_reason):
    from app.infrastructure.llm.modstore_response_normalize import normalize_market_chat_response

    text = '{"mode":"reply","reply":"你好"}'
    raw = {"content": text} if shape == "market" else {"choices": [{"message": {"content": text}}]}
    if finish_reason is not None:
        (raw if shape == "market" else raw["choices"][0])["finish_reason"] = finish_reason
    response = normalize_market_chat_response(raw, "fixture", "test")
    assert response["choices"][0]["finish_reason"] == finish_reason
    dispatch, _ = _dispatch(monkeypatch, Mock(return_value=response))
    result = dispatch.handle("owner", "你好", "normal", {}, "你好")
    assert result["success"] is (finish_reason == "end_turn")
    if finish_reason != "end_turn":
        assert result["data"]["error_code"] == "model_response_incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", [None, "end_turn", "max_tokens"])
async def test_minimax_adapter_preserves_unknown_finish(monkeypatch, finish_reason):
    from app.domain.shared_services.conversation.llm_adapter import OpenAICompatibleAdapter
    from app.infrastructure.llm.response_completion import completion_is_incomplete

    adapter = OpenAICompatibleAdapter(provider="minimax", api_key="sk-cp-synthetic")
    data = {"content": [{"type": "text", "text": "你好"}]}
    if finish_reason is not None:
        data["stop_reason"] = finish_reason
    response = Mock(json=Mock(return_value=data))
    client = AsyncMock()
    client.post.return_value = response
    monkeypatch.setattr(adapter, "_get_client", AsyncMock(return_value=client))
    result = await adapter.chat_completion([{"role": "user", "content": "你好"}])
    assert result["choices"][0]["finish_reason"] == finish_reason
    assert completion_is_incomplete(result) is (finish_reason != "end_turn")


def test_incomplete_reply_review_cannot_admit_a_complete_answer(monkeypatch):
    message = "解释一下 Python 列表推导式"
    # This negative control owns one audit; the production retry policy is unchanged.
    monkeypatch.setenv("XCAGI_GOAL_COVERAGE_MAX_ATTEMPTS", "1")

    def complete(**kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        if request.get("task") in {"audit_goal_coverage", "audit_reply"}:
            response = goal_review_response(
                request, source=message, node_ids=["model_reply"], outcome="reply"
            )
            response["choices"][0]["finish_reason"] = "length"
            return response
        return {
            "choices": [
                {
                    "message": {"content": '{"mode":"reply","reply":"完整回答"}'},
                    "finish_reason": "stop",
                }
            ]
        }

    completion = Mock(side_effect=complete)
    dispatch, risk = _dispatch(monkeypatch, completion)
    result = dispatch.handle("owner", message, "normal", {}, message)
    assert result["success"] is False
    assert result["data"]["error_code"] == "model_response_incomplete"
    assert completion.call_count == 2
    risk.evaluate.assert_not_called()


@pytest.mark.parametrize("provider_kind", ["sdk", "modstore", "modstore_market"])
@pytest.mark.parametrize(
    "finish_reason",
    [
        "length",
        "max_tokens",
        "content_filter",
        "stop",
        "end_turn",
        "stop_sequence",
        "STOP",
        "missing",
        "done_only",
        "late_error",
        "late_payload_error",
    ],
)
def test_provider_terminal_reason_survives_streaming_planner(
    monkeypatch, provider_kind, finish_reason
):
    from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
    from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider

    finish = (
        None
        if finish_reason in {"missing", "done_only"}
        else "stop"
        if finish_reason in {"late_error", "late_payload_error"}
        else finish_reason
    )
    chunks = [
        {"choices": [{"delta": {"content": '{"mode":"reply","reply":"你好"}'}}]},
        {"choices": [{"delta": {}, "finish_reason": finish}]},
    ]
    if provider_kind == "modstore_market":
        chunks = [
            {"delta": '{"mode":"reply","reply":"你好"}'},
            {"finish_reason": finish},
        ]
    if provider_kind == "sdk":
        from app.infrastructure.llm import client

        def sdk_stream(**kwargs):
            yield from chunks
            if finish_reason in {"late_error", "late_payload_error"}:
                raise OSError("post-finish provider-private-diagnostic")

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sdk_stream)))
        monkeypatch.setattr(client, "require_api_key", lambda: None)
        monkeypatch.setattr(client, "get_llm_client", lambda: fake)
        provider = OpenAISdkProvider()
    else:

        class Adapter:
            async def stream_chat_completion(self, **kwargs):
                for chunk in chunks:
                    yield json.dumps(chunk)
                if finish_reason == "late_error":
                    raise OSError("post-finish provider-private-diagnostic")
                if finish_reason == "late_payload_error":
                    yield json.dumps(
                        {"type": "error", "status": 503, "error": "provider-private-diagnostic"}
                    )
                if finish_reason != "missing":
                    yield "[DONE]"

        provider = ModstoreProvider(Adapter())
    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway.stream_planner_completion",
        lambda **kwargs: provider.stream_chat_completion([], model="fixture"),
    )
    completion = Mock()
    dispatch, risk = _dispatch(monkeypatch, completion)
    token = lifetime.current_lifetime.set(lifetime.StreamLifetime())
    try:
        result = dispatch.handle("owner", "你好", "normal", {}, "你好")
    finally:
        lifetime.current_lifetime.reset(token)
    successful = finish_reason in {"stop", "end_turn", "stop_sequence", "STOP"}
    assert result["success"] is successful
    if not successful:
        expected_code = {
            "length": "model_output_truncated",
            "content_filter": "model_response_blocked",
            "late_error": "model_connection_failed",
            "late_payload_error": "model_connection_failed"
            if provider_kind == "sdk"
            else "model_unavailable",
        }.get(finish_reason, "model_response_incomplete")
        assert result["data"]["error_code"] == expected_code
        assert result["response"].startswith("你好\n\n")
        assert "provider-private-diagnostic" not in json.dumps(result)
    completion.assert_not_called()
    risk.evaluate.assert_not_called()


@pytest.mark.parametrize("mode", ["reply", "workflow"])
def test_review_uses_candidate_evidence_without_reloading_or_trimming_history(monkeypatch, mode):
    from app.application.ai_chat import dialogue_memory as memory

    rows = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"ROW_{index} " + "中" * 100,
            "turn_id": str(index // 2),
        }
        for index in range(40)
    ]
    rows[0]["content"] = "4人，预算400元，一人海鲜过敏；只做方案，不写入。"
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": rows, "summary": None})
    context = {
        "local_user_id": 1,
        "session_id": "review-snapshot",
        "_chat_evidence_authorized": True,
        "_chat_history_messages": rows,
        "chat_customer_evidence": {"scope": "ORIGINAL_AUTHORIZED_EVIDENCE"},
        "_planning_snapshot": ([{"role": "user", "content": "UNTRUSTED_SNAPSHOT"}], {}),
    }
    requests = []

    def complete(**kwargs):
        prompt = json.loads(kwargs["messages"][-1]["content"])
        requests.append(prompt)
        if len(requests) == 1:
            # A later projection cannot replace the evidence used to generate
            # the candidate; the normal SQL revision fence still owns recalls.
            kwargs["context"]["_chat_history_messages"] = [
                {"role": "user", "content": "LATER_PROJECTION"}
            ]
            kwargs["context"]["chat_customer_evidence"]["scope"] = "LATER_EVIDENCE"
            result = (
                {"mode": "reply", "reply": "按4人400元、避开海鲜的条件说明。"}
                if mode == "reply"
                else {
                    "mode": "workflow",
                    "nodes": [
                        {
                            "node_id": "query",
                            "tool_id": "products",
                            "action": "query",
                            "params": {"keyword": "A1"},
                        }
                    ],
                }
            )
        else:
            result = {"violations": []}
            if mode == "workflow":
                result["goals"] = [
                    {
                        "goal_id": "query",
                        "source": "查询 A1",
                        "outcome": "execute",
                        "node_ids": ["query"],
                    }
                ]
        return {"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}

    planner = LLMWorkflowPlanner(
        ai_service=SimpleNamespace(get_context=lambda _: None), completion=complete
    )
    registry = {
        "products": {
            "actions": {"query": {"risk": "low", "idempotent": True, "required_params": []}}
        }
    }
    plan = planner.plan(
        "1", "解释之前的用餐条件" if mode == "reply" else "查询 A1", registry, context
    )
    assert not plan.metadata.get("planning_rejected")
    assert len(requests) == 2
    initial, review = requests
    assert review["conversation_history"] == initial["conversation_history"]
    assert len(review["conversation_history"]) == 40
    assert review["context"] == initial["context"]
    assert "海鲜过敏" in json.dumps(review, ensure_ascii=False)
    assert "ORIGINAL_AUTHORIZED_EVIDENCE" in json.dumps(review)
    assert all(value not in json.dumps(review) for value in ("LATER_", "UNTRUSTED_SNAPSHOT"))
    if mode == "reply":
        assert review["task"] == "audit_reply"
        assert "plan" not in review
        assert set(review["output_schema"]["properties"]) == {
            "violations",
            "clarification_question",
        }
