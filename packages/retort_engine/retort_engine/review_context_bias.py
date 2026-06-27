from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/.codex/worktrees/retort-live/XCMAX/packages/retort_engine/.retort/cache/github/kamilstanuch/codebase-digest",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627170400-762694f28f",\n  "signal_evidence": {\n    "benchmarking": [\n      "README.md",\n      "prompt_library/architecture_coupling_cohesion_analysis.md",\n      "prompt_library/swot_analysis.md",\n      "prompt_library/blue_ocean_strategy_analysis.md",\n      "prompt_library/performance_scalability_analysis.md"\n    ],\n    "multi_provider": [\n      "README.md",\n      "prompt_library/architecture_layer_identification.md",\n      "prompt_library/business_model_canvas_analysis.md",\n      "prompt_library/kano_model_analysis.md",\n      "prompt_library/architecture_api_conformance_check.md"\n    ],\n    "plugin_surface": [\n      "README.md",\n      "prompt_library/architecture_layer_identification.md",\n      "prompt_library/architecture_api_client_code_generation.md",\n      "codebase_digest/app.py"\n    ],\n    "review_pipeline": [\n      "README.md",\n      "prompt_library/evolution_technical_debt_estimation.md",\n      "prompt_library/quality_code_style_consistency_analysis.md",\n      "prompt_library/learning_socratic_dialogue_code_review.md",\n      "prompt_library/learning_code_review_checklist.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/kamilstanuch/codebase-digest"\n}')


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
