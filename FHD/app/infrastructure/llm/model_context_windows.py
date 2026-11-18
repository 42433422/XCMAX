"""Model context window lookup sourced from the LiteLLM catalog (MIT)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "context_window_for",
    "load_catalog",
    "model_for_budget",
    "reset_cache",
    "resolve_token_budget",
]

_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "model_context_windows.json"
_DEFAULT_WINDOW = 16384
_DEFAULT_POLICY = {"reserve_ratio": 0.5, "floor": 8000, "ceiling": 32000}


@lru_cache(maxsize=4)
def _read_catalog(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Read the vendored catalog; malformed or missing files degrade to defaults."""
    return _read_catalog(str(path or _CATALOG_PATH))


def reset_cache() -> None:
    """Drop the cached catalog (tests and config hot reloads)."""
    _read_catalog.cache_clear()


def model_for_budget(provider: Any, requested_model: str | None = None) -> str | None:
    """Use the selected provider's model, including admission/telemetry wrappers."""
    if requested_model:
        return requested_model
    for _ in range(4):
        inner = getattr(provider, "_inner", None)
        if inner is None:
            break
        provider = inner
    if getattr(provider, "provider_id", None) == "openai_sdk":
        from app.infrastructure.llm.client import resolve_chat_model

        return resolve_chat_model()
    adapter = getattr(provider, "_adapter", None)
    ensure_adapter = getattr(provider, "_ensure_adapter", None)
    if adapter is None and callable(ensure_adapter):
        adapter = ensure_adapter()
    for model in (
        getattr(adapter, "model_name", None),
        getattr(provider, "model_name", None),
        getattr(provider, "_model", None),
    ):
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None


def _positive_int(value: Any, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return number if number > 0 else fallback


def context_window_for(model: str | None, *, catalog: dict[str, Any] | None = None) -> int:
    """Return the input context window for ``model``, falling back to the catalog default."""
    data = load_catalog() if catalog is None else catalog
    name = str(model or "").strip()
    models = data.get("models")
    entry = models.get(name) if isinstance(models, dict) else None
    if isinstance(entry, dict):
        entry = entry.get("max_input_tokens")
    if entry is not None:
        window = _positive_int(entry, 0)
        if window:
            return window
    return _positive_int(data.get("default_window"), _DEFAULT_WINDOW)


def resolve_token_budget(
    model: str | None = None,
    *,
    window: int | None = None,
    catalog: dict[str, Any] | None = None,
) -> int:
    """Convert a model's context window into our input budget.

    Only part of the window is reserved for history: the remainder stays free for
    the model output and the tool schemas attached to the same call.
    """
    data = load_catalog() if catalog is None else catalog
    policy = dict(_DEFAULT_POLICY)
    if isinstance(data.get("policy"), dict):
        policy.update(data["policy"])
    try:
        ratio = float(policy["reserve_ratio"])
    except (TypeError, ValueError):
        ratio = float(_DEFAULT_POLICY["reserve_ratio"])
    ratio = max(0.1, min(0.9, ratio))
    effective_window = (
        _positive_int(window, _DEFAULT_WINDOW)
        if window is not None
        else context_window_for(model, catalog=data)
    )
    budget = int(effective_window * ratio)
    floor = _positive_int(policy.get("floor"), int(_DEFAULT_POLICY["floor"]))
    ceiling = _positive_int(policy.get("ceiling"), int(_DEFAULT_POLICY["ceiling"]))
    # The convenience floor must never manufacture capacity on a small model.
    return min(effective_window, ceiling, max(floor, budget))
