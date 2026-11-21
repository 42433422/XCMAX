"""有界重试策略：退避上限、可重试范围与规划调用接线。"""

from __future__ import annotations

import httpx
import pytest

from app.application.workflow.retry_policy import (
    RetryPolicy,
    call_with_retry,
    planner_retry_policy,
)


def test_delay_is_exponential_and_capped() -> None:
    policy = RetryPolicy(base_delay=0.1, max_delay=0.3, jitter=0.0)
    assert policy.delay_for(1) == pytest.approx(0.1)
    assert policy.delay_for(2) == pytest.approx(0.2)
    assert policy.delay_for(5) == pytest.approx(0.3)


def test_retries_transient_failures(monkeypatch) -> None:
    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("slow")
        return "ok"

    result = call_with_retry(flaky, policy=RetryPolicy(max_attempts=2))
    assert result == "ok"
    assert calls["n"] == 2


def test_non_retryable_propagates_immediately(monkeypatch) -> None:
    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        call_with_retry(broken, policy=RetryPolicy(max_attempts=3))
    assert calls["n"] == 1


def test_exhausted_attempts_raise_last_error(monkeypatch) -> None:
    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)

    def always_timeout():
        raise TimeoutError("still slow")

    with pytest.raises(TimeoutError):
        call_with_retry(always_timeout, policy=RetryPolicy(max_attempts=2))


def test_policy_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_PLAN_MODEL_RETRIES", "3")
    assert planner_retry_policy().max_attempts == 3
    monkeypatch.setenv("XCAGI_PLAN_MODEL_RETRIES", "99")
    assert planner_retry_policy().max_attempts == 4
    monkeypatch.setenv("XCAGI_PLAN_MODEL_RETRIES", "bad")
    assert planner_retry_policy().max_attempts == 2


@pytest.mark.parametrize("requested, expected", [(999, 4), (0, 1)])
def test_explicit_retry_policy_is_still_hard_bounded(monkeypatch, requested, expected):
    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    calls = []

    def fail():
        calls.append(1)
        raise TimeoutError("transient")

    with pytest.raises(TimeoutError):
        call_with_retry(fail, policy=RetryPolicy(max_attempts=requested))
    assert len(calls) == expected


def test_jitter_does_not_exceed_the_actual_delay_cap(monkeypatch):
    monkeypatch.setattr("app.application.workflow.retry_policy.random.uniform", lambda *args: 9.0)
    assert RetryPolicy(max_delay=0.3, jitter=9.0).delay_for(3) <= 0.3


def test_real_gateway_network_failures_reach_the_bounded_retry_owner(monkeypatch, caplog):
    import httpx

    from app.application.workflow.planner_llm_gateway import request_planner_completion

    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    calls = []

    class Provider:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise httpx.ConnectError("synthetic-private-network-detail")
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **kwargs: Provider()
    )
    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway._meter_planner_completion",
        lambda *args, **kwargs: None,
    )
    result = call_with_retry(
        lambda: request_planner_completion(ai_service=None, context={}, messages=[]),
        policy=RetryPolicy(max_attempts=2),
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 2
    assert "synthetic-private-network-detail" not in caplog.text
    from app.application.workflow.retry_policy import retry_manages_transport_error

    assert not retry_manages_transport_error(httpx.ConnectError("outside-owner-scope"))


def test_custom_retry_set_cannot_retry_admission_or_parameter_errors(monkeypatch):
    from app.domain.model_admission_errors import ModelRateLimitError

    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    calls = []

    def fail():
        calls.append(1)
        raise ModelRateLimitError(60)

    with pytest.raises(ModelRateLimitError):
        call_with_retry(fail, policy=RetryPolicy(max_attempts=4), retry_on=(Exception,))
    assert calls == [1]


def test_repair_and_review_completions_share_transport_retry_owner(monkeypatch):
    from unittest.mock import Mock

    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow.retry_policy import planning_request_scope, planning_stage

    monkeypatch.setattr("app.application.workflow.retry_policy.time.sleep", lambda _: None)
    completion = Mock(side_effect=[httpx.ConnectError("private"), {"choices": []}])
    planner = LLMWorkflowPlanner(ai_service=Mock(), completion=completion)
    context = {}
    with planning_request_scope(context):
        planning_stage("coverage")
        assert planner.complete_messages(messages=[], context=context) == {"choices": []}
    assert completion.call_count == 2
    assert context["planning_diagnostics"]["model_attempts"] == 2
    assert context["planning_diagnostics"]["transport_retries"] == 1
    assert [row["stage"] for row in context["planning_diagnostics"]["stages"]] == ["coverage"] * 2


def test_request_call_budget_covers_stages_and_cannot_retry_itself(monkeypatch):
    from app.application.workflow.retry_policy import (
        PlanningBudgetExceeded,
        planning_model_call,
        planning_request_scope,
        planning_stage,
    )

    monkeypatch.setenv("XCAGI_PLAN_MAX_MODEL_CALLS", "2")
    context = {}
    calls = []
    with planning_request_scope(context):
        for stage in ("planning", "repair"):
            planning_stage(stage)
            with planning_model_call():
                calls.append(stage)
        with pytest.raises(PlanningBudgetExceeded):
            call_with_retry(lambda: _attempt(calls), policy=RetryPolicy(max_attempts=4))
    assert calls == ["planning", "repair"]
    assert context["planning_diagnostics"]["exhausted"] == "model_call_limit"
    assert context["planning_diagnostics"]["transport_retries"] == 0


def _attempt(calls):
    from app.application.workflow.retry_policy import planning_model_call

    with planning_model_call():
        calls.append("not-allowed")


def test_expired_wall_clock_never_starts_next_model_call(monkeypatch):
    from app.application.workflow.retry_policy import PlanningBudgetExceeded, planning_request_scope

    now = [100.0]
    monkeypatch.setattr("app.application.workflow.retry_policy.time.monotonic", lambda: now[0])
    monkeypatch.setenv("XCAGI_PLAN_TIMEOUT_SECONDS", "5")
    context, calls = {}, []
    with planning_request_scope(context):
        now[0] += 6
        with pytest.raises(PlanningBudgetExceeded):
            call_with_retry(lambda: calls.append(1), policy=RetryPolicy(max_attempts=4))
    assert calls == []
    assert context["planning_diagnostics"]["exhausted"] == "deadline"


def test_stream_cancellation_is_not_retried():
    from app.infrastructure.chat_stream_lifetime import (
        StreamLifetime,
        StreamStopped,
        current_lifetime,
    )

    lifetime = StreamLifetime()
    lifetime.cancel()
    token = current_lifetime.set(lifetime)
    calls = []
    try:
        with pytest.raises(StreamStopped):
            call_with_retry(lambda: calls.append(1), policy=RetryPolicy(max_attempts=4))
    finally:
        current_lifetime.reset(token)
    assert not calls


def test_late_synchronous_result_cannot_escape_call_deadline(monkeypatch):
    from app.application.workflow.retry_policy import (
        PlanningBudgetExceeded,
        planning_model_call,
        planning_request_scope,
    )

    now = [100.0]
    monkeypatch.setattr("app.application.workflow.retry_policy.time.monotonic", lambda: now[0])
    monkeypatch.setenv("XCAGI_PLAN_CALL_TIMEOUT_SECONDS", "2")
    context = {}
    with planning_request_scope(context):
        with pytest.raises(PlanningBudgetExceeded):
            with planning_model_call():
                now[0] += 3
    assert context["planning_diagnostics"]["exhausted"] == "deadline"
    assert context["planning_diagnostics"]["stages"][0]["outcome"] == "error"
