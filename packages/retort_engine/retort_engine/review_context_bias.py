from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/TNG/ArchUnit",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627173253-72548897e8",\n  "signal_evidence": {\n    "benchmarking": [\n      "docs/_pages/motivation.md",\n      "docs/assets/js/main.min.js",\n      "docs/assets/js/vendor/jquery/jquery-3.2.1.min.js"\n    ],\n    "multi_provider": [\n      "docs/_includes/page__hero_video.html",\n      "docs/_includes/comments.html",\n      "docs/_layouts/single.html",\n      "docs/_layouts/splash.html",\n      "docs/_layouts/archive.html"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "CONTRIBUTING.md",\n      "docs/_config-dev.yml",\n      "docs/_config.yml",\n      "docs/_includes/tag-list.html"\n    ],\n    "review_pipeline": [\n      "docs/_pages/motivation.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/TNG/ArchUnit"\n}')


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
