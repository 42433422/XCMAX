from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/Sourish-19/ai-pr-reviewer",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627220056-7db1f7d16a",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "frontend/src/components/PhilosophySection.tsx",\n      "frontend/src/components/ServicesSection.tsx",\n      "frontend/src/components/FeaturedVideoSection.tsx",\n      "frontend/src/components/HeroSection.tsx"\n    ],\n    "benchmarking": [\n      "README.md",\n      "frontend/src/components/FeaturedVideoSection.tsx"\n    ],\n    "codebase_graph": [\n      "frontend/package-lock.json"\n    ],\n    "multi_provider": [\n      "src/ai_engine.py",\n      "src/api.py"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "package-lock.json",\n      "main.py",\n      "frontend/package-lock.json",\n      "frontend/package.json"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "frontend/index.html",\n      "frontend/package-lock.json",\n      "frontend/package.json",\n      "frontend/src/components/AboutSection.tsx"\n    ],\n    "safety_policy": [\n      "README.md",\n      "frontend/metadata.json",\n      "frontend/package-lock.json",\n      "frontend/src/App.tsx",\n      "frontend/src/components/PhilosophySection.tsx"\n    ],\n    "static_analysis": [\n      "frontend/src/components/ServicesSection.tsx"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "atmosphere_shader"\n  ],\n  "source": "https://github.com/Sourish-19/ai-pr-reviewer"\n}')


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
