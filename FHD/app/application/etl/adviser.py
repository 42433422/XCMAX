"""Optional LLM row adviser with a deterministic, fail-closed fallback.

The adviser can recommend ``new``/``update``/``skip`` and a reason, but callers
must keep the adapter decision as the executable action.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

_ACTIONS = frozenset({"new", "update", "skip"})
RowProvider = Callable[[dict[str, Any]], dict[str, Any] | None]
BatchProvider = Callable[[list[dict[str, Any]]], dict[str, Any] | None]


def _bounded_record(value: dict[str, Any]) -> dict[str, str]:
    return {str(key)[:80]: str(item)[:500] for key, item in list(value.items())[:40]}


class EtlRowAdviser:
    def __init__(
        self,
        provider: RowProvider | None = None,
        *,
        batch_provider: BatchProvider | None = None,
    ) -> None:
        self._provider = provider
        self._batch_provider = batch_provider

    @staticmethod
    def fallback(
        *,
        deterministic_action: str,
        deterministic_reason: str,
        normalized: dict[str, Any],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> dict[str, Any]:
        _ = (normalized, before, after)
        return {
            "action": deterministic_action,
            "reason": deterministic_reason or "deterministic_rule",
            "used_llm": False,
            "advisory_only": True,
            "degraded": False,
        }

    def suggest(
        self,
        *,
        deterministic_action: str,
        deterministic_reason: str,
        normalized: dict[str, Any],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = self.fallback(
            deterministic_action=deterministic_action,
            deterministic_reason=deterministic_reason,
            normalized=normalized,
            before=before,
            after=after,
        )
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
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - model failures never affect execution
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

    def suggest_many(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        if self._batch_provider is None:
            return [self.suggest(**row) for row in rows]
        fallbacks = [self.fallback(**row) for row in rows]
        payloads = [
            {
                "allowed_actions": sorted(_ACTIONS),
                "deterministic_action": row["deterministic_action"],
                "deterministic_reason": row["deterministic_reason"],
                "normalized": _bounded_record(row["normalized"]),
                "before": _bounded_record(row["before"]),
                "after": _bounded_record(row["after"]),
            }
            for row in rows
        ]
        try:
            result = self._batch_provider(payloads)
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - model failures never affect execution
            return [
                {
                    **fallback,
                    "degraded": True,
                    "degradation_code": "ETL_LLM_UNAVAILABLE",
                }
                for fallback in fallbacks
            ]
        if not isinstance(result, dict):
            return fallbacks
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        if metadata.get("degraded"):
            return [
                {
                    **fallback,
                    "degraded": True,
                    "degradation_code": str(
                        metadata.get("degradation_code") or "ETL_LLM_UNAVAILABLE"
                    ),
                }
                for fallback in fallbacks
            ]
        if not metadata.get("used_llm"):
            return fallbacks
        output = list(fallbacks)
        for item in list(result.get("items") or []):
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index") or 0)
            except (TypeError, ValueError):
                continue
            action = str(item.get("action") or "").strip().lower()
            if index < 0 or index >= len(output) or action not in _ACTIONS:
                continue
            output[index] = {
                "action": action,
                "reason": str(item.get("reason") or "llm_advice")[:300],
                "used_llm": True,
                "advisory_only": True,
                "degraded": False,
                **({"model": metadata["model"]} if metadata.get("model") else {}),
            }
        return output


def _default_batch_provider(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    from app.application.etl.llm_assist import advise_row_decisions

    result = advise_row_decisions(payloads)
    return {
        "items": list(result.data.get("items") or []),
        "metadata": result.public_metadata(),
    }


_DEFAULT_ADVISER = EtlRowAdviser(batch_provider=_default_batch_provider)


def get_etl_row_adviser() -> EtlRowAdviser:
    return _DEFAULT_ADVISER
