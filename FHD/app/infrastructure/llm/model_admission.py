"""Per-account admission controls for platform model calls."""

from __future__ import annotations

import contextvars
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from app.utils.resilience.rate_limiter import (
    RateLimitBackendError,
    check_rate_limit,
    ensure_rate_limit_backend,
)

_MODEL_IDENTITY: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "xcagi_model_rate_limit_identity", default=None
)
_MODEL_TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "xcagi_model_rate_limit_tenant", default=None
)
_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.:@-]")
_MODEL_GATE_LOCK = threading.Lock()
_MODEL_INFLIGHT = 0
_MODEL_BREAKERS: dict[str, tuple[int, float, bool]] = {}


class ModelRateLimitError(RuntimeError):
    """A model request was refused before contacting the configured provider."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("当前账户模型请求过于频繁，请稍后重试。")
        self.code = "model_rate_limited"
        self.retry_after = max(1, int(retry_after))


class ModelConcurrencyLimitError(RuntimeError):
    """The process-wide model concurrency budget is full."""

    def __init__(self, retry_after: int = 1) -> None:
        super().__init__("模型并发请求已达上限，请稍后重试。")
        self.code = "model_concurrency_limited"
        self.retry_after = max(1, int(retry_after))


class ModelCircuitOpenError(RuntimeError):
    """Repeated provider failures temporarily opened its circuit."""

    def __init__(self, retry_after: int = 30) -> None:
        super().__init__("模型服务连续失败，已暂时熔断，请稍后重试。")
        self.code = "model_circuit_open"
        self.retry_after = max(1, int(retry_after))


def _limit_identity(context: Mapping[str, Any] | None) -> str | None:
    if not isinstance(context, Mapping):
        return None
    owner = context.get("local_user_id") or context.get("actor_id")
    if owner in (None, ""):
        return None
    tenant = context.get("tenant_id") or "unscoped"
    # Values only select a quota bucket; they never authorize provider access.
    raw = f"tenant:{tenant}:actor:{owner}"
    return _SAFE_KEY.sub("_", raw)[:180]


def _limit_tenant(context: Mapping[str, Any] | None) -> str | None:
    if not isinstance(context, Mapping) or context.get("tenant_id") in (None, ""):
        return None
    return _SAFE_KEY.sub("_", f"tenant:{context['tenant_id']}")[:120]


@contextmanager
def model_rate_limit_scope(context: Mapping[str, Any] | None) -> Iterator[None]:
    """Bind the authenticated chat/tool actor across nested model calls."""
    identity = _limit_identity(context) or _MODEL_IDENTITY.get()
    tenant = _limit_tenant(context) or _MODEL_TENANT.get()
    token = _MODEL_IDENTITY.set(identity)
    tenant_token = _MODEL_TENANT.set(tenant)
    try:
        yield
    finally:
        _MODEL_TENANT.reset(tenant_token)
        _MODEL_IDENTITY.reset(token)


def _provider_identity(provider: Any, kwargs: Mapping[str, Any] | None = None) -> str:
    identity = _MODEL_IDENTITY.get()
    if identity:
        return identity
    values = kwargs if isinstance(kwargs, Mapping) else {}
    tenant = values.get("tenant_id")
    owner = values.get("user_id") or values.get("local_user_id")
    adapter = getattr(provider, "_adapter", None)
    owner = owner or getattr(adapter, "user_id", None)
    if owner not in (None, ""):
        return _SAFE_KEY.sub("_", f"tenant:{tenant or 'unscoped'}:actor:{owner}")[:180]
    return f"provider:{str(getattr(provider, 'provider_id', 'shared') or 'shared')[:80]}"


def _circuit_key(provider: Any) -> str:
    identity = _MODEL_IDENTITY.get() or _provider_identity(provider)
    provider_id = str(getattr(provider, "provider_id", "shared") or "shared")[:80]
    return f"{identity}:provider:{_SAFE_KEY.sub('_', provider_id)}"


def _model_gate_limits() -> tuple[int, int, float]:
    try:
        concurrency = max(1, min(1000, int(os.environ.get("XCAGI_MODEL_MAX_INFLIGHT", "32"))))
    except ValueError:
        concurrency = 32
    try:
        threshold = max(1, min(100, int(os.environ.get("XCAGI_MODEL_BREAKER_THRESHOLD", "5"))))
    except ValueError:
        threshold = 5
    try:
        cooldown = max(
            1.0,
            min(600.0, float(os.environ.get("XCAGI_MODEL_BREAKER_COOLDOWN", "30"))),
        )
    except ValueError:
        cooldown = 30.0
    return concurrency, threshold, cooldown


def _is_transient_provider_failure(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in {408, 425, 429} or status >= 500
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and (status in {408, 425, 429} or status >= 500)


@contextmanager
def model_call_slot(provider: Any, *, profile: str = "default") -> Iterator[None]:
    """Bound concurrent provider calls and open a short circuit after repeated faults."""
    del profile  # The breaker is shared by a user's calls to the same provider.
    global _MODEL_INFLIGHT
    key = _circuit_key(provider)
    concurrency, threshold, cooldown = _model_gate_limits()
    now = time.monotonic()
    with _MODEL_GATE_LOCK:
        failures, opened_at, probing = _MODEL_BREAKERS.get(key, (0, 0.0, False))
        if failures >= threshold:
            if now - opened_at < cooldown or probing:
                raise ModelCircuitOpenError(max(1, int(cooldown - (now - opened_at))))
            _MODEL_BREAKERS[key] = (failures, opened_at, True)
        if _MODEL_INFLIGHT >= concurrency:
            if failures >= threshold:
                _MODEL_BREAKERS[key] = (failures, opened_at, False)
            raise ModelConcurrencyLimitError()
        _MODEL_INFLIGHT += 1
    failed = False
    succeeded = False
    try:
        yield
    except BaseException as exc:
        failed = _is_transient_provider_failure(exc)
        raise
    else:
        succeeded = True
    finally:
        with _MODEL_GATE_LOCK:
            _MODEL_INFLIGHT = max(0, _MODEL_INFLIGHT - 1)
            failures, opened_at, _probing = _MODEL_BREAKERS.get(key, (0, 0.0, False))
            if succeeded or not failed:
                # Non-transient provider responses (for example an auth/config
                # error) prove connectivity and must end a prior transient streak.
                _MODEL_BREAKERS.pop(key, None)
            else:
                failures += 1
                opened_at = time.monotonic() if failures >= threshold else opened_at
                if failures or _probing:
                    _MODEL_BREAKERS[key] = (failures, opened_at, False)
                    if len(_MODEL_BREAKERS) > 10_000:
                        oldest = next(iter(_MODEL_BREAKERS))
                        if oldest != key:
                            _MODEL_BREAKERS.pop(oldest, None)


def admit_model_call(
    provider: Any,
    *,
    profile: str = "default",
    kwargs: Mapping[str, Any] | None = None,
) -> None:
    """Apply per-actor and per-tenant quotas before network I/O."""
    _ = profile  # One account quota spans planning, chat, memory, and repair calls.
    try:
        actor_limit = max(
            1, min(600, int(os.environ.get("XCAGI_MODEL_CALLS_PER_MINUTE", "60")))
        )
    except ValueError:
        actor_limit = 60
    try:
        tenant_limit = max(
            1,
            min(10000, int(os.environ.get("XCAGI_TENANT_MODEL_CALLS_PER_MINUTE", "600"))),
        )
    except ValueError:
        tenant_limit = 600
    try:
        ensure_rate_limit_backend()
        identity = _MODEL_IDENTITY.get()
        tenant = _MODEL_TENANT.get()
        if identity:
            actor_admission = check_rate_limit(
                identity,
                "llm:model_calls:actor",
                max_requests=actor_limit,
                window_seconds=60,
            )
            if not actor_admission.get("allowed", True):
                raise ModelRateLimitError(actor_admission.get("retry_after") or 60)
        if tenant:
            tenant_admission = check_rate_limit(
                tenant,
                "llm:model_calls:tenant",
                max_requests=tenant_limit,
                window_seconds=60,
            )
            if not tenant_admission.get("allowed", True):
                raise ModelRateLimitError(tenant_admission.get("retry_after") or 60)
        if not identity and not tenant:
            account_admission = check_rate_limit(
                _provider_identity(provider, kwargs),
                "llm:model_calls:account",
                max_requests=tenant_limit,
                window_seconds=60,
            )
            if not account_admission.get("allowed", True):
                raise ModelRateLimitError(account_admission.get("retry_after") or 60)
    except RateLimitBackendError:
        raise


class RateLimitedProvider:
    """Keep provider selection intact while enforcing a common call quota."""

    _xcagi_rate_limited = True

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    @property
    def is_configured(self) -> bool:
        return bool(self._inner.is_configured)

    async def chat_completion(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        with model_call_slot(self._inner):
            admit_model_call(self._inner, kwargs=kwargs)
            return await self._inner.chat_completion(messages, **kwargs)


def rate_limit_provider(provider: Any) -> Any:
    if provider is None or getattr(provider, "_xcagi_rate_limited", False):
        return provider
    return RateLimitedProvider(provider)


__all__ = [
    "ModelRateLimitError",
    "ModelConcurrencyLimitError",
    "ModelCircuitOpenError",
    "admit_model_call",
    "model_rate_limit_scope",
    "model_call_slot",
    "rate_limit_provider",
]
