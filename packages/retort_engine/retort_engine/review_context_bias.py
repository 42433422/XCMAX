from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/private/tmp/retort-depth-source-zULAcN",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627182658-daf3bca93f",\n  "signal_evidence": {\n    "benchmarking": [\n      "eval/benchmark.md"\n    ],\n    "file_grouping": [\n      "review/pipeline.py",\n      "review/grouping.ts"\n    ],\n    "multi_provider": [\n      "plugins/action.yml"\n    ],\n    "plugin_surface": [\n      "plugins/action.yml"\n    ],\n    "review_pipeline": [\n      "review/pipeline.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "/private/tmp/retort-depth-source-zULAcN"\n}')


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
