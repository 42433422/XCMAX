from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/aider-ai/aider",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627171538-da950c021d",\n  "signal_evidence": {\n    "benchmarking": [\n      "HISTORY.md",\n      "README.md",\n      "CONTRIBUTING.md",\n      "benchmark/over_time.py",\n      "benchmark/benchmark.py"\n    ],\n    "multi_provider": [\n      "HISTORY.md",\n      "README.md",\n      "benchmark/over_time.py",\n      "benchmark/benchmark.py",\n      "benchmark/problem_stats.py"\n    ],\n    "plugin_surface": [\n      "HISTORY.md",\n      "README.md",\n      "CONTRIBUTING.md",\n      "aider/io.py",\n      "aider/copypaste.py"\n    ],\n    "review_pipeline": [\n      "aider/gui.py",\n      "aider/coders/base_coder.py",\n      "aider/coders/context_coder.py",\n      "aider/website/_posts/2024-06-02-main-swe-bench.md",\n      "aider/website/_posts/2024-05-22-swe-bench-lite.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/aider-ai/aider"\n}')


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
