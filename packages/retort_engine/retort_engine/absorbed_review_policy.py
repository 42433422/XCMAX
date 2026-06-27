from __future__ import annotations

import json
from typing import Any


ABSORBED_REVIEW_POLICY: dict[str, Any] = json.loads('{\n  "context_rank_overrides": {\n    "ci_config": 15,\n    "config": 15,\n    "docs": 15,\n    "frontend": 0,\n    "other": 0,\n    "runtime": 45,\n    "security": 25,\n    "tests": 40\n  },\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/qodo-ai/pr-agent",\n  "reason": "absorbed external review policy affects PR comment ordering",\n  "run_id": "20260627235555-f62954c70a",\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "semantic_index",\n    "atmosphere_shader",\n    "procedural_surface",\n    "cloud_texture_layer",\n    "elevation_bump_map",\n    "specular_ocean"\n  ],\n  "source": "packages/retort_engine/.retort/cache/github/qodo-ai/pr-agent"\n}')


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
