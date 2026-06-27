from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "runtime",\n    "context",\n    "docs",\n    "symbols",\n    "tests",\n    "ci_config",\n    "config"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/aryanbrite/openrabbit",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627214507-0dc2a6fa81",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "Readme.md",\n      ".github/FUNDING.YML"\n    ],\n    "benchmarking": [\n      "package-lock.json"\n    ],\n    "context_packaging": [\n      "src/reviewer.ts"\n    ],\n    "elevation_bump_map": [\n      ".github/workflows/auto-version.yml"\n    ],\n    "file_grouping": [\n      ".github/CONTRIBUTING.md",\n      "src/reviewer.ts"\n    ],\n    "multi_provider": [\n      "reviewer.yml",\n      "Readme.md",\n      "action.yml",\n      "tests/groq.test.ts",\n      ".github/FUNDING.YML"\n    ],\n    "plugin_surface": [\n      "Readme.md",\n      "package-lock.json",\n      "package.json",\n      "action.yml",\n      "tests/groq.test.ts"\n    ],\n    "procedural_surface": [\n      "src/reviewer.ts"\n    ],\n    "review_pipeline": [\n      "Readme.md",\n      "package-lock.json",\n      "package.json",\n      "action.yml",\n      "tests/reviewer.test.ts"\n    ],\n    "safety_policy": [\n      "reviewer.yml",\n      "Readme.md",\n      "package-lock.json",\n      "action.yml",\n      ".github/CODE_OF_CONDUCT.md"\n    ],\n    "semantic_index": [\n      "src/reviewer.ts"\n    ],\n    "static_analysis": [\n      "Readme.md",\n      ".github/SECURITY.md",\n      "src/reviewer.ts"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "context_packaging",\n    "semantic_index",\n    "atmosphere_shader",\n    "procedural_surface",\n    "elevation_bump_map"\n  ],\n  "source": "https://github.com/aryanbrite/openrabbit"\n}')


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
