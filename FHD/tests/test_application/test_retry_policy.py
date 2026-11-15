"""有界重试策略：退避上限、可重试范围与规划调用接线。"""

from __future__ import annotations

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
