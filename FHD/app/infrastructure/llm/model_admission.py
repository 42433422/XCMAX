"""Per-account admission controls for platform model calls."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

import httpx
from openai import APIConnectionError
from starlette.exceptions import HTTPException

from app.domain.model_admission_errors import (
    ModelCircuitOpenError,
    ModelConcurrencyLimitError,
    ModelRateLimitError,
)
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
_MODEL_CONCURRENCY_IDENTITY: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "xcagi_model_concurrency_identity", default=None
)
_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.:@-]")
_MODEL_GATE_LOCK = threading.Lock()
_MODEL_INFLIGHT = 0
_MODEL_ROUTE_INFLIGHT: dict[str, int] = {}
_MODEL_ACTOR_INFLIGHT: dict[str, int] = {}


@dataclass
class _ModelCircuit:
    failures: int = 0
    opened_at: float = 0.0
    probing: bool = False
    generation: int = 0
    inflight: int = 0


_MODEL_BREAKERS: dict[str, _ModelCircuit] = {}


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
    bound_identity = _limit_identity(context)
    identity = bound_identity or _MODEL_IDENTITY.get()
    tenant = _limit_tenant(context) or _MODEL_TENANT.get()
    local_user = context.get("local_user_id") if isinstance(context, Mapping) else None
    # Local users have host-wide IDs; other actors keep their tenant namespace.
    concurrency_identity = (
        _SAFE_KEY.sub("_", f"local-user:{local_user}")[:180]
        if local_user not in (None, "")
        else bound_identity
    ) or _MODEL_CONCURRENCY_IDENTITY.get()
    token = _MODEL_IDENTITY.set(identity)
    tenant_token = _MODEL_TENANT.set(tenant)
    concurrency_token = _MODEL_CONCURRENCY_IDENTITY.set(concurrency_identity)
    try:
        yield
    finally:
        _MODEL_CONCURRENCY_IDENTITY.reset(concurrency_token)
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


def _route_key(provider: Any, model: str | None) -> str:
    """Keep model namespaces distinct without retaining endpoints in gate keys."""
    for _ in range(8):
        inner = getattr(provider, "_inner", None)
        if inner is None or inner is provider:
            break
        provider = inner
    adapter = getattr(provider, "_adapter", None)
    sdk_endpoint = ""
    sdk_provider = provider is None or getattr(provider, "provider_id", "") == "openai_sdk"
    if sdk_provider:
        from app.infrastructure.llm.client import _scoped_client, resolve_chat_model

        scoped = _scoped_client.get()
        if scoped is not None and scoped[1] is None:
            # A lazy factory has no route identity yet. Do not instantiate it
            # for observation: its first call uses a conservative shared bucket.
            sdk_endpoint = "unresolved_scoped_client"
        elif scoped is not None:
            model = model or scoped[1]
            client = scoped[0]
            sdk_endpoint = str(getattr(client, "base_url", "") or "")
            if getattr(client, "is_modstore_openai_compatible", False) is True:
                adapter = client.adapter
                sdk_endpoint = str(getattr(adapter, "platform_url", "") or "")
        elif not model:
            # No request factory is present; this reads the configured model.
            model = resolve_chat_model()
    if not model:
        for source in (adapter, provider):
            model = next(
                (
                    value
                    for attr in ("model_name", "_model", "model")
                    if isinstance(value := getattr(source, attr, None), str) and value
                ),
                None,
            )
            if model:
                break
    identity = (
        str(getattr(provider, "provider_id", "shared") or "shared"),
        str(model or "default"),
        str(
            getattr(provider, "route_identity", "")
            or sdk_endpoint
            or getattr(adapter, "_base_url", "")
            or getattr(adapter, "platform_url", "")
            or getattr(provider, "_api_url", "")
        ),
    )
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


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
    # These are host responses (including FastAPI subclasses), not transport
    # receipts. A local task deadline, budget or storage refusal is neutral.
    if isinstance(exc, HTTPException):
        return False
    cause = exc.__cause__ if isinstance(exc, APIConnectionError) and exc.__cause__ else exc
    # Pool exhaustion, permission errors and local storage failures say nothing
    # about model health. Cancellation likewise must not reset a failure streak.
    if isinstance(cause, httpx.PoolTimeout) or type(cause).__name__ == "PoolTimeout":
        return False
    if isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            httpx.NetworkError,
            httpx.TimeoutException,
            httpx.RemoteProtocolError,
            APIConnectionError,
        ),
    ):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in {408, 425, 429} or status >= 500
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and (status in {408, 425, 429} or status >= 500)


@contextmanager
def model_call_slot(
    provider: Any,
    *,
    profile: str = "default",
    model: str | None = None,
    kwargs: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    """Bound global/route capacity and isolate model failures within each account."""
    del profile  # Planning, chat and repair share the selected model's health.
    global _MODEL_INFLIGHT
    route_key = _route_key(provider, model)
    key = f"{_provider_identity(provider, kwargs)}:route:{route_key}"
    concurrency, threshold, cooldown = _model_gate_limits()
    try:
        route_limit = max(
            1, min(concurrency, int(os.environ.get("XCAGI_MODEL_MAX_INFLIGHT_PER_MODEL", "8")))
        )
    except ValueError:
        route_limit = min(8, concurrency)
    try:
        actor_limit = int(os.environ.get("XCAGI_MODEL_MAX_INFLIGHT_PER_ACTOR", "4"))
    except ValueError:
        actor_limit = 4
    # Keep room for another actor when capacity permits. A capacity-one model
    # remains serial. The actor total also spans routes to protect global slots.
    actor_limit = max(1, min(actor_limit, concurrency - 1, route_limit - 1))
    # Request kwargs/provider metadata are not an authenticated actor binding.
    actor = _MODEL_CONCURRENCY_IDENTITY.get() or "anonymous"
    now = time.monotonic()
    with _MODEL_GATE_LOCK:
        circuit = _MODEL_BREAKERS.get(key) or _ModelCircuit()
        probe = circuit.failures >= threshold
        if probe and (now - circuit.opened_at < cooldown or circuit.probing):
            raise ModelCircuitOpenError(max(1, int(cooldown - (now - circuit.opened_at))))
        route_inflight = _MODEL_ROUTE_INFLIGHT.get(route_key, 0)
        actor_inflight = _MODEL_ACTOR_INFLIGHT.get(actor, 0)
        if (
            concurrency <= _MODEL_INFLIGHT
            or route_limit <= route_inflight
            or actor_limit <= actor_inflight
        ):
            raise ModelConcurrencyLimitError()
        if key not in _MODEL_BREAKERS and len(_MODEL_BREAKERS) >= 10_000:
            expired = next(
                (
                    old_key
                    for old_key, old in _MODEL_BREAKERS.items()
                    if not old.inflight and now - old.opened_at >= cooldown
                ),
                None,
            )
            if expired is None:
                raise ModelConcurrencyLimitError()
            _MODEL_BREAKERS.pop(expired)
        _MODEL_BREAKERS[key] = circuit
        circuit.probing = probe
        generation = circuit.generation
        circuit.inflight += 1
        _MODEL_INFLIGHT += 1
        _MODEL_ROUTE_INFLIGHT[route_key] = route_inflight + 1
        _MODEL_ACTOR_INFLIGHT[actor] = actor_inflight + 1
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        exc = sys.exc_info()[1] if not succeeded else None
        with _MODEL_GATE_LOCK:
            _MODEL_INFLIGHT = max(0, _MODEL_INFLIGHT - 1)
            for counts, identity in (
                (_MODEL_ROUTE_INFLIGHT, route_key),
                (_MODEL_ACTOR_INFLIGHT, actor),
            ):
                remaining = counts[identity] - 1
                if remaining:
                    counts[identity] = remaining
                else:
                    counts.pop(identity, None)
            circuit.inflight -= 1
            if _MODEL_BREAKERS.get(key) is circuit and generation == circuit.generation:
                circuit.probing = False
                if succeeded:
                    circuit.failures = 0
                    if probe:
                        circuit.generation += 1
                elif exc is not None and _is_transient_provider_failure(exc):
                    circuit.failures += 1
                    if circuit.failures >= threshold:
                        circuit.opened_at = time.monotonic()
                        circuit.generation += 1
            if (
                _MODEL_BREAKERS.get(key) is circuit
                and not circuit.failures
                and not circuit.inflight
            ):
                _MODEL_BREAKERS.pop(key, None)


def admit_model_call(
    provider: Any,
    *,
    profile: str = "default",
    kwargs: Mapping[str, Any] | None = None,
) -> None:
    """Apply per-actor and per-tenant quotas before network I/O."""
    _ = profile  # One account quota spans planning, chat, memory, and repair calls.
    try:
        actor_limit = max(1, min(600, int(os.environ.get("XCAGI_MODEL_CALLS_PER_MINUTE", "60"))))
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
    def _xcagi_instrumented(self) -> bool:
        return bool(getattr(self._inner, "_xcagi_instrumented", False))

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    @property
    def is_configured(self) -> bool:
        return bool(self._inner.is_configured)

    @property
    def supports_streaming(self) -> bool:
        from app.infrastructure.llm.response_completion import provider_supports_streaming

        return provider_supports_streaming(self._inner)

    async def chat_completion(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        with model_call_slot(self._inner, model=kwargs.get("model"), kwargs=kwargs):
            admit_model_call(self._inner, kwargs=kwargs)
            return await self._inner.chat_completion(messages, **kwargs)

    @property
    def stream_chat_completion(self) -> Callable[..., AsyncIterator[str]] | None:
        """Preserve the inner provider's optional streaming capability."""
        if not callable(getattr(self._inner, "stream_chat_completion", None)):
            return None
        return self._stream_chat_completion

    async def _stream_chat_completion(self, messages: list[dict[str, Any]], **kwargs: Any):
        stream = getattr(self._inner, "stream_chat_completion", None)
        if stream is None:
            return
        with model_call_slot(self._inner, model=kwargs.get("model"), kwargs=kwargs):
            admit_model_call(self._inner, kwargs=kwargs)
            async for delta in stream(messages, **kwargs):
                yield delta


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
