from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "runtime",\n    "context",\n    "docs",\n    "symbols",\n    "tests",\n    "ci_config",\n    "config"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/Review-scope/ReviewScope",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627213722-6cc7a9e742",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "ReviewScope.md",\n      "apps/dashboard/src/app/layout.tsx",\n      "apps/dashboard/src/app/privacy/page.tsx"\n    ],\n    "benchmarking": [\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md",\n      "packages/rules-engine/src/rules/ai-sanity.ts",\n      "packages/llm-core/src/prompts.ts"\n    ],\n    "codebase_graph": [\n      "tsconfig.base.json",\n      "package-lock.json",\n      "packages/context-engine/src/layers.ts",\n      "packages/context-engine/src/layers/related-files.ts",\n      "apps/dashboard/src/app/page.tsx"\n    ],\n    "context_packaging": [\n      "packages/llm-core/src/prompts.ts",\n      "apps/dashboard/src/app/page.tsx"\n    ],\n    "elevation_bump_map": [\n      "apps/worker/src/jobs/review.ts"\n    ],\n    "file_grouping": [\n      "docs/ARCHITECTURE.md",\n      "packages/rules-engine/src/rules/reviewscope.ts",\n      "packages/context-engine/src/layers.ts",\n      "apps/worker/src/lib/validation.ts"\n    ],\n    "multi_provider": [\n      "ReviewScope.md",\n      "docker-compose.dev.yml",\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md"\n    ],\n    "plugin_surface": [\n      "docker-compose.dev.yml",\n      "README.md",\n      "package-lock.json",\n      "package.json",\n      "docs/USER_GUIDE.md"\n    ],\n    "procedural_surface": [\n      "packages/rules-engine/src/rules/reliability.ts",\n      "packages/llm-core/src/prompts.ts",\n      "apps/dashboard/src/app/layout.tsx",\n      "apps/dashboard/src/app/page.tsx",\n      "apps/dashboard/src/app/pricing/pricing-client.tsx"\n    ],\n    "review_pipeline": [\n      "ReviewScope.md",\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md",\n      "packages/context-engine/src/layers/system-guardrails.ts"\n    ],\n    "safety_policy": [\n      "ReviewScope.md",\n      "tsconfig.base.json",\n      "docker-compose.dev.yml",\n      "README.md",\n      "package-lock.json"\n    ],\n    "semantic_index": [\n      "tsconfig.json",\n      "packages/rules-engine/src/parsers/python.ts",\n      "packages/context-engine/src/layers/related-files.ts",\n      "packages/llm-core/src/prompts.ts",\n      "apps/dashboard/README.md"\n    ],\n    "static_analysis": [\n      "README.md",\n      "docs/USER_GUIDE.md",\n      "docs/ARCHITECTURE.md",\n      "packages/context-engine/src/layers.ts",\n      "apps/dashboard/src/app/page.tsx"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "context_packaging",\n    "semantic_index",\n    "atmosphere_shader",\n    "procedural_surface",\n    "elevation_bump_map"\n  ],\n  "source": "https://github.com/Review-scope/ReviewScope"\n}')


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
