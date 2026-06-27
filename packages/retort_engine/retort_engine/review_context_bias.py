from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "symbols",\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/hevinbryant/ai-pr-reviewer",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627222436-02cbea1e01",\n  "signal_evidence": {\n    "file_grouping": [\n      "README.md",\n      "action.yml",\n      "src/reviewer.py",\n      "src/main.py",\n      "src/github_client.py"\n    ],\n    "multi_provider": [\n      "README.md",\n      "action.yml",\n      "src/reviewer.py",\n      "src/main.py"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "src/reviewer.py",\n      "src/main.py",\n      "src/github_client.py"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "action.yml",\n      "src/__init__.py",\n      "src/reviewer.py",\n      "src/main.py"\n    ],\n    "safety_policy": [\n      "README.md",\n      "src/reviewer.py"\n    ],\n    "semantic_index": [\n      "src/reviewer.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "semantic_index"\n  ],\n  "source": "https://github.com/hevinbryant/ai-pr-reviewer"\n}')


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
