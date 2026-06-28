from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/packages/retort_engine/.retort/cache/github/hypothesisworks/hypothesis",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260628172341-a5eb9a1b2f",\n  "signal_evidence": {\n    "benchmarking": [\n      "website/content/2016-04-16-the-purpose-of-hypothesis.md",\n      "website/content/2017-09-28-threshold-problem.md",\n      "website/content/2025-11-16-introducing-hypofuzz.md",\n      "website/content/2016-07-23-what-is-hypothesis.md",\n      "website/content/2016-05-26-exploring-voting-with-hypothesis.md"\n    ],\n    "multi_provider": [\n      "pyproject.toml",\n      "website/content/2016-04-19-rule-based-stateful-testing.md",\n      "website/content/2016-04-16-quickcheck-in-every-language.md",\n      "website/content/2016-05-11-generating-the-right-data.md",\n      "website/content/2016-10-01-pytest-integration-sponsorship.md"\n    ],\n    "plugin_surface": [\n      "pyproject.toml",\n      "website/content/2016-04-15-economics-of-software-correctness.md",\n      "website/content/2016-10-01-pytest-integration-sponsorship.md",\n      "website/content/2016-09-23-hypothesis-3.5.0-release.md",\n      "website/content/2025-11-01-claude-code-plugin.md"\n    ],\n    "review_pipeline": [\n      "website/content/2016-04-15-economics-of-software-correctness.md",\n      "website/content/2017-09-14-multi-bug-discovery.md",\n      "website/content/2025-11-01-claude-code-plugin.md",\n      "website/content/pages/testimonials.md",\n      "hypothesis/tests/quality/test_discovery_ability.py"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "benchmarking",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/hypothesisworks/hypothesis"\n}')


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
