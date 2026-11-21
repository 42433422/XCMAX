"""Provider availability must not depend on successful plan decoding."""

import json
from unittest.mock import Mock

import httpx
import pytest

from app.application.workflow import model_response_metrics as evidence
from app.application.workflow.llm_plan_generation import LlmPlanGeneration
from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_execution.registry import get_workflow_tool_registry


@pytest.mark.parametrize("message", ["hello", "请把客户写入数据库"])
@pytest.mark.parametrize(
    "response,outcome",
    [('{"mode":"workflow","nodes":[]}', "returned"), ("", "empty"), (None, "empty")],
)
def test_raw_completion_outcome_survives_invalid_plan(monkeypatch, message, response, outcome):
    observed = []
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "0")
    monkeypatch.setattr(evidence, "observe_plan_stage", lambda **kw: observed.append(kw))
    ai = Mock()
    ai.get_context.return_value = None
    completion = Mock(
        return_value=None if response is None else {"choices": [{"message": {"content": response}}]}
    )
    planner = LLMWorkflowPlanner(ai_service=ai, completion=completion)
    plan = planner.plan("u", message, get_workflow_tool_registry(), {})
    assert plan.metadata["planning_rejected"] is True
    assert [item["outcome"] for item in observed] == [outcome]


def test_native_reply_and_valid_review_each_record_a_returned_response(monkeypatch):
    observed, tasks = [], []
    monkeypatch.setattr(evidence, "observe_plan_stage", lambda **kw: observed.append(kw))
    reply = "缓存会暂存重复读取的数据。"

    def complete(**kwargs):
        payload = json.loads(kwargs["messages"][-1]["content"])
        tasks.append(payload["task"])
        if payload["task"] == "audit_reply":
            assert payload["reply"] == reply
            content = '{"violations":[],"clarification_question":null}'
        else:
            content = reply
        return {"choices": [{"message": {"content": content}}]}

    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=complete
    )
    plan = planner.plan("u", "解释缓存", get_workflow_tool_registry(), {})
    assert plan.metadata["response_mode"] == "reply"
    assert plan.metadata["reply"] == reply
    assert len(tasks) == 2 and tasks[-1] == "audit_reply"
    assert [item["outcome"] for item in observed] == ["returned", "returned"]


@pytest.mark.parametrize("message", ["hello", "请把客户写入数据库"])
def test_exhausted_transport_error_is_not_empty(monkeypatch, message):
    observed = []
    monkeypatch.setenv("XCAGI_PLAN_MODEL_RETRIES", "2")
    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    monkeypatch.setattr(evidence, "observe_plan_stage", lambda **kw: observed.append(kw))
    ai = Mock()
    ai.get_context.return_value = None
    completion = Mock(side_effect=httpx.ConnectError("offline"))
    plan = LLMWorkflowPlanner(ai_service=ai, completion=completion).plan(
        "u", message, get_workflow_tool_registry(), {}
    )
    assert plan.metadata["planning_rejected"] is True
    assert completion.call_count == 2
    assert [item["outcome"] for item in observed] == ["error"]


def test_retry_success_and_subsequent_request_do_not_duplicate_or_leak(monkeypatch):
    observed = []
    monkeypatch.setattr(evidence, "observe_plan_stage", lambda **kw: observed.append(kw))
    wrapped = evidence.observe_model_response(
        Mock(
            side_effect=[
                httpx.ConnectError("retry"),
                {"choices": [{"message": {"tool_calls": [{"id": "tool"}]}}]},
                None,
            ]
        )
    )
    with evidence.model_response_scope():
        with pytest.raises(httpx.ConnectError):
            wrapped()
        wrapped()
    with evidence.model_response_scope():
        wrapped()
    wrapped = evidence.observe_model_response(lambda: None)
    wrapped()  # A completion outside the planning stage must not add a sample.
    assert [item["outcome"] for item in observed] == ["returned", "empty"]


@pytest.mark.parametrize("partial", [True, False])
def test_interrupted_stream_is_an_error_even_after_partial_content(monkeypatch, partial):
    observed = []
    monkeypatch.setattr(evidence, "observe_plan_stage", lambda **kw: observed.append(kw))
    from app.infrastructure.chat_stream_lifetime import current_lifetime

    async def chunks():
        if partial:
            yield "not a plan"
        raise httpx.ConnectError("stream disconnected")

    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway.stream_planner_completion",
        lambda **kw: chunks(),
    )
    generation = LlmPlanGeneration(Mock(), Mock(), Mock())
    token = current_lifetime.set(Mock())
    try:
        with evidence.model_response_scope():
            with pytest.raises(httpx.ConnectError):
                generation._stream_reply([], {})
    finally:
        current_lifetime.reset(token)
    assert [item["outcome"] for item in observed] == ["error"]
