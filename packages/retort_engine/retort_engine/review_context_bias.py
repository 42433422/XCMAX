from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/reviewdog/reviewdog",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627210037-4436ac66e6",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "CHANGELOG.md",\n      "doghouse/appengine/app.yaml",\n      "doghouse/appengine/main.go",\n      "doghouse/appengine/secret/README.md",\n      "doghouse/server/storage/token.go"\n    ],\n    "benchmarking": [\n      "parser/sarif_test.go"\n    ],\n    "elevation_bump_map": [\n      "README.md",\n      ".github/CONTRIBUTING.md",\n      ".github/workflows/release.yml"\n    ],\n    "file_grouping": [\n      "filter/diff_filter.go",\n      "filter/filter.go"\n    ],\n    "multi_provider": [\n      "CHANGELOG.md",\n      "package-lock.json",\n      "proto/rdf/README.md"\n    ],\n    "plugin_surface": [\n      "CHANGELOG.md",\n      "README.md",\n      "package-lock.json",\n      ".config/binstaller.yml",\n      "cmd/reviewdog/doghouse.go"\n    ],\n    "review_pipeline": [\n      "README.md",\n      ".goreleaser.yml",\n      "proto/rdf/README.md",\n      "cienv/_testdata/github_event_push.json",\n      "cienv/_testdata/github_event_rerun.json"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider",\n    "atmosphere_shader",\n    "elevation_bump_map"\n  ],\n  "source": "https://github.com/reviewdog/reviewdog"\n}')


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
