"""Transport classification and bounded diagnostics for existing execution owners."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from openai import APIConnectionError

from app.infrastructure.chat_stream_lifetime import StreamStopped

_SAFE_TRANSPORT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def is_safe_transport_retry(error: BaseException) -> bool:
    """Only connection/pool failures prove the model request was not sent.

    The SDK may wrap its own HTTPX family. Unwrap only that SDK exception, never
    arbitrary application errors. Read/write timeouts, protocol errors, generic
    timeouts and HTTP 5xx do not establish a known, unexecuted request.
    """
    cause = error
    if type(error).__module__.split(".")[0] == "openai" and type(error).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
    }:
        cause = error.__cause__ or error
    return isinstance(cause, _SAFE_TRANSPORT) or (
        type(cause).__module__.split(".")[0] == "httpx2"
        and type(cause).__name__ in {"ConnectError", "ConnectTimeout", "PoolTimeout"}
    )


def is_transport_error(error: BaseException) -> bool:
    """Classify transport uncertainty; this never grants retry permission."""
    return isinstance(
        error,
        (
            OSError,
            httpx.NetworkError,
            httpx.TimeoutException,
            httpx.RemoteProtocolError,
            APIConnectionError,
        ),
    )


def _upstream_settlement_unresolved(error: BaseException) -> bool:
    """The market gateway refuses replay while it settles the original request.

    This proves the request was accepted upstream, so it must stay unknown:
    neither a retry nor a local zero-usage assumption is allowed.
    """
    response = getattr(error, "response", None)
    if response is None:
        return False
    try:
        text = str(getattr(response, "text", "") or "")
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False
    return "REQUEST_UNRESOLVED" in text or '"state":"settling"' in text.replace(" ", "")


def model_failure_details(
    error: BaseException,
    *,
    stage: str,
    attempt: int,
    elapsed_ms: float,
    output_started: bool = False,
    stream_phase: str | None = None,
    stream_frame: int | None = None,
) -> dict[str, Any]:
    """Return bounded root-cause evidence without exception text or credentials."""
    status = getattr(error, "status_code", None)
    if type(status) is not int:
        status = getattr(getattr(error, "response", None), "status_code", None)
    safe = is_safe_transport_retry(error) and not output_started
    if isinstance(error, (asyncio.CancelledError, StreamStopped)):
        kind, reason = "cancelled", "Task or response consumer cancelled the model call"
    elif safe:
        kind, reason = "transport_unavailable", "Connection failed before model request dispatch"
    elif status == 429:
        kind, reason = "rate_limited", "Provider rejected the model call with HTTP 429"
    elif status in {401, 402, 403}:
        kind, reason = "model_admission_denied", f"Provider rejected admission with HTTP {status}"
    elif type(status) is int and status >= 500:
        kind, reason = "provider_unavailable", f"Provider returned HTTP {status}"
    elif status == 409 and _upstream_settlement_unresolved(error):
        kind, reason = (
            "usage_unsettled",
            "Upstream is still settling the original request; replay is forbidden",
        )
    elif isinstance(error, (httpx.TransportError, TimeoutError, OSError)) or (
        type(error).__module__.split(".")[0] in {"httpx2", "openai"}
        and type(error).__name__ in {"APIConnectionError", "APITimeoutError", "ReadTimeout"}
    ):
        kind, reason = "transport_unknown", "Model request outcome could not be confirmed"
    else:
        kind, reason = "model_response_invalid", "Model response could not be accepted"
    details = {
        "stage": stage,
        "attempt": attempt,
        "elapsed_ms": round(elapsed_ms, 1),
        "failure_kind": kind,
        "failure_reason": reason,
        "error_type": type(error).__name__,
        "http_status": status if type(status) is int else None,
        "retryable": safe,
        "outcome": "not_started" if safe else "unknown",
        "output_started": output_started,
    }
    if stream_phase is not None:
        details["stream_phase"] = stream_phase
    if stream_frame is not None:
        details["stream_frame"] = stream_frame
    return details
