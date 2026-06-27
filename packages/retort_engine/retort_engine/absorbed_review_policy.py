from __future__ import annotations

from typing import Any


ABSORBED_REVIEW_POLICY: dict[str, Any] = {
    "enabled": False,
    "source": "",
    "run_id": "",
    "signals": [],
    "context_rank_overrides": {},
}


def absorbed_review_policy() -> dict[str, Any]:
    return dict(ABSORBED_REVIEW_POLICY)


def policy_context_rank_weight(review_context: str) -> int:
    policy = absorbed_review_policy()
    if not policy.get("enabled"):
        return 0
    weights = policy.get("context_rank_overrides") if isinstance(policy.get("context_rank_overrides"), dict) else {}
    return int(weights.get(str(review_context or "other"), 0) or 0)


def policy_context_rank_weights() -> dict[str, int]:
    contexts = ("security", "runtime", "tests", "ci_config", "config", "frontend", "docs", "other")
    return {context: policy_context_rank_weight(context) for context in contexts}


def policy_summary() -> dict[str, Any]:
    policy = absorbed_review_policy()
    weights = policy_context_rank_weights()
    return {
        "enabled": bool(policy.get("enabled")),
        "source": str(policy.get("source") or ""),
        "run_id": str(policy.get("run_id") or ""),
        "signal_count": len(policy.get("signals") or []),
        "weighted_context_count": sum(1 for value in weights.values() if value > 0),
        "max_context_weight": max(weights.values() or [0]),
    }
