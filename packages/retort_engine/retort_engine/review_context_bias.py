from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "symbols",\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/jaygaha/local-ai-pr-reviewer",\n  "external_paths": [\n    "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/hevinbryant/ai-pr-reviewer",\n    "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/jaygaha/local-ai-pr-reviewer"\n  ],\n  "reason": "merged external file grouping and review pipeline signals",\n  "run_id": "20260627224409-8893c01ae8",\n  "run_ids": [\n    "20260627222436-02cbea1e01",\n    "20260627224409-8893c01ae8"\n  ],\n  "signal_evidence": {\n    "codebase_graph": [\n      "reviewer.py"\n    ],\n    "file_grouping": [\n      "README.md",\n      "action.yml",\n      "src/reviewer.py",\n      "src/main.py",\n      "src/github_client.py"\n    ],\n    "multi_provider": [\n      "README.md",\n      "action.yml",\n      "src/reviewer.py",\n      "src/main.py",\n      "reviewer.py"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "src/reviewer.py",\n      "src/main.py",\n      "src/github_client.py"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "action.yml",\n      "src/__init__.py",\n      "src/reviewer.py",\n      "src/main.py",\n      "reviewer.py"\n    ],\n    "safety_policy": [\n      "README.md",\n      "src/reviewer.py",\n      "reviewer.py"\n    ],\n    "semantic_index": [\n      "src/reviewer.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "semantic_index",\n    "codebase_graph"\n  ],\n  "source": "https://github.com/jaygaha/local-ai-pr-reviewer",\n  "sources": [\n    "https://github.com/hevinbryant/ai-pr-reviewer",\n    "https://github.com/jaygaha/local-ai-pr-reviewer"\n  ]\n}')


def review_context_bias() -> dict[str, Any]:
    """Return the absorbed context grouping profile used by PR review."""
    return dict(REVIEW_CONTEXT_BIAS)


def file_grouping_enabled() -> bool:
    """Tell PR review whether absorbed external evidence supports context grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return bool(REVIEW_CONTEXT_BIAS.get("enabled")) and bool(signals & {"file_grouping", "review_pipeline", "diff_hunk_review", "context_packaging", "semantic_index"})


def context_signal_strength() -> int:
    """Score how much absorbed evidence should influence review grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return min(100, 20 * len(signals & {"file_grouping", "review_pipeline", "diff_hunk_review", "benchmarking", "safety_policy", "static_analysis", "context_packaging", "semantic_index"}))


def context_rank_weight(review_context: str) -> int:
    """Return absorbed context weight used by the main PR review ranking path."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    focus = set(REVIEW_CONTEXT_BIAS.get("context_focus") or [])
    context = str(review_context or "other")
    weight = 20 if context in focus else 0
    if context == "security" and signals & {"safety_policy", "static_analysis"}:
        weight += 30
    if context in {"runtime", "tests", "ci_config"} and signals & {"review_pipeline", "file_grouping", "diff_hunk_review"}:
        weight += 20
    if context == "runtime" and signals & {"semantic_index", "codebase_graph"}:
        weight += 15
    if context == "docs" and signals & {"context_packaging"}:
        weight += 10
    return min(70, weight)


def context_rank_weights() -> dict[str, int]:
    """Expose the absorbed ranking model for audit and LLM evidence."""
    return {context: context_rank_weight(context) for context in ("security", "runtime", "tests", "ci_config", "config", "frontend", "docs", "other")}
