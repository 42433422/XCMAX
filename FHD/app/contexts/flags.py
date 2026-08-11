"""Feature flags: event-primary path per bounded context."""

from __future__ import annotations

import os


def _truthy(val: str) -> bool:
    return val.strip().lower() in {"1", "true", "yes", "on"}


def is_any_event_primary_enabled() -> bool:
    raw = (os.environ.get("XCAGI_EVENT_PRIMARY") or "").strip()
    return bool(raw) and _truthy(raw)


def is_event_primary_enabled(context_id: str) -> bool:
    """
    ``XCAGI_EVENT_PRIMARY=1`` enables event-primary for all facades that consult this flag.
    ``XCAGI_EVENT_PRIMARY_SHIPMENT=1`` enables only shipment (context id ``shipment``).
    """
    if is_any_event_primary_enabled():
        return True
    key = f"XCAGI_EVENT_PRIMARY_{context_id.strip().upper()}"
    raw = (os.environ.get(key) or "").strip()
    return bool(raw) and _truthy(raw)


# Valid workflow runtime modes (LG-W1-T7 gray-release selector). At this T7
# boundary only ``legacy`` and ``primary`` are fully wired; ``shadow``/``canary``
# are reserved for the ShadowCanaryRouter (T8) and must fail closed, never fall
# back to another mode.
_LG_RUNTIME_MODES = frozenset({"legacy", "shadow", "canary", "primary"})


def lg_runtime_mode() -> str:
    """Return the normalized ``XCAGI_LG_RUNTIME`` mode (strip/lower).

    Defaults to ``legacy`` when unset. Valid values: ``legacy``, ``shadow``,
    ``canary``, ``primary``. Any other value raises ``ValueError`` — it never
    silently falls back to a default.
    """
    raw = (os.environ.get("XCAGI_LG_RUNTIME") or "legacy").strip().lower()
    if raw not in _LG_RUNTIME_MODES:
        raise ValueError(f"XCAGI_LG_RUNTIME 无效值: {raw!r}（有效: {sorted(_LG_RUNTIME_MODES)}）")
    return raw


def lg_runtime_canary_ratio() -> float:
    """Return the ``XCAGI_LG_CANARY_RATIO`` traffic ratio (default ``0.1``).

    Must be a float inside the closed interval ``[0, 1]`` (both endpoints are
    valid: ``0.0`` routes nothing to the new runtime, ``1.0`` routes everything).
    A missing/invalid value or a value outside that closed interval raises
    ``ValueError``.
    """
    raw = (os.environ.get("XCAGI_LG_CANARY_RATIO") or "0.1").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"XCAGI_LG_CANARY_RATIO 无效值: {raw!r}（需为 0~1 之间浮点数）") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"XCAGI_LG_CANARY_RATIO 必须在 [0, 1]（闭区间）内: {raw!r}")
    return value
