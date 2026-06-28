from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/packages/retort_engine/.retort/cache/github/anthropics/claude-code-security-review",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260628141803-755b966889",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.md",\n      "claudecode/test_hard_exclusion_rules.py",\n      "claudecode/test_prompts.py",\n      "claudecode/test_eval_engine.py",\n      "claudecode/prompts.py"\n    ],\n    "file_grouping": [\n      "README.md"\n    ],\n    "multi_provider": [\n      "README.md",\n      "action.yml",\n      "claudecode/github_action_audit.py",\n      "claudecode/test_workflow_integration.py",\n      "claudecode/constants.py"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "action.yml",\n      "claudecode/test_github_action_audit.py",\n      "claudecode/github_action_audit.py",\n      "claudecode/test_workflow_integration.py"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "action.yml",\n      "claudecode/prompts.py",\n      "claudecode/evals/README.md",\n      ".claude/commands/security-review.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/anthropics/claude-code-security-review"\n}')


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
    signal_weights = {
        "file_grouping": 24,
        "review_pipeline": 24,
        "diff_hunk_review": 20,
        "benchmarking": 16,
        "safety_policy": 16,
        "workflow_ci": 8,
        "plugin_surface": 10,
        "multi_provider": 10,
    }
    return min(100, sum(signal_weights.get(signal, 0) for signal in signals))
