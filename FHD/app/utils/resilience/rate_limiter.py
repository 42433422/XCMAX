"""
限流和熔断工具模块

提供基于 Redis（可选）或内存的请求限流和熔断机制。
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from contextlib import contextmanager
from threading import Lock
from typing import Any, cast

from app.utils.deployment import (
    distributed_rate_limit_required,
    env_flag,
    redis_url_from_env,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_redis_client: Any | None = None
_redis_init_attempted = False


class RateLimitBackendError(RuntimeError):
    """需要分布式限流后端（Redis）但其不可用时抛出。"""


class CircuitOpenError(RuntimeError):
    """熔断器处于 open 状态、拒绝调用时抛出（替代裸 Exception，便于精确捕获）。"""


def _fail_closed_without_redis() -> bool:
    """无 Redis 时是否「拒绝」（fail-closed）。

    仅当显式开启 ``XCAGI_REQUIRE_REDIS_RATE_LIMIT`` 才 fail-closed；默认 fail-open（回退内存限流），
    保持既有生产行为不变。
    """
    return env_flag("XCAGI_REQUIRE_REDIS_RATE_LIMIT")


class ToolConcurrencyLimitError(RuntimeError):
    """Per-process tool execution capacity is full; the call did not start."""


class ToolCircuitOpenError(RuntimeError):
    """A tool action has repeated transient faults and is temporarily blocked."""

    def __init__(self, retry_after: int = 30) -> None:
        super().__init__("Tool action circuit is open")
        self.retry_after = max(1, int(retry_after))


def _get_redis_client():
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    url = redis_url_from_env()
    if not url:
        return None
    try:
        import redis

        _redis_client = redis.from_url(url, decode_responses=True)
        _redis_client.ping()
        logger.info("Rate limiter using Redis backend")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Rate limiter Redis unavailable, using in-memory: %s", exc)
        _redis_client = None
    return _redis_client


class _InMemoryRateLimiter:
    """内存限流器（无 Redis 时使用）"""

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
        max_keys: int = 10000,
    ):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        # 限制追踪的 key 总数，避免长期运行下 _requests 无界增长导致内存泄漏。
        self._max_keys = max_keys
        self._requests: OrderedDict[str, list] = OrderedDict()
        self._lock = Lock()

    def _clean_old(self, key: str) -> None:
        now = time.time()
        cutoff = now - self._window_seconds
        self._requests[key] = [t for t in self._requests.get(key, []) if t > cutoff]
        if not self._requests[key]:
            del self._requests[key]

    def is_allowed(self, key: str) -> bool:
        with self._lock:
            self._clean_old(key)
            now = time.time()
            if key not in self._requests:
                # 容量上限：淘汰最久未活动的 key（OrderedDict 头部）。
                while len(self._requests) >= self._max_keys:
                    self._requests.popitem(last=False)
                self._requests[key] = []
            else:
                self._requests.move_to_end(key)
            if len(self._requests[key]) < self._max_requests:
                self._requests[key].append(now)
                return True
            return False

    def get_remaining(self, key: str) -> int:
        with self._lock:
            self._clean_old(key)
            return max(0, self._max_requests - len(self._requests.get(key, [])))

    def get_reset_time(self, key: str) -> float | None:
        with self._lock:
            self._clean_old(key)
            if key in self._requests and self._requests[key]:
                return cast("float | None", self._requests[key][0] + self._window_seconds)
            return None


class _RedisRateLimiter:
    """基于 Redis 的固定窗口计数（多副本共享）。"""

    def __init__(self, max_requests: int, window_seconds: int):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._redis = _get_redis_client()

    def _window_key(self, key: str) -> str:
        bucket = int(time.time()) // self._window_seconds
        return f"ratelimit:{key}:{bucket}"

    def is_allowed(self, key: str) -> bool:
        if self._redis is None:
            # 无 Redis：按 fail-closed/open 策略决定放行
            return not _fail_closed_without_redis()
        rk = self._window_key(key)
        try:
            pipe = self._redis.pipeline()
            pipe.incr(rk)
            pipe.expire(rk, self._window_seconds + 1)
            count, _ = pipe.execute()
            return int(count) <= self._max_requests
        except RECOVERABLE_ERRORS as exc:
            logger.warning("Rate limiter Redis request failed: %s", type(exc).__name__)
            if distributed_rate_limit_required():
                raise RateLimitBackendError("分布式限流 Redis 请求失败，已拒绝调用") from exc
            return True

    def get_remaining(self, key: str) -> int:
        if self._redis is None:
            return self._max_requests
        try:
            count = int(self._redis.get(self._window_key(key)) or 0)
        except RECOVERABLE_ERRORS:
            return 0
        return max(0, self._max_requests - count)

    def get_reset_time(self, key: str) -> float | None:
        now = time.time()
        bucket = int(now) // self._window_seconds
        return (bucket + 1) * self._window_seconds


class _CircuitBreaker:
    """熔断器实现"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._expected_exception = expected_exception
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._state = "closed"
        self._lock = Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open":
                if (
                    self._last_failure_time
                    and time.time() - self._last_failure_time > self._recovery_timeout
                ):
                    self._state = "half-open"
                    logger.info("Circuit breaker transitioning to half-open")
            return self._state

    def call(self, func, *args, **kwargs):
        if self.state == "open":
            raise CircuitOpenError("Circuit breaker is open")

        try:
            result = func(*args, **kwargs)
            with self._lock:
                if self._state == "half-open":
                    self._state = "closed"
                    self._failure_count = 0
                    logger.info("Circuit breaker closed after successful call")
            return result
        except self._expected_exception as e:
            with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.time()
                if self._failure_count >= self._failure_threshold:
                    self._state = "open"
                    logger.warning("Circuit breaker opened after %s failures", self._failure_count)
            raise e

    def reset(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failure_count = 0
            self._last_failure_time = None


_rate_limiters: dict[str, _InMemoryRateLimiter | _RedisRateLimiter] = {}
_circuit_breakers: dict[str, _CircuitBreaker] = {}
_limiter_lock = Lock()
_tool_gate_lock = Lock()
_tool_inflight = 0
_tool_inflight_by_tenant: dict[str, int] = {}
_tool_inflight_by_action: dict[str, int] = {}
_tool_breakers: OrderedDict[str, tuple[int, float, bool]] = OrderedDict()


def _tool_gate_limits() -> tuple[int, int, int, float]:
    try:
        concurrency = max(1, min(1000, int(os.environ.get("XCAGI_TOOL_MAX_INFLIGHT", "32"))))
    except ValueError:
        concurrency = 32
    try:
        per_tenant = max(
            1, min(concurrency, int(os.environ.get("XCAGI_TOOL_MAX_INFLIGHT_PER_TENANT", "16")))
        )
    except ValueError:
        per_tenant = min(concurrency, 16)
    try:
        threshold = max(1, min(100, int(os.environ.get("XCAGI_TOOL_BREAKER_THRESHOLD", "5"))))
    except ValueError:
        threshold = 5
    try:
        cooldown = max(1.0, min(600.0, float(os.environ.get("XCAGI_TOOL_BREAKER_COOLDOWN", "30"))))
    except ValueError:
        cooldown = 30.0
    return concurrency, per_tenant, threshold, cooldown


def _transient_tool_failure(result: Any = None, error: BaseException | None = None) -> bool:
    if error is not None:
        if isinstance(error, (TimeoutError, ConnectionError, OSError)):
            return True
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            return status in {408, 425, 429} or status >= 500
        response_status = getattr(getattr(error, "response", None), "status_code", None)
        return isinstance(response_status, int) and (
            response_status in {408, 425, 429} or response_status >= 500
        )
    if not isinstance(result, dict) or result.get("success") is True:
        return False
    code = str(result.get("error_code") or "")
    return code in {
        "tool_timeout_unknown",
        "tool_exception",
        "tool_exception_after_unknown_io",
        "tool_result_transport_failed",
        "tool_worker_incomplete",
        "tool_cleanup_failed",
        "tool_unavailable",
        "tool_upstream_failure",
        "upstream_unavailable",
        "service_unavailable",
        "model_circuit_open",
    }


@contextmanager
def tool_execution_slot(action_key: str, *, tenant_id: str = "shared"):
    """Limit in-process tool concurrency and circuit-break repeated transient faults.

    Distributed per-tenant/action rate quotas remain enforced by ``check_rate_limit``.
    This short-lived slot covers the whole isolated worker lifetime in the API process.
    """
    global _tool_inflight
    action = str(action_key or "unknown")[:160]
    tenant = str(tenant_id or "shared")[:120]
    key = f"{tenant}:{action}"[:240]
    concurrency, tenant_limit, threshold, cooldown = _tool_gate_limits()
    try:
        per_action_limit = max(
            1, min(concurrency, int(os.environ.get("XCAGI_TOOL_MAX_INFLIGHT_PER_ACTION", "8")))
        )
    except ValueError:
        per_action_limit = min(concurrency, 8)
    now = time.monotonic()
    with _tool_gate_lock:
        failures, opened_at, probing = _tool_breakers.get(key, (0, 0.0, False))
        if failures >= threshold:
            remaining = cooldown - (now - opened_at)
            if remaining > 0 or probing:
                raise ToolCircuitOpenError(max(1, int(remaining)))
            _tool_breakers[key] = (failures, opened_at, True)
        if (
            _tool_inflight >= concurrency
            or _tool_inflight_by_tenant.get(tenant, 0) >= tenant_limit
            or _tool_inflight_by_action.get(key, 0) >= per_action_limit
        ):
            if failures >= threshold:
                _tool_breakers[key] = (failures, opened_at, False)
            raise ToolConcurrencyLimitError("Tool execution capacity is full")
        _tool_inflight += 1
        _tool_inflight_by_tenant[tenant] = _tool_inflight_by_tenant.get(tenant, 0) + 1
        _tool_inflight_by_action[key] = _tool_inflight_by_action.get(key, 0) + 1
        _tool_breakers.move_to_end(key) if key in _tool_breakers else None
    result_seen = False
    result_success = False
    result_failure = False

    def report_result(result: Any) -> None:
        nonlocal result_seen, result_success, result_failure
        result_seen = True
        result_success = isinstance(result, dict) and result.get("success") is True
        result_failure = _transient_tool_failure(result=result)

    try:
        yield report_result
    except BaseException as exc:
        result_failure = _transient_tool_failure(error=exc)
        result_seen = True
        raise
    finally:
        with _tool_gate_lock:
            _tool_inflight = max(0, _tool_inflight - 1)
            tenant_remaining = _tool_inflight_by_tenant.get(tenant, 0) - 1
            if tenant_remaining <= 0:
                _tool_inflight_by_tenant.pop(tenant, None)
            else:
                _tool_inflight_by_tenant[tenant] = tenant_remaining
            remaining = _tool_inflight_by_action.get(key, 0) - 1
            if remaining <= 0:
                _tool_inflight_by_action.pop(key, None)
            else:
                _tool_inflight_by_action[key] = remaining
            if result_success:
                _tool_breakers.pop(key, None)
            elif result_failure:
                _record_tool_result_locked(key, True, threshold)
            elif result_seen:
                # A definitive upstream response proves the service is reachable;
                # only consecutive transient faults should keep the circuit open.
                _tool_breakers.pop(key, None)


def _record_tool_result_locked(action_key: str, failure: bool, threshold: int) -> None:
    if not failure:
        return
    failures, opened_at, _probing = _tool_breakers.get(action_key, (0, 0.0, False))
    failures += 1
    if failures >= threshold:
        opened_at = time.monotonic()
    _tool_breakers[action_key] = (failures, opened_at, False)
    _tool_breakers.move_to_end(action_key)
    while len(_tool_breakers) > 10_000:
        _tool_breakers.popitem(last=False)


def get_rate_limiter(
    name: str, max_requests: int = 100, window_seconds: int = 60
) -> _InMemoryRateLimiter | _RedisRateLimiter:
    with _limiter_lock:
        if name not in _rate_limiters:
            if _get_redis_client() is not None:
                _rate_limiters[name] = _RedisRateLimiter(max_requests, window_seconds)
            elif _fail_closed_without_redis():
                raise RateLimitBackendError(f"分布式限流后端不可用（Redis 缺失）: {name}")
            else:
                _rate_limiters[name] = _InMemoryRateLimiter(max_requests, window_seconds)
        return _rate_limiters[name]


def ensure_rate_limit_backend() -> None:
    """启动期校验：需要分布式限流但 Redis 不可用时抛 :class:`RateLimitBackendError`。

    桌面/测试等不要求分布式限流的形态直接放行。
    """
    if not distributed_rate_limit_required():
        return
    if _get_redis_client() is None:
        raise RateLimitBackendError("分布式限流要求 Redis 后端，但当前不可用")


def check_rate_limit(
    user_id: str, endpoint: str, max_requests: int = 100, window_seconds: int = 60
) -> dict[str, Any]:
    key = f"{endpoint}:{user_id}"
    limiter = get_rate_limiter(endpoint, max_requests, window_seconds)

    if limiter.is_allowed(key):
        return {
            "allowed": True,
            "remaining": limiter.get_remaining(key),
            "reset_time": limiter.get_reset_time(key),
            "retry_after": None,
        }
    reset_time = limiter.get_reset_time(key)
    retry_after = int(reset_time - time.time()) if reset_time else window_seconds
    return {
        "allowed": False,
        "remaining": 0,
        "reset_time": reset_time,
        "retry_after": retry_after,
    }


def get_circuit_breaker(
    name: str, failure_threshold: int = 5, recovery_timeout: int = 60
) -> _CircuitBreaker:
    with _limiter_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = _CircuitBreaker(failure_threshold, recovery_timeout)
        return _circuit_breakers[name]


def reset_circuit_breaker(name: str) -> None:
    with _limiter_lock:
        if name in _circuit_breakers:
            _circuit_breakers[name].reset()
