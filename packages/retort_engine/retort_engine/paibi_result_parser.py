from __future__ import annotations

import json
from typing import Any

from retort_engine.paibi_prompting import RETORT_SCORE_DIMENSIONS


def extract_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    best_scoring: dict[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            if isinstance(value.get("scores"), list) or "score_suggestion" in value:
                best_scoring = value
            best = value
    return best_scoring or best


def normalize_llm_scores(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_scores = payload.get("scores")
    scores: list[dict[str, Any]] = []
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension") or "").strip()
            if dimension not in RETORT_SCORE_DIMENSIONS:
                continue
            try:
                value = max(0.0, min(100.0, float(item.get("value"))))
            except (TypeError, ValueError):
                continue
            evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
            scores.append(
                {
                    "dimension": dimension,
                    "value": round(value, 1),
                    "reason": str(item.get("reason") or "LLM score from Retort scoring prompt."),
                    "evidence": [str(row) for row in evidence],
                }
            )
    existing = {score["dimension"] for score in scores}
    if "calibrated_overall" not in existing:
        suggestion = payload.get("score_suggestion")
        try:
            value = max(0.0, min(100.0, float(suggestion)))
        except (TypeError, ValueError):
            value = -1.0
        if value >= 0:
            scores.append(
                {
                    "dimension": "calibrated_overall",
                    "value": round(value, 1),
                    "reason": "LLM score_suggestion normalized as calibrated_overall.",
                    "evidence": [],
                }
            )
    return scores
