from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "runtime",\n    "symbols",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/AndreaBonn/ai-pr-reviewer",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627221413-310a494b4a",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.it.md"\n    ],\n    "elevation_bump_map": [\n      "CHANGELOG.md"\n    ],\n    "file_grouping": [\n      "reviewer/prompt.py"\n    ],\n    "multi_provider": [\n      "README.it.md",\n      "review.py",\n      "README.md",\n      "SECURITY.it.md",\n      "SECURITY.md"\n    ],\n    "plugin_surface": [\n      "README.it.md",\n      "pyproject.toml",\n      "review.py",\n      "README.md",\n      "reviewer/github_client.py"\n    ],\n    "review_pipeline": [\n      "README.it.md",\n      "pyproject.toml",\n      "review.py",\n      "README.md",\n      "SECURITY.it.md"\n    ],\n    "safety_policy": [\n      "README.it.md",\n      "pyproject.toml",\n      "README.md",\n      "SECURITY.it.md",\n      "SECURITY.md"\n    ],\n    "semantic_index": [\n      "README.md"\n    ],\n    "static_analysis": [\n      "README.md",\n      "SECURITY.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "semantic_index",\n    "elevation_bump_map"\n  ],\n  "source": "https://github.com/AndreaBonn/ai-pr-reviewer"\n}')


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
