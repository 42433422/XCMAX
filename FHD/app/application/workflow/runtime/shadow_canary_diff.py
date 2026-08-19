"""Deterministic sampling and normalized result diffs for shadow canaries."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any

from app.application.workflow.ports.runtime import WorkflowRunResult

_VOLATILE_KEYS = (
    "timestamp",
    "started_at",
    "finished_at",
    "duration_ms",
    "trace_id",
    "checkpoint_id",
)


def _stripped_key(key: str) -> str:
    return str(key).replace("_", "").lower()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _normalize(value: Any, volatile: frozenset[str]) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _stripped_key(key_str) in volatile:
                continue
            normalized[key_str] = _normalize(item, volatile)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item, volatile) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item, volatile) for item in value), key=_canonical_json)
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize({item.name: getattr(value, item.name) for item in fields(value)}, volatile)
    if isinstance(value, Enum):
        return _normalize(value.value, volatile)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"__xcagi_object__": type(value).__name__}


def normalize_context(context: Any, *, volatile_keys: tuple[str, ...] | None = None) -> Any:
    """Normalize a final context while removing configured volatile fields."""
    volatile = frozenset(_stripped_key(key) for key in (volatile_keys or _VOLATILE_KEYS))
    return _normalize(context, volatile)


def deterministic_canary_selected(identity: str, ratio: float) -> bool:
    """Map a stable identity to a deterministic canary bucket."""
    if isinstance(ratio, bool):
        raise ValueError(f"ratio 不能是 bool: {ratio!r}")
    if not isinstance(ratio, (int, float)):
        raise ValueError(f"ratio 必须是实数: {ratio!r}")
    if isinstance(ratio, float) and not math.isfinite(ratio):
        raise ValueError(f"ratio 必须是有限实数: {ratio!r}")
    if not 0.0 <= float(ratio) <= 1.0:
        raise ValueError(f"ratio 必须在 [0, 1]（闭区间）内: {ratio!r}")
    if ratio <= 0.0:
        return False
    if ratio >= 1.0:
        return True
    digest = hashlib.sha256(str(identity).encode("utf-8")).digest()
    normalized = int.from_bytes(digest[:8], "big") / 2**64
    return normalized < ratio


def _executed_node_ids(result: WorkflowRunResult) -> list[str]:
    return [node.node_id for node in result.node_results]


@dataclass
class ShadowDiff:
    """Normalized comparison between a serving run and its shadow run."""

    operation: str
    plan_id: str
    equal: bool
    legacy_context: dict[str, Any] = field(default_factory=dict)
    langgraph_context: dict[str, Any] = field(default_factory=dict)
    langgraph_error: str = ""


def compute_normalized_diff(
    serving: WorkflowRunResult,
    shadow: WorkflowRunResult,
    *,
    operation: str = "run",
    langgraph_error: str = "",
) -> ShadowDiff:
    """Compare two run results on normalized contexts and executed nodes."""
    legacy_context = normalize_context(serving.final_context)
    langgraph_context = normalize_context(shadow.final_context)
    equal = (_executed_node_ids(serving) == _executed_node_ids(shadow)) and (
        legacy_context == langgraph_context
    )
    return ShadowDiff(
        operation=operation,
        plan_id=serving.plan_id,
        equal=equal,
        legacy_context=legacy_context,
        langgraph_context=langgraph_context,
        langgraph_error=langgraph_error,
    )
