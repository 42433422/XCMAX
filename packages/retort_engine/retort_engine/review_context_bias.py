from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/vercel-labs/openreview",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627170435-5782efe19c",\n  "signal_evidence": {\n    "benchmarking": [\n      ".agents/skills/vercel-react-native-skills/rules/scroll-position-no-state.md",\n      ".agents/skills/next-best-practices/self-hosting.md",\n      ".agents/skills/next-best-practices/data-patterns.md",\n      ".agents/skills/vercel-react-best-practices/README.md",\n      ".agents/skills/vercel-react-best-practices/SKILL.md"\n    ],\n    "file_grouping": [\n      "lib/agent.ts"\n    ],\n    "multi_provider": [\n      "README.md",\n      ".agents/skills/next-best-practices/rsc-boundaries.md",\n      ".agents/skills/next-best-practices/debug-tricks.md",\n      ".agents/skills/vercel-react-best-practices/AGENTS.md",\n      ".agents/skills/vercel-react-best-practices/rules/bundle-preload.md"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "tsconfig.json",\n      "app/components/readme.tsx",\n      ".agents/skills/vercel-react-native-skills/README.md",\n      ".agents/skills/vercel-react-native-skills/SKILL.md"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "app/layout.tsx",\n      "lib/agent.ts"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/vercel-labs/openreview"\n}')


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
