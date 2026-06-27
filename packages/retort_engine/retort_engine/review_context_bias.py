from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/OpenHands/benchmarks",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627191156-142d39dda9",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "README.md",\n      "legacy/the_agent_company/browsing.py",\n      "legacy/agent_bench/README.md",\n      "benchmarks/multiswebench/README.md",\n      "benchmarks/swebenchmultilingual/README.md"\n    ],\n    "benchmarking": [\n      "pyrightconfig.json",\n      "pyproject.toml",\n      "sitecustomize.py",\n      "README.md",\n      "CONTRIBUTING.md"\n    ],\n    "multi_provider": [\n      "README.md",\n      "CONTRIBUTING.md",\n      "AGENTS.md",\n      ".llm_config/example.json",\n      "tests/test_llm_config.py"\n    ],\n    "plugin_surface": [\n      "pyproject.toml",\n      "README.md",\n      "CONTRIBUTING.md",\n      "AGENTS.md",\n      "tests/test_harbor_compat.py"\n    ],\n    "procedural_surface": [\n      "tests/test_swtbench_grading_patches.py"\n    ],\n    "review_pipeline": [\n      "legacy/swe_perf/run_infer.py",\n      "benchmarks/hybridgym_issuelocalize/README.md",\n      "benchmarks/hybridgym_issuelocalize/eval_infer.py"\n    ],\n    "webgl_scene": [\n      "tests/test_programbench.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider",\n    "atmosphere_shader",\n    "procedural_surface",\n    "webgl_scene"\n  ],\n  "source": "https://github.com/OpenHands/benchmarks"\n}')


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
