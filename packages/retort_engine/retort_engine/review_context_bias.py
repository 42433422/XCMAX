from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/packages/retort_engine/.retort/cache/github/shim52/ai-code-review-bench",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260628170457-3af65b9633",\n  "signal_evidence": {\n    "benchmarking": [\n      "CHANGELOG.md",\n      "pyproject.toml",\n      "README.md",\n      "DEVELOPMENT.md",\n      "SECURITY.md"\n    ],\n    "multi_provider": [\n      "CHANGELOG.md",\n      "pyproject.toml",\n      "README.md",\n      "DEVELOPMENT.md",\n      "challenges/missing-await-async/before/src/services/auth.ts"\n    ],\n    "plugin_surface": [\n      "CHANGELOG.md",\n      "pyproject.toml",\n      "README.md",\n      "DEVELOPMENT.md",\n      "challenges/insecure-deserialization/before/cache/session_store.py"\n    ],\n    "review_pipeline": [\n      "CHANGELOG.md",\n      "pyproject.toml",\n      "README.md",\n      "DEVELOPMENT.md",\n      "SECURITY.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/shim52/ai-code-review-bench"\n}')


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
    signal_weights = {
        "file_grouping": 24,
        "review_pipeline": 24,
        "diff_hunk_review": 20,
        "benchmarking": 16,
        "safety_policy": 16,
        "workflow_ci": 8,
        "plugin_surface": 10,
        "multi_provider": 10,
    }
    return min(100, sum(signal_weights.get(signal, 0) for signal in signals))
