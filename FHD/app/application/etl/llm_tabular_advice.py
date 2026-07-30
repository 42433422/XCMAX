"""Region, mapping, and row-decision LLM advice."""

from __future__ import annotations

from typing import Any

from app.utils.mixin_module_sync import sync_module_functions

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
                "Allowed transforms are empty, trim, number, and date. Write every "
                "human-readable reason in Simplified Chinese."
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
                "reason": _localized_model_text(
                    item.get("reason"),
                    "模型根据列名、样例值和目标字段语义建议此映射。",
                )[:300],
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
                "must not claim that a database write occurred. Write every human-readable "
                "reason in Simplified Chinese."
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
                "reason": _localized_model_text(
                    item.get("reason"),
                    {
                        "new": "模型建议新增；最终仍以主数据和重复数据校验结果为准。",
                        "update": "模型建议更新；最终仍以变更差异和允许更新字段为准。",
                        "skip": "模型建议跳过；最终仍以重复数据和业务规则校验结果为准。",
                    }[action],
                )[:300],
            }
        )
    result.data = {"items": normalized}
    return result


sync_module_functions(
    target=globals(),
    source_module="app.application.etl.llm_assist",
    function_names=(
        "advise_workbook_regions",
        "advise_field_mappings",
        "advise_row_decisions",
    ),
)
