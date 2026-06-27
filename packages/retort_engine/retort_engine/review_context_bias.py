from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/openautocoder/agentless",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627194531-f1634167bd",\n  "signal_evidence": {\n    "benchmarking": [\n      "README_swebench.md",\n      "classification/README.md",\n      "classification/graph_classification.py",\n      "agentless/test/run_tests.py",\n      "agentless/test/run_reproduction_tests.py"\n    ],\n    "multi_provider": [\n      "README.md",\n      "README_swebench.md",\n      "agentless/test/generate_reproduction_tests.py",\n      "agentless/test/run_tests.py",\n      "agentless/test/run_reproduction_tests.py"\n    ],\n    "plugin_surface": [\n      "README_swebench.md",\n      "agentless/test/run_tests.py",\n      "agentless/util/preprocess_data.py",\n      "agentless/util/api_requests.py"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "README_swebench.md",\n      "agentless/fl/localize.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/openautocoder/agentless"\n}')


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
