from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/PyCQA/bandit",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627211902-816c3b78e7",\n  "signal_evidence": {\n    "benchmarking": [\n      "tests/unit/formatters/test_sarif.py",\n      "tests/functional/test_functional.py",\n      "bandit/plugins/injection_sql.py",\n      "bandit/plugins/injection_shell.py",\n      "bandit/plugins/django_xss.py"\n    ],\n    "codebase_graph": [\n      ".pre-commit-config.yaml",\n      "tests/unit/core/test_docs_util.py",\n      "tests/unit/core/test_config.py",\n      "tests/unit/core/test_context.py",\n      "tests/functional/test_functional.py"\n    ],\n    "file_grouping": [\n      "CONTRIBUTING.md"\n    ],\n    "multi_provider": [\n      "funding.json",\n      "bandit/plugins/pytorch_load.py",\n      "bandit/plugins/general_bad_file_permissions.py",\n      "bandit/plugins/django_sql_injection.py",\n      "bandit/plugins/huggingface_unsafe_download.py"\n    ],\n    "plugin_surface": [\n      ".pre-commit-config.yaml",\n      "CONTRIBUTING.md",\n      "tests/unit/core/test_docs_util.py",\n      "tests/unit/core/test_issue.py",\n      "tests/unit/core/test_config.py"\n    ],\n    "review_pipeline": [\n      "CONTRIBUTING.md"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "file_grouping",\n    "benchmarking",\n    "codebase_graph",\n    "plugin_surface",\n    "multi_provider"\n  ],\n  "source": "https://github.com/PyCQA/bandit"\n}')


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
