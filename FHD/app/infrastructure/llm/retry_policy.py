"""Bounded model transport retries within a host-owned, persistent task budget.

The caller restores the deadline and attempt count from the task repository.
This scope adds cooperative cancellation and diagnostics; it never creates a
task, changes the model, or treats an uncertain provider result as replayable.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from openai import APIConnectionError

from app.application.tool_execution_deadline import (
    check_invocation_deadline,
    invocation_deadline,
    remaining_invocation_seconds,
)
from app.infrastructure.chat_stream_lifetime import StreamStopped, check_stream_active
from app.utils.operational_errors import BOUNDARY_ERRORS

T = TypeVar("T")
_SAFE_TRANSPORT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_RETRY_ERRORS = (httpx.HTTPError, APIConnectionError)


class ModelBudgetExceeded(TimeoutError):
    def __init__(self, kind: str = "deadline_exceeded") -> None:
        self.kind = kind
        super().__init__(
            "Task model-call limit reached"
            if kind == "model_call_limit"
            else "Task model deadline exceeded"
        )


@dataclass
class ModelRequestBudget:
    max_calls: int
    attempts_used: int
    diagnostics: dict[str, Any]
    cancelled: Callable[[], bool] | None = None


_BUDGET: ContextVar[ModelRequestBudget | None] = ContextVar("model_request_budget", default=None)


def check_model_budget() -> None:
    budget = _BUDGET.get()
    if budget is not None and budget.cancelled is not None and budget.cancelled():
        raise asyncio.CancelledError("Task cancelled before model dispatch")
    check_stream_active()
    try:
        check_invocation_deadline()
    except TimeoutError as exc:
        if budget is not None:
            budget.diagnostics["exhausted"] = "deadline_exceeded"
        raise ModelBudgetExceeded() from exc


@contextmanager
def model_request_scope(
    *,
    deadline_at: float,
    max_calls: int,
    attempts_used: int,
    diagnostics: dict[str, Any],
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[ModelRequestBudget]:
    """Restore trusted UTC deadline/count; entering or retrying cannot renew them."""
    if (
        not math.isfinite(deadline_at)
        or type(max_calls) is not int
        or max_calls < 1
        or type(attempts_used) is not int
        or attempts_used < 0
    ):
        raise ValueError("Invalid trusted model budget")
    started = time.monotonic()
    deadline = started + max(0.0, deadline_at - time.time())
    diagnostics.setdefault("schema_version", 2)
    diagnostics.setdefault("transport_retries", 0)
    diagnostics.setdefault("stages", [])
    diagnostics["model_attempts"] = attempts_used
    diagnostics["deadline_at"] = deadline_at
    budget = ModelRequestBudget(max_calls, attempts_used, diagnostics, cancelled)
    token = _BUDGET.set(budget)
    try:
        with invocation_deadline(deadline):
            yield budget
    finally:
        diagnostics["elapsed_ms"] = round(
            float(diagnostics.get("elapsed_ms", 0)) + (time.monotonic() - started) * 1000, 1
        )
        _BUDGET.reset(token)


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


def model_failure_details(
    error: BaseException,
    *,
    stage: str,
    attempt: int,
    elapsed_ms: float,
    output_started: bool = False,
) -> dict[str, Any]:
    """Return bounded root-cause evidence without exception text or credentials."""
    status = getattr(error, "status_code", None)
    if type(status) is not int:
        status = getattr(getattr(error, "response", None), "status_code", None)
    safe = is_safe_transport_retry(error) and not output_started
    if isinstance(error, (asyncio.CancelledError, StreamStopped)):
        kind, reason = "cancelled", "Task or response consumer cancelled the model call"
    elif isinstance(error, ModelBudgetExceeded):
        kind, reason = error.kind, str(error)
    elif safe:
        kind, reason = "transport_unavailable", "Connection failed before model request dispatch"
    elif status == 429:
        kind, reason = "rate_limited", "Provider rejected the model call with HTTP 429"
    elif status in {401, 402, 403}:
        kind, reason = "model_admission_denied", f"Provider rejected admission with HTTP {status}"
    elif type(status) is int and status >= 500:
        kind, reason = "provider_unavailable", f"Provider returned HTTP {status}"
    elif isinstance(error, (httpx.TransportError, TimeoutError, OSError)) or (
        type(error).__module__.split(".")[0] in {"httpx2", "openai"}
        and type(error).__name__ in {"APIConnectionError", "APITimeoutError", "ReadTimeout"}
    ):
        kind, reason = "transport_unknown", "Model request outcome could not be confirmed"
    else:
        kind, reason = "model_response_invalid", "Model response could not be accepted"
    return {
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


@contextmanager
def model_call(stage: str) -> Iterator[dict[str, Any]]:
    """Record each physical attempt, including failed and cancelled attempts."""
    check_model_budget()
    budget = _BUDGET.get()
    if budget is not None:
        if budget.attempts_used >= budget.max_calls:
            budget.diagnostics["exhausted"] = "model_call_limit"
            raise ModelBudgetExceeded("model_call_limit")
        budget.attempts_used += 1
        budget.diagnostics["model_attempts"] = budget.attempts_used
    entry: dict[str, Any] = {
        "stage": stage,
        "attempt": budget.attempts_used if budget else 1,
        "outcome": "unknown",
    }
    if budget is not None:
        budget.diagnostics["stages"].append(entry)
    started = time.monotonic()
    try:
        yield entry
        check_model_budget()
        entry["outcome"] = "returned"
    except BOUNDARY_ERRORS + (asyncio.CancelledError,) as exc:
        # Provider boundary: record and re-raise; process teardown bypasses diagnostics.
        entry.update(
            model_failure_details(
                exc,
                stage=stage,
                attempt=entry["attempt"],
                elapsed_ms=(time.monotonic() - started) * 1000,
                output_started=entry.get("output_started") is True,
            )
        )
        raise
    finally:
        entry["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay: float = 0.2
    max_delay: float = 2.0
    jitter: float = 0.1

    def delay_for(self, attempt: int) -> float:
        raw = self.base_delay * 2 ** max(0, attempt - 1)
        return float(max(0.0, min(self.max_delay, raw + random.uniform(0, max(0.0, self.jitter)))))


def _retry_delay(error: Exception, attempt: int, policy: RetryPolicy) -> float:
    if not is_safe_transport_retry(error) or attempt >= max(1, min(4, policy.max_attempts)):
        raise error
    check_model_budget()
    delay = policy.delay_for(attempt)
    if delay >= remaining_invocation_seconds(math.inf):
        raise ModelBudgetExceeded() from error
    budget = _BUDGET.get()
    if budget is not None:
        budget.diagnostics["transport_retries"] += 1
    return delay


def call_with_retry(fn: Callable[[], T], *, policy: RetryPolicy, stage: str = "model") -> T:
    for attempt in range(1, max(1, min(4, policy.max_attempts)) + 1):
        try:
            with model_call(stage):
                return fn()
        except _RETRY_ERRORS as exc:
            delay = _retry_delay(exc, attempt, policy)
            while delay > 0:
                check_model_budget()
                interval = min(0.05, delay)
                time.sleep(interval)
                delay -= interval
    raise RuntimeError("Model retry policy did not execute")


async def async_call_with_retry(
    fn: Callable[[], Awaitable[T]], *, policy: RetryPolicy, stage: str = "model"
) -> T:
    for attempt in range(1, max(1, min(4, policy.max_attempts)) + 1):
        try:
            with model_call(stage):
                remaining = remaining_invocation_seconds(math.inf)
                deadline = asyncio.timeout(remaining if math.isfinite(remaining) else None)
                try:
                    async with deadline:
                        return await fn()
                except TimeoutError as exc:
                    if deadline.expired():
                        raise ModelBudgetExceeded() from exc
                    raise
        except _RETRY_ERRORS as exc:
            delay = _retry_delay(exc, attempt, policy)
            while delay > 0:
                check_model_budget()
                interval = min(0.05, delay)
                await asyncio.sleep(interval)
                delay -= interval
    raise RuntimeError("Model retry policy did not execute")
