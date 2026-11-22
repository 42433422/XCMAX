"""Real HTTP ownership and trusted budget contracts for bounded model attempts."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from openai import APIConnectionError

from app.infrastructure.chat_stream_lifetime import StreamObservationTimeout, StreamStopped
from app.infrastructure.llm.retry_policy import (
    ModelBudgetExceeded,
    RetryPolicy,
    async_call_with_retry,
    call_with_retry,
    is_safe_transport_retry,
    is_transport_error,
    model_call,
    model_failure_details,
    model_request_scope,
)


def scope(diagnostics, *, calls=4, used=0, seconds=5, cancelled=None):
    return model_request_scope(
        deadline_at=time.time() + seconds,
        max_calls=calls,
        attempts_used=used,
        diagnostics=diagnostics,
        cancelled=cancelled,
    )


@pytest.mark.asyncio
async def test_connection_retry_keeps_the_same_request_and_counts_each_physical_attempt():
    posted, diagnostics = [], {}

    def respond(request):
        posted.append((str(request.url), json.loads(request.content)))
        if len(posted) == 1:
            raise httpx.ConnectError("private-host-name", request=request)
        return httpx.Response(200, json={"output": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:

        async def invoke():
            return await client.post(
                "https://model.invalid/responses",
                json={"model": "pinned", "request_id": "same-parent-call", "allow_failover": False},
            )

        with scope(diagnostics, used=2):
            result = await async_call_with_retry(
                invoke, policy=RetryPolicy(base_delay=0, jitter=0), stage="goal_review"
            )
    assert result.status_code == 200
    assert posted[0] == posted[1]
    assert diagnostics["model_attempts"] == 4
    assert diagnostics["transport_retries"] == 1
    assert [row["attempt"] for row in diagnostics["stages"]] == [3, 4]
    assert [row["outcome"] for row in diagnostics["stages"]] == ["not_started", "returned"]
    assert all(
        row["stage"] == "goal_review" and row["elapsed_ms"] >= 0 for row in diagnostics["stages"]
    )
    assert "private-host-name" not in json.dumps(diagnostics)


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout,
        httpx.WriteError,
        httpx.RemoteProtocolError,
        TimeoutError,
        StreamObservationTimeout,
    ],
)
def test_unconfirmed_output_cannot_be_replayed(failure):
    attempts, diagnostics = [], {}

    def invoke():
        attempts.append(1)
        raise failure("unconfirmed-response")

    with scope(diagnostics), pytest.raises(failure):
        call_with_retry(invoke, policy=RetryPolicy(max_attempts=4, base_delay=0, jitter=0))
    assert attempts == [1]
    assert diagnostics["stages"][0]["retryable"] is False
    assert diagnostics["stages"][0]["outcome"] == "unknown"
    assert diagnostics["stages"][0]["failure_kind"] == "transport_unknown"


def test_output_started_remains_unknown_even_if_later_connection_error_is_wrapped():
    diagnostics = {}
    with scope(diagnostics), pytest.raises(httpx.ConnectError):
        with model_call("codex") as entry:
            entry["output_started"] = True
            raise httpx.ConnectError("later connection failed")
    assert diagnostics["stages"][0]["outcome"] == "unknown"
    assert diagnostics["stages"][0]["retryable"] is False


@pytest.mark.parametrize(
    "failure,kind",
    [
        (Exception("provider failed"), "model_response_invalid"),
        (asyncio.CancelledError("task stopped"), "cancelled"),
        (StreamStopped("consumer stopped"), "cancelled"),
        (KeyboardInterrupt(), None),
        (SystemExit(1), None),
        (GeneratorExit(), None),
    ],
)
def test_callback_failures_propagate_once_and_process_teardown_is_not_provider_failure(
    failure, kind
):
    diagnostics, calls = {}, []

    def invoke():
        calls.append(1)
        raise failure

    with scope(diagnostics), pytest.raises(type(failure)) as caught:
        call_with_retry(invoke, policy=RetryPolicy(max_attempts=4, base_delay=0, jitter=0))
    assert caught.value is failure
    assert calls == [1] and diagnostics["model_attempts"] == 1
    assert diagnostics["transport_retries"] == 0
    entry = diagnostics["stages"][0]
    assert entry.get("failure_kind") == kind
    assert entry["outcome"] == "unknown" and entry["elapsed_ms"] >= 0
    if kind is not None:
        assert entry["retryable"] is False


def test_sdk_transport_wrappers_do_not_make_unknown_reads_safe():
    request = httpx.Request("POST", "https://model.invalid")
    for cause, expected in [
        (httpx.ConnectError("before-send"), True),
        (httpx.ReadError("sent"), False),
    ]:
        error = APIConnectionError(request=request)
        error.__cause__ = cause
        assert is_safe_transport_retry(error) is expected
    wrapped = RuntimeError("application failure")
    wrapped.__cause__ = httpx.ConnectError("other-operation")
    assert not is_safe_transport_retry(wrapped)
    assert is_transport_error(httpx.ReadTimeout("unconfirmed"))
    assert not is_safe_transport_retry(httpx.ReadTimeout("unconfirmed"))


def test_persistent_attempt_limit_is_not_reset_by_retry_or_a_second_stage():
    diagnostics, calls = {}, []

    def invoke():
        calls.append(1)
        raise httpx.ConnectError("not sent")

    with scope(diagnostics, used=3), pytest.raises(ModelBudgetExceeded, match="call limit"):
        call_with_retry(invoke, policy=RetryPolicy(base_delay=0, jitter=0), stage="codex")
    with scope(diagnostics, used=4), pytest.raises(ModelBudgetExceeded, match="call limit"):
        call_with_retry(lambda: calls.append(2), policy=RetryPolicy(), stage="goal_review")
    assert calls == [1]
    assert diagnostics["model_attempts"] == 4
    assert diagnostics["exhausted"] == "model_call_limit"


@pytest.mark.asyncio
async def test_absolute_deadline_cancels_a_blocked_model_and_forbids_later_review():
    cancelled, diagnostics = asyncio.Event(), {}

    async def invoke():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    started = time.monotonic()
    with scope(diagnostics, seconds=0.05):
        with pytest.raises(ModelBudgetExceeded):
            await async_call_with_retry(invoke, policy=RetryPolicy(), stage="codex")
        with pytest.raises(ModelBudgetExceeded):
            with model_call("goal_review"):
                pytest.fail("deadline expired before review")
    assert cancelled.is_set()
    assert time.monotonic() - started < 0.5
    assert diagnostics["model_attempts"] == 1
    assert diagnostics["stages"][0]["failure_kind"] == "deadline_exceeded"
    assert diagnostics["stages"][0]["outcome"] == "unknown"


def test_cancellation_between_attempts_prevents_dispatch():
    stopped, calls, diagnostics = [], [], {}

    def invoke():
        calls.append(1)
        stopped.append(True)
        raise httpx.ConnectError("not sent")

    with scope(diagnostics, cancelled=lambda: bool(stopped)), pytest.raises(asyncio.CancelledError):
        call_with_retry(invoke, policy=RetryPolicy(base_delay=0, jitter=0))
    assert calls == [1]
    assert diagnostics["model_attempts"] == 1


@pytest.mark.parametrize(
    "status,kind",
    [(429, "rate_limited"), (403, "model_admission_denied"), (503, "provider_unavailable")],
)
def test_diagnostics_keep_root_status_without_promoting_it_to_replay_authority(status, kind):
    response = httpx.Response(status, request=httpx.Request("POST", "https://model.invalid"))
    error = httpx.HTTPStatusError(
        "private provider detail", request=response.request, response=response
    )
    details = model_failure_details(error, stage="goal_review", attempt=3, elapsed_ms=12.3)
    assert details["http_status"] == status
    assert details["failure_kind"] == kind
    assert details["failure_reason"]
    assert details["stage"] == "goal_review" and details["attempt"] == 3
    assert details["retryable"] is False and details["outcome"] == "unknown"
    assert "private provider detail" not in json.dumps(details)
