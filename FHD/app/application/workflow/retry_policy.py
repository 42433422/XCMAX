"""有界重试策略：统一模型调用的退避与上限。

只用于幂等的模型请求（计划生成）。步骤级重试仍由 ``RunRepair`` 按幂等台账
控制，两者语义不同，不能合并，否则会破坏已写入业务台账的步骤。
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

_ENV_MODEL_RETRIES = "XCAGI_PLAN_MODEL_RETRIES"
_RETRYABLE = (OSError, httpx.NetworkError, httpx.TimeoutException, httpx.RemoteProtocolError)
_TRANSPORT_RETRY_SCOPE: ContextVar[bool] = ContextVar("planner_transport_retry", default=False)


def retry_manages_transport_error(error: Exception) -> bool:
    return _TRANSPORT_RETRY_SCOPE.get() and isinstance(error, _RETRYABLE)


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
    token = _TRANSPORT_RETRY_SCOPE.set(True)
    try:
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except retry_on as exc:
                # An explicit retry tuple may narrow, never broaden, the safe set.
                if not isinstance(exc, _RETRYABLE) or attempt >= attempts:
                    raise
                delay = policy.delay_for(attempt)
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


__all__ = ["RetryPolicy", "call_with_retry", "planner_retry_policy"]
