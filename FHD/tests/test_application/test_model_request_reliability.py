"""Transport classification contracts used by the model gateway, MCP and executor."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from app.infrastructure.chat_stream_lifetime import StreamObservationTimeout, StreamStopped
from app.infrastructure.llm.retry_policy import (
    is_safe_transport_retry,
    is_transport_error,
    model_failure_details,
)


@pytest.mark.parametrize("failure", ["ConnectError", "ConnectTimeout", "PoolTimeout"])
def test_connection_failure_is_known_not_started_without_exposing_provider_details(failure):
    error = getattr(httpx, failure)("private-host-name")
    assert is_safe_transport_retry(error)
    details = model_failure_details(error, stage="codex.responses", attempt=3, elapsed_ms=12.34)
    assert details["retryable"] is True and details["outcome"] == "not_started"
    assert details["failure_kind"] == "transport_unavailable"
    assert details["stage"] == "codex.responses" and details["attempt"] == 3
    assert details["elapsed_ms"] == 12.3 and details["output_started"] is False
    assert "private-host-name" not in json.dumps(details)


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
def test_unconfirmed_output_has_no_replay_authority(failure):
    error = failure("unconfirmed-response")
    assert is_transport_error(error) and not is_safe_transport_retry(error)
    details = model_failure_details(error, stage="codex.responses", attempt=1, elapsed_ms=12.3)
    assert details["retryable"] is False and details["outcome"] == "unknown"
    assert details["failure_kind"] == "transport_unknown"
    assert "unconfirmed-response" not in json.dumps(details)


@pytest.mark.parametrize("wrapper", [None, APIConnectionError, APITimeoutError])
def test_output_started_remains_unknown_even_if_later_connection_error_is_wrapped(wrapper):
    error = httpx.ConnectError("later connection failed")
    if wrapper is not None:
        cause = error
        error = wrapper(request=httpx.Request("POST", "https://model.invalid"))
        error.__cause__ = cause
    assert is_safe_transport_retry(error)
    details = model_failure_details(
        error, stage="codex.responses", attempt=1, elapsed_ms=12.3, output_started=True
    )
    assert details["outcome"] == "unknown" and details["retryable"] is False
    assert details["failure_kind"] == "transport_unknown" and details["output_started"] is True


@pytest.mark.parametrize(
    "failure,kind",
    [
        (Exception("private provider failure"), "model_response_invalid"),
        (asyncio.CancelledError("private task stopped"), "cancelled"),
        (StreamStopped("private consumer stopped"), "cancelled"),
    ],
)
def test_provider_failure_and_cancellation_keep_bounded_diagnostics(failure, kind):
    details = model_failure_details(failure, stage="codex.responses", attempt=3, elapsed_ms=12.3)
    assert details["failure_kind"] == kind
    assert details["outcome"] == "unknown" and details["elapsed_ms"] == 12.3
    assert details["retryable"] is False and details["http_status"] is None
    assert details["stage"] == "codex.responses" and details["attempt"] == 3
    assert "private" not in json.dumps(details)


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), SystemExit(1), GeneratorExit()])
def test_process_teardown_is_not_a_retryable_transport_error(failure):
    assert not is_transport_error(failure)
    assert not is_safe_transport_retry(failure)


@pytest.mark.parametrize("wrapper", [APIConnectionError, APITimeoutError])
@pytest.mark.parametrize(
    "failure,safe",
    [
        ("ConnectError", True),
        ("ConnectTimeout", True),
        ("PoolTimeout", True),
        ("ReadError", False),
        ("ReadTimeout", False),
    ],
)
def test_sdk_transport_wrappers_only_grant_replay_for_unsent_requests(wrapper, failure, safe):
    error = wrapper(request=httpx.Request("POST", "https://model.invalid"))
    error.__cause__ = getattr(httpx, failure)("private provider detail")
    assert is_safe_transport_retry(error) is safe
    assert is_transport_error(error)
    details = model_failure_details(error, stage="codex.responses", attempt=1, elapsed_ms=12.3)
    assert details["retryable"] is safe
    assert details["outcome"] == ("not_started" if safe else "unknown")
    assert "private provider detail" not in json.dumps(details)


@pytest.mark.parametrize(
    "failure,safe",
    [
        ("ConnectError", True),
        ("ConnectTimeout", True),
        ("PoolTimeout", True),
        ("ReadTimeout", False),
    ],
)
def test_httpx2_compatibility_exception_names_do_not_require_the_optional_sdk(failure, safe):
    """A name-compatibility double, not evidence from an installed HTTPX2 transport."""
    error_type = type(failure, (Exception,), {"__module__": "httpx2"})
    cause = error_type("private provider detail")
    assert is_safe_transport_retry(cause) is safe
    wrapped = APIConnectionError(request=httpx.Request("POST", "https://model.invalid"))
    wrapped.__cause__ = cause
    assert is_safe_transport_retry(wrapped) is safe
    details = model_failure_details(wrapped, stage="codex.responses", attempt=1, elapsed_ms=12.3)
    assert details["retryable"] is safe
    assert details["outcome"] == ("not_started" if safe else "unknown")
    assert "private provider detail" not in json.dumps(details)


def test_application_wrapper_does_not_inherit_transport_retry_authority():
    wrapped = RuntimeError("private application failure")
    wrapped.__cause__ = httpx.ConnectError("other-operation")
    assert not is_safe_transport_retry(wrapped)
    assert not is_transport_error(wrapped)
    details = model_failure_details(wrapped, stage="codex.responses", attempt=1, elapsed_ms=12.3)
    assert details["retryable"] is False and details["outcome"] == "unknown"
    assert details["failure_kind"] == "model_response_invalid"
    assert "private application failure" not in json.dumps(details)


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, "model_admission_denied"),
        (402, "model_admission_denied"),
        (403, "model_admission_denied"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
        (503, "provider_unavailable"),
    ],
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
