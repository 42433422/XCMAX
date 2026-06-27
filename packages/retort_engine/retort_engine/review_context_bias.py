from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/OpenHands/software-agent-sdk",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627171611-61b3c3e350",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.md",\n      "CONTRIBUTING.md",\n      "AGENTS.md",\n      "openhands-agent-server/AGENTS.md",\n      "openhands-agent-server/openhands/agent_server/event_service.py"\n    ],\n    "file_grouping": [\n      "AGENTS.md",\n      "openhands-sdk/openhands/sdk/git/git_changes.py"\n    ],\n    "multi_provider": [\n      "README.md",\n      "AGENTS.md",\n      "openhands-agent-server/pyproject.toml",\n      "openhands-agent-server/AGENTS.md",\n      "openhands-agent-server/openhands/agent_server/file_router.py"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "CONTRIBUTING.md",\n      "AGENTS.md",\n      "openhands-agent-server/AGENTS.md",\n      "openhands-agent-server/openhands/agent_server/conversation_router.py"\n    ],\n    "review_pipeline": [\n      "AGENTS.md",\n      "openhands-tools/openhands/tools/workflow/definition.py",\n      "openhands-sdk/openhands/sdk/subagent/AGENTS.md",\n      "openhands-sdk/openhands/sdk/subagent/load.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/OpenHands/software-agent-sdk"\n}')


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
