from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "runtime",\n    "symbols",\n    "tests",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/semgrep/semgrep",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627212518-4985a95789",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "CHANGELOG.md",\n      "metrics.md"\n    ],\n    "benchmarking": [\n      "CHANGELOG.md",\n      "release_changes.md",\n      "tests/README.md",\n      "tests/misc/il/container.py",\n      "tests/misc/il/foreach.py"\n    ],\n    "codebase_graph": [\n      "CHANGELOG.md",\n      ".pre-commit-config.yaml",\n      "tests/patterns/python/scoped_wildcard.py"\n    ],\n    "elevation_bump_map": [\n      "CHANGELOG.md",\n      ".pre-commit-config.yaml"\n    ],\n    "multi_provider": [\n      "README.md",\n      "metrics.md",\n      "tests/patterns/python/metavar_kwd_arg.py"\n    ],\n    "plugin_surface": [\n      "CHANGELOG.md",\n      ".pre-commit-config.yaml",\n      "semgrep.yml",\n      "README.md",\n      "setup.py"\n    ],\n    "procedural_surface": [\n      "README.md"\n    ],\n    "safety_policy": [\n      "CODE_OF_CONDUCT.md",\n      "CHANGELOG.md",\n      ".pre-commit-hooks.yaml",\n      "README.md",\n      "setup.py"\n    ],\n    "semantic_index": [\n      "CHANGELOG.md",\n      ".pre-commit-config.yaml",\n      "README.md",\n      "CONTRIBUTING.md",\n      "metrics.md"\n    ],\n    "static_analysis": [\n      "CHANGELOG.md",\n      "README.md",\n      "AGENTS.md",\n      "SECURITY.md",\n      "tests/explanations/explain_taint.yaml"\n    ]\n  },\n  "signals": [\n    "benchmarking",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "semantic_index",\n    "atmosphere_shader",\n    "procedural_surface",\n    "elevation_bump_map"\n  ],\n  "source": "https://github.com/semgrep/semgrep"\n}')


def review_context_bias() -> dict[str, Any]:
    """Return the absorbed context grouping profile used by PR review."""
    return dict(REVIEW_CONTEXT_BIAS)


def file_grouping_enabled() -> bool:
    """Tell PR review whether absorbed external evidence supports context grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return bool(REVIEW_CONTEXT_BIAS.get("enabled")) and bool(signals & {"file_grouping", "review_pipeline", "diff_hunk_review", "context_packaging", "semantic_index"})


def context_signal_strength() -> int:
    """Score how much absorbed evidence should influence review grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return min(100, 20 * len(signals & {"file_grouping", "review_pipeline", "diff_hunk_review", "benchmarking", "safety_policy", "static_analysis", "context_packaging", "semantic_index"}))
