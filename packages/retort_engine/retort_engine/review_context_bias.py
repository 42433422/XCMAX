from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/anc95/ChatGPT-CodeReview",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627204837-5df07f797f",\n  "signal_evidence": {\n    "codebase_graph": [\n      "rollup.config.ts",\n      "package-lock.json",\n      "tsconfig.json",\n      "action/worker1.js"\n    ],\n    "file_grouping": [\n      "README.md"\n    ],\n    "multi_provider": [\n      "serverless.yml",\n      "README.md",\n      "README.ja.md",\n      "README.zh-TW.md",\n      "package-lock.json"\n    ],\n    "plugin_surface": [\n      "rollup.config.ts",\n      "README.md",\n      "README.ja.md",\n      "README.zh-TW.md",\n      "package-lock.json"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "README.ja.md",\n      "README.zh-TW.md",\n      "package.json",\n      "README.zh-CN.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/anc95/ChatGPT-CodeReview"\n}')


def review_context_bias() -> dict[str, Any]:
    """Return the absorbed context grouping profile used by PR review."""
    return dict(REVIEW_CONTEXT_BIAS)


def file_grouping_enabled() -> bool:
    """Tell PR review whether absorbed external evidence supports context grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return bool(REVIEW_CONTEXT_BIAS.get("enabled")) and bool(signals & {"file_grouping", "review_pipeline", "diff_hunk_review"})


def context_signal_strength() -> int:
    """Score how much absorbed evidence should influence review grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return min(100, 20 * len(signals & {"file_grouping", "review_pipeline", "diff_hunk_review", "benchmarking", "safety_policy"}))
