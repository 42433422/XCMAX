"""Request-local provider evidence, independent of plan decoding and retry count."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec

from app.infrastructure.observability.metrics import observe_plan_stage

P = ParamSpec("P")


@dataclass
class ResponseEvidence:
    outcome: str = "empty"
    duration_ms: float = 0


_evidence: ContextVar[ResponseEvidence | None] = ContextVar(
    "planner_response_evidence", default=None
)


def record_response_error() -> None:
    evidence = _evidence.get()
    if evidence is not None and evidence.outcome != "returned":
        evidence.outcome = "error"


@contextmanager
def model_response_scope() -> Iterator[None]:
    evidence = ResponseEvidence()
    token = _evidence.set(evidence)
    try:
        yield
    finally:
        _evidence.reset(token)
        observe_plan_stage(
            stage="model_returned", outcome=evidence.outcome, duration_ms=evidence.duration_ms
        )


def observe_model_response(
    fn: Callable[P, dict[str, Any] | None],
) -> Callable[P, dict[str, Any] | None]:
    @wraps(fn)
    def measured(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any] | None:
        started = perf_counter()
        completed = False
        try:
            response = fn(*args, **kwargs)
            completed = True
            evidence = _evidence.get()
            if evidence is not None and isinstance(response, dict):
                choices = response.get("choices")
                for choice in choices if isinstance(choices, list) else []:
                    message = choice.get("message") if isinstance(choice, dict) else None
                    if isinstance(message, dict) and (
                        message.get("content")
                        or message.get("tool_calls")
                        or message.get("function_call")
                    ):
                        evidence.outcome = "returned"
                        break
            return response
        finally:
            if not completed:
                record_response_error()
            evidence = _evidence.get()
            if evidence is not None:
                evidence.duration_ms += (perf_counter() - started) * 1000

    return measured
