from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/SWE-agent/SWE-agent",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627172432-c09c7479ad",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.md",\n      "tools/web_browser/lib/browser_manager.py",\n      "config/bash_only.yaml",\n      "config/coding_challenge.yaml",\n      "config/benchmarks/250526_anthropic_filemap_simple_review_sbl.yaml"\n    ],\n    "multi_provider": [\n      "mkdocs.yml",\n      "pyproject.toml",\n      "README.md",\n      "mlc_config.json",\n      "tools/review_on_submit_m/config.yaml"\n    ],\n    "plugin_surface": [\n      "mkdocs.yml",\n      "pyproject.toml",\n      "README.md",\n      "tools/web_browser/config.yaml",\n      "tools/web_browser/lib/web_browser_config.py"\n    ],\n    "review_pipeline": [\n      "tests/test_data/data_sources/debug_20240322.json",\n      "sweagent/types.py",\n      "sweagent/agent/agents.py",\n      "sweagent/agent/reviewer.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/SWE-agent/SWE-agent"\n}')


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
