"""Absorbed review ranking weights that change review_diff behavior.

Synthesized by absorption_synthesizer from external review signals. This is a
behavior module (not a registry-only bridge): pr_review reads these boosts when
ranking external diagnostics and capabilities.
"""

from __future__ import annotations

import json
from typing import Any

ABSORBED_REVIEW_RANK_WEIGHTS: dict[str, Any] = json.loads(
    '{"capability_boosts": {"cross_language_transfer": 0, "external_diagnostic_ingestion": 20, "hunk_semantic_review": 40}, "external_source_boosts": {"pr-agent": 15, "qodo": 15, "reviewdog": 20}, "rule_token_boosts": {"permission": 30, "secret": 30, "security": 30, "token": 30}, "run_id": "20260719151907-f7cfdfd7bc", "schema_version": 1, "source": "https://github.com/alibaba/open-code-review"}'
)


def absorbed_rank_weights() -> dict[str, Any]:
    return dict(ABSORBED_REVIEW_RANK_WEIGHTS)


def external_source_boost(source: str, rule_id: str = "") -> int:
    source_lower = source.lower()
    rule_lower = rule_id.lower()
    boost = 0
    for token, value in (
        ABSORBED_REVIEW_RANK_WEIGHTS.get("external_source_boosts") or {}
    ).items():
        if str(token).lower() in source_lower:
            boost += int(value)
    for token, value in (
        ABSORBED_REVIEW_RANK_WEIGHTS.get("rule_token_boosts") or {}
    ).items():
        if str(token).lower() in rule_lower:
            boost += int(value)
    return boost


def capability_rank_boost(capability: str) -> int:
    boosts = ABSORBED_REVIEW_RANK_WEIGHTS.get("capability_boosts") or {}
    return int(boosts.get(str(capability or ""), 0) or 0)
