"""Software-LLM assistance for general ETL.

The model may classify bounded workbook probes, suggest field mappings, and
explain deterministic row decisions.  It never receives authority to write
business data or to override target-adapter actions.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.application.etl import llm_assist_runtime as _runtime
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

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

# ETL assistance is advisory.  A provider outage must never turn a preview
# into a sequence of long, duplicate calls (especially when an auto-detected
# delivery workbook creates the linked customer/product preview at the same
# time).  Keep this process-local on purpose: account credentials and quota
# state are not ETL business data and are never persisted with a run.
LlmAssistResult = _runtime.LlmAssistResult
clear_etl_llm_circuit = _runtime.clear_etl_llm_circuit
etl_llm_mode = _runtime.etl_llm_mode
etl_llm_timeout_seconds = _runtime.etl_llm_timeout_seconds
etl_row_advice_limit = _runtime.etl_row_advice_limit
_circuit_cooldown_seconds = _runtime.circuit_cooldown_seconds
_circuit_degradation = _runtime.circuit_degradation
_circuit_key = _runtime.circuit_key
_degradation_code = _runtime.degradation_code
_open_circuit = _runtime.open_circuit
_owner_call_lock = _runtime.owner_call_lock


def _bounded_structured_completion(
    messages: list[dict[str, str]],
    *,
    schema: dict[str, Any],
    max_tokens: int,
    timeout_seconds: float,
    conversation_service: Any | None,
    provider: Any | None,
):
    """Run one structured LLM call without letting a worker thread stall.

    ``complete_structured_sync`` applies its timeout only when it detects an
    existing event loop.  Preview workers intentionally do not own one, so an
    outer daemon-thread deadline is required here.  A timed-out provider call
    may finish in the background, but the preview returns immediately and the
    ETL circuit prevents another advisory call while it is unhealthy.
    """

    from app.infrastructure.llm.structured_output import complete_structured_sync

    box: dict[str, Any] = {}

    def invoke() -> None:
        try:
            box["result"] = complete_structured_sync(
                messages,
                schema=schema,
                temperature=0.0,
                max_tokens=max_tokens,
                # A schema repair is another provider request.  ETL remains
                # deterministic without it, so never retry advisory output.
                max_repairs=0,
                timeout_seconds=timeout_seconds,
                profile="etl",
                conversation_service=conversation_service,
                provider=provider,
            )
        except BOUNDARY_ERRORS as exc:
            box["error"] = exc

    worker = threading.Thread(
        target=invoke,
        name="etl-llm-assist",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=timeout_seconds)
    if worker.is_alive():
        raise TimeoutError("ETL LLM assist timed out")
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise RuntimeError("ETL LLM assist returned no result")
    return box["result"]


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
    circuit_key = _circuit_key()
    circuit_degradation = _circuit_degradation(circuit_key)
    if circuit_degradation:
        return LlmAssistResult(
            used_llm=False,
            degraded=True,
            degradation_code=circuit_degradation,
        )

    # The auto shipment preview can spawn a linked customer/product preview.
    # Serializing calls for one software account lets the first observed quota
    # or timeout stop every later advisory stage instead of multiplying it.
    with _owner_call_lock(circuit_key):
        circuit_degradation = _circuit_degradation(circuit_key)
        if circuit_degradation:
            return LlmAssistResult(
                used_llm=False,
                degraded=True,
                degradation_code=circuit_degradation,
            )
        configured, conversation_service, provider = _active_software_llm()
        if not configured:
            return LlmAssistResult(
                used_llm=False,
                degraded=mode == "on",
                degradation_code="ETL_LLM_UNAVAILABLE" if mode == "on" else "",
            )
        timeout_seconds = etl_llm_timeout_seconds()
        try:
            result = _bounded_structured_completion(
                messages,
                schema=schema,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                conversation_service=conversation_service,
                provider=provider,
            )
            return LlmAssistResult(
                used_llm=True,
                model=str(result.model or ""),
                billing=dict(result.billing or {}),
                data=dict(result.data),
            )
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - advisory LLM must never own ETL execution
            degradation_code = _degradation_code(exc)
            _open_circuit(circuit_key, degradation_code)
            logger.info(
                "general etl llm assist degraded (%s): %s",
                degradation_code,
                type(exc).__name__,
            )
            return LlmAssistResult(
                used_llm=True,
                degraded=True,
                degradation_code=degradation_code,
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
            index = int(item.get("index") or 0)
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


_BATCH_ADVICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["overall_judgment", "reasoning", "cautions", "questions"],
    "properties": {
        "overall_judgment": {"type": "string"},
        "reasoning": {"type": "array", "items": {"type": "string"}},
        "cautions": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def advise_batch_plan(items: list[dict[str, Any]], source_label: str) -> LlmAssistResult:
    """Review the completed deterministic corpus once, after every file was read."""
    if not items:
        return LlmAssistResult()
    bounded_items: list[dict[str, Any]] = []
    for item in items[:100]:
        bounded_items.append(
            {
                "file_name": str(item.get("file_name") or "")[:500],
                "target_type": str(item.get("target_type") or "")[:80],
                "database_target_label": str(item.get("database_target_label") or "")[:120],
                "confidence": item.get("confidence") or 0,
                "sheet_count": item.get("sheet_count") or 0,
                "row_count": item.get("row_count") or 0,
                "preview_counts": {
                    "new": item.get("new_count") or 0,
                    "update": item.get("update_count") or 0,
                    "skip": item.get("skip_count") or 0,
                    "error": item.get("error_count") or 0,
                },
                "template_count": item.get("template_count") or 0,
                "knowledge_ready": bool(item.get("knowledge_ready")),
                "database_recommended": bool(item.get("database_recommended")),
                "warnings": [str(value)[:300] for value in list(item.get("warnings") or [])[:20]],
            }
        )
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业办公资料对接顾问。所有文件已经由确定性解析器完整读取并完成无写入预演。"
                "请综合全部文件后给出自然、具体的中文建议，不要逐个要求用户确认。"
                "数据库建议必须服从 database_recommended；存在阻断错误、低置信度或目标不明时不得建议强行入库。"
                "只有 template_count 大于零才可称为真实模板。不得声称已经写入任何目标。返回 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "review_office_docking_batch_after_complete_read",
                    "source_label": str(source_label or "这批办公资料")[:500],
                    "items": bounded_items,
                    "requested_output": {
                        "overall_judgment": "一段总体判断",
                        "reasoning": "最多4条处理思路",
                        "cautions": "最多4条风险提示",
                        "questions": "最多3个值得和用户商量的问题",
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = _complete(messages, schema=_BATCH_ADVICE_SCHEMA, max_tokens=1400)
    if not result.data:
        return result
    result.data = {
        "overall_judgment": str(result.data.get("overall_judgment") or "")[:1200],
        "reasoning": [str(value)[:500] for value in list(result.data.get("reasoning") or [])[:4]],
        "cautions": [str(value)[:500] for value in list(result.data.get("cautions") or [])[:4]],
        "questions": [str(value)[:500] for value in list(result.data.get("questions") or [])[:3]],
    }
    return result


__all__ = [
    "LlmAssistResult",
    "advise_batch_plan",
    "advise_field_mappings",
    "advise_row_decisions",
    "advise_workbook_regions",
    "clear_etl_llm_circuit",
    "etl_llm_enabled",
    "etl_llm_mode",
    "etl_llm_timeout_seconds",
    "etl_row_advice_limit",
]
