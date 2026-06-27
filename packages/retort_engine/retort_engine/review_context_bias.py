from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/qodo-ai/pr-agent",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627172352-6e1352f61e",\n  "signal_evidence": {\n    "benchmarking": [\n      "CHANGELOG.md",\n      "pr_agent/settings/pr_evaluate_prompt_response.toml",\n      "pr_agent/settings/code_suggestions/pr_code_suggestions_reflect_prompts.toml",\n      "pr_agent/tools/pr_help_message.py",\n      "pr_agent/algo/token_handler.py"\n    ],\n    "file_grouping": [\n      "pr_agent/settings/pr_reviewer_prompts.toml",\n      "pr_agent/settings/code_suggestions/pr_code_suggestions_prompts_not_decoupled.toml",\n      "pr_agent/git_providers/local_git_provider.py",\n      "pr_agent/git_providers/gerrit_provider.py"\n    ],\n    "multi_provider": [\n      "CHANGELOG.md",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "AGENTS.md",\n      "SECURITY.md"\n    ],\n    "plugin_surface": [\n      "pyproject.toml",\n      "README.md",\n      "RELEASE_NOTES.md",\n      "AGENTS.md",\n      "SECURITY.md"\n    ],\n    "review_pipeline": [\n      "pyproject.toml",\n      "README.md",\n      ".pr_agent.toml",\n      "AGENTS.md",\n      "docker/mosaico/pr-agent-solution-agent.json"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/qodo-ai/pr-agent"\n}')


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
