from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/evalops/diffscope",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627160755-f8e6a7af99",\n  "signal_evidence": {\n    "benchmarking": [\n      "Cargo.toml",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "CLAUDE.md",\n      "action.yml"\n    ],\n    "multi_provider": [\n      "CHANGELOG.md",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "docker-compose.yml",\n      "FEATURES.md"\n    ],\n    "plugin_surface": [\n      "Cargo.toml",\n      "CHANGELOG.md",\n      "README.md",\n      "rust-toolchain.toml",\n      "CLAUDE.md"\n    ],\n    "review_pipeline": [\n      "Cargo.toml",\n      "CHANGELOG.md",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "FEATURES.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/evalops/diffscope"\n}')


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
