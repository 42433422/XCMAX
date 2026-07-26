"""Optional LLM row adviser with a deterministic, fail-closed fallback.

The adviser can recommend ``new``/``update``/``skip`` and a reason, but callers
must keep the adapter decision as the executable action.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_ACTIONS = frozenset({"new", "update", "skip"})


def _bounded_record(value: dict[str, Any]) -> dict[str, str]:
    return {str(key)[:80]: str(item)[:500] for key, item in list(value.items())[:40]}


class EtlRowAdviser:
    def __init__(
        self,
        provider: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> None:
        self._provider = provider

    def suggest(
        self,
        *,
        deterministic_action: str,
        deterministic_reason: str,
        normalized: dict[str, Any],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = {
            "action": deterministic_action,
            "reason": deterministic_reason or "deterministic_rule",
            "used_llm": False,
            "advisory_only": True,
            "degraded": False,
        }
        if self._provider is None:
            return fallback
        try:
            result = self._provider(
                {
                    "allowed_actions": sorted(_ACTIONS),
                    "deterministic_action": deterministic_action,
                    "deterministic_reason": deterministic_reason,
                    "normalized": _bounded_record(normalized),
                    "before": _bounded_record(before),
                    "after": _bounded_record(after),
                }
            )
        except Exception:  # noqa: BLE001 - model failures never affect execution
            return {
                **fallback,
                "degraded": True,
                "degradation_code": "ETL_LLM_UNAVAILABLE",
            }
        if not isinstance(result, dict):
            return {
                **fallback,
                "degraded": True,
                "degradation_code": "ETL_LLM_INVALID_RESPONSE",
            }
        action = str(result.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return {
                **fallback,
                "degraded": True,
                "degradation_code": "ETL_LLM_INVALID_ACTION",
            }
        return {
            "action": action,
            "reason": str(result.get("reason") or "llm_advice")[:300],
            "used_llm": True,
            "advisory_only": True,
            "degraded": False,
        }


_DEFAULT_ADVISER = EtlRowAdviser()


def get_etl_row_adviser() -> EtlRowAdviser:
    return _DEFAULT_ADVISER
