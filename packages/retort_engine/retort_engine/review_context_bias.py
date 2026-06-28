from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/packages/retort_engine/.retort/cache/github/existential-birds/daydream",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260628175502-a237875a09",\n  "signal_evidence": {\n    "benchmarking": [\n      "CHANGELOG.md",\n      "README.md",\n      "bench/review-bot-compare/README.md",\n      "bench/review-bot-compare/replay.py",\n      "bench/review-bot-compare/compare.py"\n    ],\n    "file_grouping": [\n      "CHANGELOG.md",\n      "bench/review-bot-compare/test_replay.py",\n      "tests/conftest.py",\n      "tests/test_worktree_cwd_grounding.py",\n      "tests/test_deep_pr_comment_integration.py"\n    ],\n    "multi_provider": [\n      "CHANGELOG.md",\n      "README.md",\n      "CLAUDE.md",\n      "bench/review-bot-compare/test_replay.py",\n      "bench/review-bot-compare/README.md"\n    ],\n    "plugin_surface": [\n      "CHANGELOG.md",\n      "pyproject.toml",\n      "README.md",\n      "CLAUDE.md",\n      "bench/review-bot-compare/README.md"\n    ],\n    "review_pipeline": [\n      "CHANGELOG.md",\n      "pyproject.toml",\n      "README.md",\n      "CLAUDE.md",\n      "bench/review-bot-compare/replay.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/existential-birds/daydream"\n}')


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
