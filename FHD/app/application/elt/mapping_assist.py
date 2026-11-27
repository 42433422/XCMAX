"""AI-first field mapping over existing parsed source facts and target fields."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.application.elt.llm_assist import advise_field_mappings
from app.application.elt.parser_types import ParsedDataset
from app.application.elt.targets import TargetAdapter


def enhance_mappings_with_llm(
    dataset: ParsedDataset,
    adapter: TargetAdapter,
    deterministic: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Suggest mappings without changing raw rows or bypassing preview approval."""
    if (
        adapter.allow_dynamic_fields
        or adapter.type in {"knowledge", "abnormal"}
        or not dataset.rows
    ):
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
    if not result.used_llm or result.degraded:
        return deterministic, {
            **result.public_metadata(),
            "decision_source": "rule_fallback",
        }

    # A model result is a proposal, not an approved mapping. Missing or
    # conflicting suggestions stay unmapped rather than being silently filled.
    sources = set(dataset.headers)
    targets = {field.key for field in adapter.fields}
    suggestions = [
        item
        for item in result.data.get("mappings") or []
        if isinstance(item, dict)
        and item.get("source") in sources
        and item.get("target") in targets
        and 0.85 <= float(item.get("confidence") or 0.0) <= 1.0
        and item.get("transform", "") in {"", "trim", "number", "date"}
    ]
    source_counts = Counter(item["source"] for item in suggestions)
    target_counts = Counter(item["target"] for item in suggestions)
    accepted = {
        item["target"]: item
        for item in suggestions
        if source_counts[item["source"]] == target_counts[item["target"]] == 1
    }
    enhanced = []
    for rule in deterministic:
        target = str(rule.get("target") or "")
        suggestion = accepted.get(target)
        if suggestion is None:
            enhanced.append(
                {
                    **rule,
                    "source": "",
                    "confidence": 0.0,
                    "transforms": [],
                    "suggested_by": "llm_unresolved",
                    "reason": "model_mapping_missing_or_ambiguous",
                }
            )
            continue
        transform = str(suggestion.get("transform") or "")
        enhanced.append(
            {
                **rule,
                "source": suggestion["source"],
                "confidence": float(suggestion["confidence"]),
                "transforms": [{"op": transform}] if transform else [],
                "suggested_by": "llm",
                "reason": str(suggestion.get("reason") or "")[:300],
            }
        )
    mapped_sources = {item["source"] for item in enhanced if item.get("source")}
    return enhanced, {
        **result.public_metadata(),
        "decision_source": "model",
        "suggestion_count": len(result.data.get("mappings") or []),
        "applied_count": len(accepted),
        "unmapped_targets": [item["target"] for item in enhanced if not item.get("source")],
        "unmapped_sources": [header for header in dataset.headers if header not in mapped_sources],
        "rule_candidates": deterministic,
    }


__all__ = ["enhance_mappings_with_llm"]
