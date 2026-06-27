from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/mopemope/pr-ai-review-bot",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627183417-fe4938a18b",\n  "signal_evidence": {\n    "benchmarking": [\n      "__tests__/reviewer.test.ts",\n      "__tests__/prompts.test.ts",\n      "src/prompts.ts",\n      "src/option.ts"\n    ],\n    "file_grouping": [\n      "README.md",\n      "action.yml",\n      "__tests__/prompts.test.ts",\n      "src/main.ts",\n      "src/commenter.ts"\n    ],\n    "multi_provider": [\n      "README.md",\n      "package-lock.json",\n      "package.json",\n      "AGENTS.md",\n      "action.yml"\n    ],\n    "plugin_surface": [\n      "rollup.config.ts",\n      "README.md",\n      ".licensed.yml",\n      "package-lock.json",\n      "package.json"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "package-lock.json",\n      "package.json",\n      "AGENTS.md",\n      "action.yml"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/mopemope/pr-ai-review-bot"\n}')


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
