from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/nedbat/coveragepy",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627173057-8f77226be1",\n  "signal_evidence": {\n    "benchmarking": [\n      "igor.py",\n      "lab/goals.py",\n      "tests/test_results.py",\n      "tests/test_debug.py",\n      "tests/test_templite.py"\n    ],\n    "file_grouping": [\n      "tests/test_html.py",\n      ".github/workflows/coverage.yml",\n      ".github/workflows/quality.yml",\n      ".github/workflows/testsuite.yml"\n    ],\n    "multi_provider": [\n      "tests/test_concurrency.py",\n      "tests/test_cmdline.py",\n      "coverage/files.py"\n    ],\n    "plugin_surface": [\n      "pyproject.toml",\n      "ci/trigger_action.py",\n      "lab/parser.py",\n      "lab/pick.py",\n      "tests/select_plugin.py"\n    ]\n  },\n  "signals": [\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/nedbat/coveragepy"\n}')


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
