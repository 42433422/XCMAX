from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/Review-scope/ReviewScope",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627155419-6cc7a9e742",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md",\n      "packages/rules-engine/src/rules/ai-sanity.ts",\n      "packages/llm-core/src/prompts.ts"\n    ],\n    "file_grouping": [\n      "docs/ARCHITECTURE.md",\n      "packages/rules-engine/src/rules/reviewscope.ts",\n      "packages/context-engine/src/layers.ts",\n      "apps/worker/src/lib/validation.ts"\n    ],\n    "multi_provider": [\n      "ReviewScope.md",\n      "docker-compose.dev.yml",\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md"\n    ],\n    "plugin_surface": [\n      "docker-compose.dev.yml",\n      "README.md",\n      "package-lock.json",\n      "package.json",\n      "docs/USER_GUIDE.md"\n    ],\n    "review_pipeline": [\n      "ReviewScope.md",\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md",\n      "packages/context-engine/src/layers/system-guardrails.ts"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/Review-scope/ReviewScope"\n}')


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
