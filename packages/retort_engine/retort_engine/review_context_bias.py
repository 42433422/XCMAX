from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/sunerpy/codegraph-rust",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627195002-b40d2378d6",\n  "signal_evidence": {\n    "benchmarking": [\n      "Cargo.toml",\n      "audit.toml",\n      "AGENTS.md",\n      "docs/architecture.md",\n      "docs/readme/README.zh-CN.md"\n    ],\n    "elevation_bump_map": [\n      "cliff.toml",\n      "AGENTS.md",\n      "release-please-config.json",\n      "changelog/CHANGELOG-v0.x.md",\n      "changelog/README.md"\n    ],\n    "file_grouping": [\n      "docs/cli.md"\n    ],\n    "multi_provider": [\n      "README.md",\n      "AGENTS.md",\n      "docs/architecture.md",\n      "docs/embedded-extraction.md",\n      "docs/data-model.md"\n    ],\n    "plugin_surface": [\n      "Cargo.toml",\n      "README.md",\n      "cliff.toml",\n      "AGENTS.md",\n      "crates/codegraph-cli/Cargo.toml"\n    ],\n    "procedural_surface": [\n      "docs/cli.md",\n      "docs/godot.md"\n    ],\n    "webgl_scene": [\n      "changelog/CHANGELOG-v0.x.md",\n      "docs/cli.md",\n      "docs/languages.md",\n      "docs/godot.md",\n      "reference/golden/mcp/initialize.json"\n    ]\n  },\n  "signals": [\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider",\n    "procedural_surface",\n    "webgl_scene",\n    "elevation_bump_map"\n  ],\n  "source": "https://github.com/sunerpy/codegraph-rust"\n}')


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
