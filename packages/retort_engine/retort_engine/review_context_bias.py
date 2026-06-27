from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/continuedev/continue",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627172525-c3d6b79c6a",\n  "signal_evidence": {\n    "benchmarking": [\n      "core/nextEdit/NextEditProvider.ts",\n      "core/nextEdit/constants.ts",\n      "core/nextEdit/context/autocompleteContextFetching.ts",\n      "core/tools/index.ts",\n      "core/tools/systemMessageTools/toolCodeblocks/buildSystemMessage.vitest.ts"\n    ],\n    "multi_provider": [\n      "TESTING.md",\n      "BUILD_DEPENDENCIES.md",\n      "package-lock.json",\n      "CONTRIBUTING.md",\n      "docs-site/app/layout.tsx"\n    ],\n    "plugin_surface": [\n      "TESTING.md",\n      "README.md",\n      "BUILD_DEPENDENCIES.md",\n      "package-lock.json",\n      "package.json"\n    ],\n    "review_pipeline": [\n      "CONTRIBUTING.md",\n      "core/util/sanitization.ts"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/continuedev/continue"\n}')


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
