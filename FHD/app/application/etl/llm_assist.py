"""Software-LLM assistance for general ETL.

The model may classify bounded workbook probes, suggest field mappings, and
explain deterministic row decisions.  It never receives authority to write
business data or to override target-adapter actions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_REGION_ROLES = frozenset(
    {
        "delivery_note",
        "shipment_ledger",
        "product_catalog",
        "customer_directory",
        "finance",
        "ignore",
    }
)
_ROW_ACTIONS = frozenset({"new", "update", "skip"})
_SAFE_MAPPING_TRANSFORMS = frozenset({"trim", "number", "date"})


@dataclass(slots=True)
class LlmAssistResult:
    used_llm: bool = False
    degraded: bool = False
    degradation_code: str = ""
    model: str = ""
    billing: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def public_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "used_llm": self.used_llm,
            "advisory_only": True,
            "degraded": self.degraded,
        }
        if self.degradation_code:
            result["degradation_code"] = self.degradation_code
        if self.model:
            result["model"] = self.model
        if self.billing:
            result["billing"] = dict(self.billing)
        return result


def etl_llm_mode() -> str:
    raw = str(os.environ.get("FHD_ETL_LLM") or "auto").strip().lower()
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return "on"
    return "auto"


def etl_llm_timeout_seconds() -> float:
    raw = str(os.environ.get("FHD_ETL_LLM_TIMEOUT") or "15").strip()
    try:
        return min(60.0, max(1.0, float(raw)))
    except ValueError:
        return 15.0


def etl_row_advice_limit() -> int:
    raw = str(os.environ.get("FHD_ETL_LLM_ROW_ADVICE_LIMIT") or "20").strip()
    try:
        return min(100, max(0, int(raw)))
    except ValueError:
        return 20


def _degradation_code(exc: BaseException) -> str:
    message = str(exc).lower()
    if "quota exhausted" in message or "额度" in message or "429" in message:
        return "ETL_LLM_QUOTA_EXHAUSTED"
    return "ETL_LLM_UNAVAILABLE"


def _active_software_llm() -> tuple[bool, Any | None, Any | None]:
    """Resolve the current user's software-account LLM, then app-wide providers."""
    try:
        from app.application.etl.llm_session_provider import current_owner_market_provider

        market_provider = current_owner_market_provider(timeout_seconds=etl_llm_timeout_seconds())
        if market_provider is not None:
            return True, None, market_provider
        from app.infrastructure.llm.providers.registry import get_active_provider

        if get_active_provider(profile="etl") is not None:
            return True, None, None
        from app.services.ai_conversation_service import get_ai_conversation_service

        service = get_ai_conversation_service()
        if get_active_provider(conversation_service=service, profile="etl") is not None:
            return True, service, None
        return False, None, None
    except RECOVERABLE_ERRORS:
        return False, None, None


def etl_llm_enabled() -> bool:
    mode = etl_llm_mode()
    if mode == "off":
        return False
    configured, _service, _provider = _active_software_llm()
    return configured if mode == "auto" else True


def _complete(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_tokens: int,
) -> LlmAssistResult:
    mode = etl_llm_mode()
    if mode == "off":
        return LlmAssistResult()
    configured, conversation_service, provider = _active_software_llm()
    if not configured:
        return LlmAssistResult(
            used_llm=False,
            degraded=mode == "on",
            degradation_code="ETL_LLM_UNAVAILABLE" if mode == "on" else "",
        )
    try:
        from app.infrastructure.llm.structured_output import complete_structured_sync

        result = complete_structured_sync(
            messages,
            schema=schema,
            temperature=0.0,
            max_tokens=max_tokens,
            max_repairs=1,
            timeout_seconds=etl_llm_timeout_seconds(),
            profile="etl",
            conversation_service=conversation_service,
            provider=provider,
        )
        return LlmAssistResult(
            used_llm=True,
            model=str(result.model or ""),
            billing=dict(result.billing or {}),
            data=dict(result.data),
        )
    except Exception as exc:  # noqa: BLE001 - LLM failure must never own ETL execution
        logger.info("general etl llm assist degraded: %s", type(exc).__name__)
        return LlmAssistResult(
            used_llm=True,
            degraded=True,
            degradation_code=_degradation_code(exc),
        )


_REGION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["regions"],
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["region_id", "role", "confidence", "reason"],
                "properties": {
                    "region_id": {"type": "string"},
                    "role": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "contact_person": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def advise_workbook_regions(probes: list[dict[str, Any]]) -> LlmAssistResult:
    """Classify only deterministic candidate region IDs; never invent coordinates."""
    if not probes:
        return LlmAssistResult()
    bounded = []
    for probe in probes[:40]:
        bounded.append(
            {
                "region_id": str(probe.get("region_id") or "")[:120],
                "sheet": str(probe.get("sheet") or "")[:120],
                "header_row": int(probe.get("header_row") or 0),
                "headers": [str(item)[:120] for item in list(probe.get("headers") or [])[:24]],
                "context_rows": [
                    {
                        "row": int(item.get("row") or 0),
                        "text": str(item.get("text") or "")[:600],
                    }
                    for item in list(probe.get("context_rows") or [])[:5]
                    if isinstance(item, dict)
                ],
                "deterministic_role": str(probe.get("deterministic_role") or "")[:40],
                "explicit_customer": str(probe.get("explicit_customer") or "")[:160],
            }
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You classify spreadsheet regions for enterprise ETL. Return JSON only. "
                "Use only supplied region_id values and source text. Never invent cells, "
                "customers, quantities, prices, or write actions."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "classify_workbook_regions",
                    "allowed_roles": sorted(_REGION_ROLES),
                    "rules": [
                        "delivery_note requires explicit buyer or customer evidence",
                        "finance, payment, reconciliation and balance tables are finance",
                        "a price list or color-code list is product_catalog",
                        "sheet or filename text alone is not sufficient customer identity",
                    ],
                    "regions": bounded,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_REGION_SCHEMA, max_tokens=1800)
    allowed_ids = {item["region_id"] for item in bounded if item["region_id"]}
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("regions") or []):
        if not isinstance(item, dict):
            continue
        region_id = str(item.get("region_id") or "")
        role = str(item.get("role") or "")
        if region_id not in allowed_ids or role not in _REGION_ROLES:
            continue
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append(
            {
                "region_id": region_id,
                "role": role,
                "customer_name": str(item.get("customer_name") or "")[:160],
                "contact_person": str(item.get("contact_person") or "")[:160],
                "confidence": confidence,
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    result.data = {"regions": normalized}
    return result


_MAPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["mappings"],
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "target", "confidence", "reason"],
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "transform": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def advise_field_mappings(
    *,
    headers: list[str],
    samples: dict[str, list[str]],
    target_fields: list[dict[str, Any]],
) -> LlmAssistResult:
    if not headers or not target_fields:
        return LlmAssistResult()
    messages = [
        {
            "role": "system",
            "content": (
                "You suggest spreadsheet field mappings. Return JSON only. Choose source "
                "and target names exclusively from the supplied lists. Never invent values. "
                "Allowed transforms are empty, trim, number, and date."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "suggest_etl_field_mappings",
                    "headers": [str(item)[:160] for item in headers[:100]],
                    "samples": {
                        str(key)[:160]: [str(value)[:160] for value in values[:3]]
                        for key, values in list(samples.items())[:100]
                    },
                    "target_fields": target_fields[:80],
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_MAPPING_SCHEMA, max_tokens=1600)
    allowed_sources = set(headers)
    allowed_targets = {str(field.get("key") or "") for field in target_fields}
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("mappings") or []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        target = str(item.get("target") or "")
        transform = str(item.get("transform") or "")
        if source not in allowed_sources or target not in allowed_targets:
            continue
        if transform and transform not in _SAFE_MAPPING_TRANSFORMS:
            transform = ""
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append(
            {
                "source": source,
                "target": target,
                "transform": transform,
                "confidence": confidence,
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    result.data = {"mappings": normalized}
    return result


_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "action", "reason"],
                "properties": {
                    "index": {"type": "integer"},
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def advise_row_decisions(payloads: list[dict[str, Any]]) -> LlmAssistResult:
    """Explain a bounded set of adapter decisions in one model call."""
    if not payloads:
        return LlmAssistResult()
    bounded = [
        {
            "index": index,
            "allowed_actions": sorted(_ROW_ACTIONS),
            "deterministic_action": str(item.get("deterministic_action") or ""),
            "deterministic_reason": str(item.get("deterministic_reason") or "")[:300],
            "normalized": item.get("normalized") or {},
            "before": item.get("before") or {},
            "after": item.get("after") or {},
        }
        for index, item in enumerate(payloads[: etl_row_advice_limit()])
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You explain deterministic ETL preview decisions. Return JSON only. "
                "You may recommend new, update, or skip, but your answer is advisory and "
                "must not claim that a database write occurred."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "advise_etl_row_decisions",
                    "rules": [
                        "Prefer skip for duplicates",
                        "Update requires a visible before/after difference",
                        "Do not invent missing business values",
                    ],
                    "items": bounded,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_ROW_SCHEMA, max_tokens=1600)
    normalized: list[dict[str, Any]] = []
    for item in list(result.data.get("items") or []):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        action = str(item.get("action") or "")
        if index < 0 or index >= len(bounded) or action not in _ROW_ACTIONS:
            continue
        normalized.append(
            {
                "index": index,
                "action": action,
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    result.data = {"items": normalized}
    return result


__all__ = [
    "LlmAssistResult",
    "advise_field_mappings",
    "advise_row_decisions",
    "advise_workbook_regions",
    "etl_llm_enabled",
    "etl_llm_mode",
    "etl_llm_timeout_seconds",
    "etl_row_advice_limit",
]
