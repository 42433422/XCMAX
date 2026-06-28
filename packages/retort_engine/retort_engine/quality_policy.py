from __future__ import annotations

from typing import Any


DEFAULT_LLM_WAIT_SEC = 12.0
TEST_TO_SOURCE_HEALTHY_RATIO = 0.4


def apply_default_llm_policy(payload: dict[str, Any], *, require_scores: bool = False) -> dict[str, Any]:
    normalized = dict(payload)
    explicit_disable = bool(normalized.pop("no_llm", False))
    llm_keys = {"use_llm", "paibi_llm", "llm_review"}
    for key in tuple(llm_keys):
        if normalized.get(key) is None:
            normalized.pop(key, None)
    for key in ("wait_llm_sec", "wait_llm_seconds"):
        if normalized.get(key) is None:
            normalized.pop(key, None)
    if explicit_disable:
        normalized["use_llm"] = False
        normalized.setdefault("require_deep_review", False)
        normalized["llm_default_policy"] = "explicitly_disabled"
        return normalized
    if not any(key in normalized for key in llm_keys):
        normalized["use_llm"] = True
        normalized["llm_default_policy"] = "enabled_by_default"
    else:
        normalized["llm_default_policy"] = "explicit"
    if require_scores and "require_deep_review" not in normalized:
        normalized["require_deep_review"] = True
    else:
        normalized.setdefault("require_deep_review", False)
    if normalized.get("use_llm") and "wait_llm_sec" not in normalized and "wait_llm_seconds" not in normalized:
        normalized["wait_llm_sec"] = DEFAULT_LLM_WAIT_SEC
    return normalized


def test_source_ratio_status(ratio: float | None, *, target: float = TEST_TO_SOURCE_HEALTHY_RATIO) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= target:
        return "healthy"
    if ratio >= target * 0.7:
        return "watch"
    return "low"
