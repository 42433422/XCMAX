from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "security",\n    "runtime",\n    "context",\n    "docs",\n    "symbols",\n    "tests",\n    "ci_config",\n    "config"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/yamadashy/repomix",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627212946-168c95fefd",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "website/compose.bundle.yml",\n      "website/server/cloudbuild.yaml",\n      "website/server/package.json",\n      "website/server/tests/turnstile.test.ts",\n      "website/server/monitoring/README.md"\n    ],\n    "benchmarking": [\n      "repomix-instruction.md",\n      "llms-install.md",\n      "README.md",\n      "website/server/src/domains/pack/remoteRepo.ts",\n      "website/server/src/actions/packRequestSchema.ts"\n    ],\n    "cloud_texture_layer": [\n      "website/server/cloudbuild.yaml"\n    ],\n    "codebase_graph": [\n      "biome.json",\n      "website/.claude/skills/website-maintainer/SKILL.md",\n      "website/server/tests/packEventSchema.test.ts",\n      "website/client/tsconfig.node.json",\n      "website/client/package-lock.json"\n    ],\n    "context_packaging": [\n      "website/client/src/hi/guide/faq.md",\n      "website/client/src/en/index.md",\n      "website/client/src/en/guide/faq.md",\n      "website/client/src/en/guide/index.md",\n      "website/client/src/en/guide/configuration.md"\n    ],\n    "file_grouping": [\n      "website/client/src/en/guide/command-line-options.md"\n    ],\n    "multi_provider": [\n      "README.md",\n      "package-lock.json",\n      "package.json",\n      "website/server/package-lock.json",\n      "website/client/package-lock.json"\n    ],\n    "plugin_surface": [\n      "typos.toml",\n      "repomix-instruction.md",\n      "llms-install.md",\n      "README.md",\n      "package-lock.json"\n    ],\n    "procedural_surface": [\n      "website/client/src/hi/guide/comment-removal.md",\n      "website/client/src/id/guide/configuration.md",\n      "website/client/src/id/guide/comment-removal.md",\n      "website/client/src/en/guide/configuration.md",\n      "website/client/src/en/guide/comment-removal.md"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "website/client/src/vi/index.md",\n      "website/client/src/vi/guide/prompt-examples.md",\n      "website/client/src/vi/guide/github-actions.md",\n      "website/client/src/vi/guide/use-cases.md"\n    ],\n    "safety_policy": [\n      ".secretlintrc.json",\n      "CODE_OF_CONDUCT.md",\n      "repomix-instruction.md",\n      "llms-install.md",\n      "README.md"\n    ],\n    "semantic_index": [\n      "AGENTS.md",\n      "CLAUDE.md",\n      "website/server/monitoring/README.md",\n      "website/server/src/utils/errorHandler.ts",\n      "website/server/src/utils/logger.ts"\n    ],\n    "static_analysis": [\n      "SECURITY.md",\n      "website/server/src/domains/pack/processZipFile.ts",\n      "website/server/src/domains/pack/utils/fileUtils.ts",\n      "website/client/src/en/guide/claude-code-plugins.md",\n      "website/client/src/en/guide/use-cases.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider",\n    "safety_policy",\n    "static_analysis",\n    "context_packaging",\n    "semantic_index",\n    "atmosphere_shader",\n    "procedural_surface",\n    "cloud_texture_layer"\n  ],\n  "source": "https://github.com/yamadashy/repomix"\n}')


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
