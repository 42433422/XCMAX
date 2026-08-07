"""Bounded LLM assistance for deterministic ETL field mappings."""

from __future__ import annotations

from typing import Any

from app.application.etl.llm_assist import advise_field_mappings
from app.application.etl.parser_types import ParsedDataset
from app.application.etl.targets import TargetAdapter


def enhance_mappings_with_llm(
    dataset: ParsedDataset,
    adapter: TargetAdapter,
    deterministic: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fill only weak or unmapped pairs from a bounded structured suggestion."""
    if adapter.allow_dynamic_fields or not dataset.rows:
        return deterministic, {
            "used_llm": False,
            "advisory_only": True,
            "degraded": False,
            "reason": "dynamic_or_empty_dataset",
        }

    samples: dict[str, list[str]] = {}
    for header in dataset.headers[:100]:
        values: list[str] = []
        for row in dataset.rows[:20]:
            value = row.values.get(header)
            if value in (None, ""):
                continue
            text = str(value)[:160]
            if text not in values:
                values.append(text)
            if len(values) >= 3:
                break
        samples[header] = values
    result = advise_field_mappings(
        headers=list(dataset.headers),
        samples=samples,
        target_fields=[
            {
                "key": field.key,
                "label": field.label,
                "type": field.type,
                "required": field.required,
                "aliases": list(field.aliases),
            }
            for field in adapter.fields
        ],
    )
    enhanced = [dict(mapping) for mapping in deterministic]
    by_target = {str(mapping.get("target") or ""): mapping for mapping in enhanced}
    used_sources = {
        str(mapping.get("source") or "")
        for mapping in enhanced
        if mapping.get("source") and float(mapping.get("confidence") or 0.0) >= 0.9
    }
    applied = 0
    for suggestion in list(result.data.get("mappings") or []):
        target = str(suggestion.get("target") or "")
        source = str(suggestion.get("source") or "")
        mapping = by_target.get(target)
        if mapping is None or source in used_sources:
            continue
        current_confidence = float(mapping.get("confidence") or 0.0)
        llm_confidence = float(suggestion.get("confidence") or 0.0)
        if current_confidence >= 0.9 or llm_confidence < 0.85:
            continue
        transform = str(suggestion.get("transform") or "")
        mapping.update(
            {
                "source": source,
                "confidence": llm_confidence,
                "transforms": [{"op": transform}] if transform else [],
                "suggested_by": "llm",
                "reason": str(suggestion.get("reason") or "")[:300],
            }
        )
        used_sources.add(source)
        applied += 1
    return enhanced, {
        **result.public_metadata(),
        "suggestion_count": len(list(result.data.get("mappings") or [])),
        "applied_count": applied,
    }


__all__ = ["enhance_mappings_with_llm"]
