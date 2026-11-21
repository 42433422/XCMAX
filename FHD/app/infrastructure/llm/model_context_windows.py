"""Request-scoped model limits; the offline fallback is sourced from LiteLLM (MIT)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "ModelLimits",
    "ModelOutputLimitExceeded",
    "context_window_for",
    "load_catalog",
    "model_for_budget",
    "reset_cache",
    "resolve_model_limits",
    "resolve_token_budget",
]

_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "model_context_windows.json"
_DEFAULT_WINDOW = 16384
_DEFAULT_MARGIN = 256
_LIMIT_FIELDS = ("context_window", "max_input_tokens", "max_output_tokens")


def _tokens(value: Any, name: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise ValueError(f"{name} must be a {'non-negative' if allow_zero else 'positive'} integer")
    return value


class ModelOutputLimitExceeded(ValueError):
    """The requested output exceeds a known model limit; do not silently change it."""


@dataclass(frozen=True)
class ModelLimits:
    model: str | None = None
    context_window: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    source: str = "unknown"
    resolved_model: str | None = None
    safety_margin_tokens: int = _DEFAULT_MARGIN
    input_ceiling: int | None = None
    request_guard: Callable[[], None] | None = field(default=None, repr=False, compare=False)
    request_options: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (*_LIMIT_FIELDS, "input_ceiling"):
            value = getattr(self, name)
            if value is not None:
                _tokens(value, name)
        _tokens(self.safety_margin_tokens, "safety_margin_tokens", allow_zero=True)

    def assert_current(self) -> None:
        """Recheck request ownership after compression awaits and before provider I/O."""
        if self.request_guard is not None:
            self.request_guard()

    def input_budget(self, output_tokens: int = 0, external_tokens: int = 0) -> int:
        """Remaining message budget after actual output, tools and one safety margin.

        Input-only limits do not include output. A total context limit does.
        ``external_tokens`` is request content not already counted in messages.
        """
        _tokens(output_tokens, "output_tokens", allow_zero=True)
        _tokens(external_tokens, "external_tokens", allow_zero=True)
        if self.max_output_tokens is not None and output_tokens > self.max_output_tokens:
            raise ModelOutputLimitExceeded(
                f"Requested output {output_tokens} exceeds {self.model!r} limit "
                f"{self.max_output_tokens}"
            )
        bounds = []
        if self.context_window is not None:
            bounds.append(self.context_window - output_tokens)
        if self.max_input_tokens is not None:
            bounds.append(self.max_input_tokens)
        if not bounds:
            raise ValueError("No context or input capacity is available")
        available = min(bounds) - self.safety_margin_tokens
        if self.input_ceiling is not None:
            available = min(available, self.input_ceiling)
        return max(0, available - external_tokens)


@lru_cache(maxsize=4)
def _read_catalog(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Read the pinned offline catalog; missing/malformed files use conservative defaults."""
    return _read_catalog(str(path or _CATALOG_PATH))


def reset_cache() -> None:
    _read_catalog.cache_clear()


def _policy(data: Mapping[str, Any]) -> dict[str, Any]:
    policy = data.get("policy")
    policy = policy if isinstance(policy, Mapping) else {}
    return {
        "safety_margin_tokens": policy.get("safety_margin_tokens", _DEFAULT_MARGIN),
        "input_ceiling": policy.get("ceiling"),
    }


def _catalog_limits(model: str | None, data: Mapping[str, Any]) -> ModelLimits:
    name = str(model or "").strip().lower()
    models = data.get("models")
    entry = models.get(name) if isinstance(models, Mapping) else None
    # A proxy alias can collide with a real model name; only its exact configured
    # key or verified underlying model may supply capacity.
    if entry is None and isinstance(models, Mapping) and not name.startswith("litellm/"):
        entry = models.get(name.rsplit("/", 1)[-1])
    values = dict(entry) if isinstance(entry, Mapping) else {"context_window": entry}
    limits = {key: values.get(key) for key in _LIMIT_FIELDS}
    known = limits["context_window"] is not None or limits["max_input_tokens"] is not None
    if not known:
        limits["context_window"] = data.get("default_window", _DEFAULT_WINDOW)
    return ModelLimits(
        model=model,
        context_window=limits["context_window"],
        max_input_tokens=limits["max_input_tokens"],
        max_output_tokens=limits["max_output_tokens"],
        source=f"catalog:{data.get('_revision', 'local')}" if known else "catalog:default",
        resolved_model=model if known else None,
        **_policy(data),
    )


def _metadata_limits(model: str | None, info: Mapping[str, Any], source: str) -> ModelLimits:
    data = load_catalog()
    values = {key: info.get(key) for key in _LIMIT_FIELDS}
    resolved = _name(info.get("resolved_model"))
    source = _name(info.get("source")) or source
    if values["context_window"] is None and values["max_input_tokens"] is None:
        fallback = _catalog_limits(resolved or model, data)
        return replace(
            fallback,
            model=model,
            resolved_model=resolved or fallback.resolved_model,
            max_output_tokens=(
                values["max_output_tokens"]
                if values["max_output_tokens"] is not None
                else fallback.max_output_tokens
            ),
            source=f"{source}+{fallback.source}" if info else fallback.source,
        )
    return ModelLimits(
        model=model,
        context_window=values["context_window"],
        max_input_tokens=values["max_input_tokens"],
        max_output_tokens=values["max_output_tokens"],
        source=source,
        resolved_model=resolved,
        **_policy(data),
    )


def _name(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _check_connection(connection: Any, expected: Any, scoped: Any = None) -> None:
    changed = callable(connection) and connection() != expected
    if scoped is not None:
        from app.infrastructure.llm.client import _scoped_client

        current = _scoped_client.get()
        changed = (
            changed or current is None or current[0] is not scoped[0] or current[1] != scoped[1]
        )
    if changed:
        from app.infrastructure.modstore_transport import MarketModelError

        raise MarketModelError({"status": 409})


def _provider_adapter(provider: Any) -> tuple[Any, Any, Any]:
    seen = set()
    for _ in range(8):
        seen.add(id(provider))
        inner = getattr(provider, "_inner", None)
        if inner is None or id(inner) in seen:
            break
        provider = inner
    adapter = getattr(provider, "_adapter", None)
    ensure = getattr(provider, "_ensure_adapter", None)
    if adapter is None and callable(ensure):
        adapter = ensure()
    scoped = None
    if getattr(provider, "provider_id", None) == "openai_sdk":
        from app.infrastructure.llm.client import _resolved_scoped_client, _scoped_client

        resolved = _resolved_scoped_client()
        if resolved and getattr(resolved[0], "is_modstore_openai_compatible", False) is True:
            adapter = resolved[0].adapter
            scoped = _scoped_client.get()
    return provider, adapter, scoped


def _default_model(provider: Any, adapter: Any) -> str | None:
    if getattr(provider, "provider_id", None) == "openai_sdk":
        from app.infrastructure.llm.client import resolve_chat_model

        return _name(resolve_chat_model())
    return next(
        (
            name
            for value in (
                getattr(adapter, "model_name", None),
                getattr(provider, "model_name", None),
                getattr(provider, "_model", None),
            )
            if (name := _name(value))
        ),
        None,
    )


async def model_for_budget(
    provider: Any, requested_model: str | None = None, requested_provider: str | None = None
) -> str | None:
    """Resolve the callable route without globally registering account-specific aliases."""
    provider, adapter, scoped = _provider_adapter(provider)
    if adapter is not None and (getattr(provider, "provider_id", None) == "modstore" or scoped):
        requested_model = requested_model or (scoped[1] if scoped else None)
        vendor, model = await adapter.resolve_chat_route(requested_provider, requested_model)
        # Always retain the outer vendor, including nested OpenRouter/model namespaces.
        return f"{vendor}/{model}"
    return _name(requested_model) or _default_model(provider, adapter)


async def resolve_model_limits(
    provider: Any,
    requested_model: str | None = None,
    requested_provider: str | None = None,
    *,
    messages: list[dict[str, Any]] | None = None,
) -> ModelLimits:
    """Use only the selected route's metadata; never share an alias across accounts."""
    provider, adapter, scoped = _provider_adapter(provider)
    if adapter is not None and (getattr(provider, "provider_id", None) == "modstore" or scoped):
        connection = getattr(adapter, "_connection", None)
        snapshot = connection() if callable(connection) else None
        fallback_model = scoped[1] if scoped else None
        prepare = getattr(adapter, "prepare_chat_route", None)
        prepared = None
        if callable(prepare):
            prepared = await prepare(
                messages or [],
                requested_provider,
                requested_model,
                **({"fallback_model": fallback_model} if scoped else {}),
            )
            vendor, raw_model = prepared.route
        else:
            vendor, raw_model = await adapter.resolve_chat_route(
                requested_provider, requested_model or fallback_model
            )
        _check_connection(connection, snapshot, scoped)
        model: str | None = f"{vendor}/{raw_model}"
        resolve = getattr(adapter, "resolve_model_capabilities", None)
        info = (
            await resolve(
                vendor, raw_model, **({"prepared_route": prepared} if prepared is not None else {})
            )
            if callable(resolve)
            else {}
        )
        _check_connection(connection, snapshot, scoped)
        limits = _metadata_limits(
            model, info if isinstance(info, Mapping) else {}, "provider_metadata"
        )
        return replace(
            limits,
            request_guard=(
                (lambda: _check_connection(connection, snapshot, scoped))
                if callable(connection) or scoped is not None
                else None
            ),
            request_options=(
                {"_prepared_chat_route": prepared, "model": model} if prepared is not None else {}
            ),
        )
    default_model = _default_model(provider, adapter)
    model = _name(requested_model) or default_model
    for owner in (provider, adapter):
        info = getattr(owner, "model_info", None)
        if not isinstance(info, Mapping):
            continue
        selected = info.get(model) if model is not None else None
        if isinstance(selected, Mapping):
            return _metadata_limits(model, selected, "provider_metadata")
        declared = _name(info.get("model")) or _name(info.get("model_name"))
        if (declared and declared == model) or (not declared and model == default_model):
            return _metadata_limits(model, info, "provider_metadata")
    return _catalog_limits(model, load_catalog())


def context_window_for(model: str | None, *, catalog: dict[str, Any] | None = None) -> int:
    """Legacy capacity lookup, before output reservation or the safety margin."""
    limits = _catalog_limits(model, load_catalog() if catalog is None else catalog)
    return min(
        value for value in (limits.context_window, limits.max_input_tokens) if value is not None
    )


def resolve_token_budget(
    model: str | None = None,
    *,
    window: int | None = None,
    catalog: dict[str, Any] | None = None,
) -> int:
    """Legacy input budget; callers reserve their actual output and external content once."""
    data = load_catalog() if catalog is None else catalog
    limits = (
        ModelLimits(model=model, context_window=window, source="explicit", **_policy(data))
        if window is not None
        else _catalog_limits(model, data)
    )
    return limits.input_budget()
