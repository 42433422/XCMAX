"""有界重试策略：统一模型调用的退避与上限。

只用于幂等的模型请求（计划生成）。步骤级重试仍由 ``RunRepair`` 按幂等台账
控制，两者语义不同，不能合并，否则会破坏已写入业务台账的步骤。
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from openai import APIConnectionError

from app.infrastructure.modstore_transport import MarketModelError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_ENV_MODEL_RETRIES = "XCAGI_PLAN_MODEL_RETRIES"
_RETRYABLE = (
    OSError,
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    APIConnectionError,
)
_TRANSPORT_RETRY_SCOPE: ContextVar[bool] = ContextVar("planner_transport_retry", default=False)


class PlanningBudgetExceeded(MarketModelError):
    """No further model call is allowed for this planning request."""

    def __init__(self, message: str) -> None:
        # Retain the existing public deadline contract and transport retry boundary.
        super().__init__({"status": 504}, code="model_deadline_exceeded")
        budget = _PLANNING_BUDGET.get()
        if budget is not None:
            budget.trace.setdefault("exhausted", "deadline")


@dataclass
class PlanningBudget:
    deadline: float
    max_calls: int
    trace: dict[str, Any] = field(
        default_factory=lambda: {
            "schema_version": 2,
            "model_attempts": 0,
            "transport_retries": 0,
            "stages": [],
        }
    )
    stage: str = "planning"


_PLANNING_BUDGET: ContextVar[PlanningBudget | None] = ContextVar("planning_budget", default=None)


def _bounded_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@contextmanager
def planning_request_scope(context: dict[str, Any]) -> Iterator[PlanningBudget]:
    """One trusted wall clock/call budget shared by planning, repair and review."""
    from app.application.tool_execution_deadline import invocation_deadline

    existing = _PLANNING_BUDGET.get()
    if existing is not None:
        context["planning_diagnostics"] = existing.trace
        yield existing
        return
    started = time.monotonic()
    timeout = _bounded_setting("XCAGI_PLAN_TIMEOUT_SECONDS", 180, 1, 600)
    with invocation_deadline(started + timeout) as invocation:
        budget = PlanningBudget(
            invocation.deadline, _bounded_setting("XCAGI_PLAN_MAX_MODEL_CALLS", 12, 1, 24)
        )
        context["planning_diagnostics"] = budget.trace
        token = _PLANNING_BUDGET.set(budget)
        try:
            yield budget
        finally:
            budget.trace["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
            _PLANNING_BUDGET.reset(token)


def planning_stage(stage: str) -> None:
    from app.infrastructure.chat_stream_lifetime import publish_stream_note

    budget = _PLANNING_BUDGET.get()
    if budget is not None:
        budget.stage = stage
    publish_stream_note(
        {
            "planning": "正在生成任务计划…",
            "repair": "正在校验并修复计划，尚未执行操作…",
            "coverage": "正在核对任务目标、条件和顺序…",
            "replanning": "正在根据核对结果修订计划，尚未执行操作…",
        }.get(stage, "正在核验计划…")
    )


def planner_call_timeout() -> float:
    from app.application.tool_execution_deadline import remaining_invocation_seconds

    limit = _bounded_setting("XCAGI_PLAN_CALL_TIMEOUT_SECONDS", 60, 1, 180)
    remaining = remaining_invocation_seconds(float(limit))
    if remaining <= 0:
        budget = _PLANNING_BUDGET.get()
        if budget is not None:
            budget.trace["exhausted"] = "deadline"
        raise PlanningBudgetExceeded("规划已达到等待时限，请重试原请求；本次未执行业务操作")
    return remaining


@contextmanager
def planning_model_call(stage: str | None = None) -> Iterator[PlanningBudget | None]:
    from app.application.tool_execution_deadline import invocation_deadline
    from app.infrastructure.chat_stream_lifetime import check_stream_active

    check_stream_active()
    budget = _PLANNING_BUDGET.get()
    if budget is None:
        yield None
        return
    if budget.trace["model_attempts"] >= budget.max_calls:
        budget.trace["exhausted"] = "model_call_limit"
        raise PlanningBudgetExceeded("规划已达到自动重试上限，请重试原请求；本次未执行业务操作")
    timeout = planner_call_timeout()
    budget.trace["model_attempts"] += 1
    entry: dict[str, Any] = {
        "stage": stage or budget.stage,
        "attempt": budget.trace["model_attempts"],
        "outcome": "error",
    }
    budget.trace["stages"].append(entry)
    started = time.monotonic()
    try:
        with invocation_deadline(started + timeout):
            yield budget
            planner_call_timeout()
            check_stream_active()
        entry["outcome"] = "returned"
    finally:
        entry["duration_ms"] = round((time.monotonic() - started) * 1000, 1)


def retry_manages_transport_error(error: Exception) -> bool:
    return _TRANSPORT_RETRY_SCOPE.get() and is_transport_error(error)


def is_transport_error(error: BaseException) -> bool:
    """该异常是否属于可重试的传输类错误（不依赖当前重试作用域）。"""
    return isinstance(error, _RETRYABLE) and not isinstance(
        error, (PlanningBudgetExceeded, PermissionError, FileNotFoundError)
    )


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay: float = 0.2
    max_delay: float = 2.0
    jitter: float = 0.1

    def delay_for(self, attempt: int) -> float:
        """第 ``attempt`` 次重试（从 1 开始）前的等待秒数。"""
        raw = self.base_delay * (2 ** max(0, int(attempt) - 1))
        bounded = min(self.max_delay, raw)
        return float(
            max(0.0, min(self.max_delay, bounded + random.uniform(0, max(0.0, self.jitter))))
        )


def planner_retry_policy() -> RetryPolicy:
    try:
        attempts = int(str(os.environ.get(_ENV_MODEL_RETRIES) or "2").strip())
    except ValueError:
        attempts = 2
    return RetryPolicy(max_attempts=max(1, min(4, attempts)))


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    retry_on: tuple[type[Exception], ...] = _RETRYABLE,
) -> T:
    """同步执行 ``fn``，可重试异常按策略退避；最后一次异常原样抛出。"""
    attempts = max(1, min(4, int(policy.max_attempts)))
    from app.application.tool_execution_deadline import (
        check_invocation_deadline,
        remaining_invocation_seconds,
    )
    from app.infrastructure.modstore_transport import MarketModelError

    token = _TRANSPORT_RETRY_SCOPE.set(True)
    try:
        for attempt in range(1, attempts + 1):
            from app.infrastructure.chat_stream_lifetime import check_stream_active

            check_stream_active()
            planner_call_timeout()
            try:
                check_invocation_deadline()
            except TimeoutError as exc:
                raise MarketModelError({"status": 504}, code="model_deadline_exceeded") from exc
            try:
                return fn()
            except retry_on as exc:
                # An explicit retry tuple may narrow, never broaden, the safe set.
                if not is_transport_error(exc) or attempt >= attempts:
                    raise
                delay = policy.delay_for(attempt)
                if remaining_invocation_seconds(delay + 0.001) <= delay:
                    raise MarketModelError({"status": 504}, code="model_deadline_exceeded") from exc
                remaining = planner_call_timeout()
                if delay >= remaining:
                    raise
                budget = _PLANNING_BUDGET.get()
                if budget is not None:
                    budget.trace["transport_retries"] += 1
                from app.infrastructure.chat_stream_lifetime import publish_stream_note

                publish_stream_note(f"模型连接暂时中断，正在重试（{attempt + 1}/{attempts}）…")
                logger.warning(
                    "模型调用失败，%0.2fs 后重试（%s/%s）：%s",
                    delay,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )
                time.sleep(delay)
        raise RuntimeError("重试策略未执行")
    finally:
        _TRANSPORT_RETRY_SCOPE.reset(token)


__all__ = ["RetryPolicy", "call_with_retry", "is_transport_error", "planner_retry_policy"]
