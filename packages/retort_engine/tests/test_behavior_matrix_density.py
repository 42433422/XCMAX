"""Behavior matrix density tests (compact JSON-backed generators)."""

from __future__ import annotations

import json
from pathlib import Path

from retort_engine.diff_extension_policy import (
    extension_policy_for_path,
    extension_policy_summary,
)
from retort_engine.review_context_bias import (
    context_rank_weight,
    context_rank_weights,
    context_signal_strength,
    file_grouping_enabled,
)
from retort_engine.static_analysis_gate import scan_static_analysis_findings

_DATA = json.loads(
    (
        Path(__file__).resolve().parent / "data" / "behavior_matrix_density.json"
    ).read_text(encoding="utf-8")
)
_EXTENSION_SEEDS = [tuple(row) for row in _DATA["extension_seeds"]]
_EXTENSION_RAW_EXTRA = [tuple(row) for row in _DATA["extension_raw_extra"]]
_STATIC_SEEDS = [tuple(row) for row in _DATA["static_seeds"]]
CONTEXT_WEIGHT_CASES = [tuple(row) for row in _DATA["context_weight_cases"]]


def _build_extension_policy_cases(target: int = 2600) -> list[tuple]:
    cases: list[tuple] = []
    cases.extend(_EXTENSION_RAW_EXTRA)
    i = 0
    while len(cases) < target:
        prefix, ext, family, context, known, risk, kind = _EXTENSION_SEEDS[
            i % len(_EXTENSION_SEEDS)
        ]
        n = i
        if kind == "nested":
            path = prefix.format(n=f"{n:04d}") + f"/case_{n:04d}.{ext}"
        else:
            path = f"{prefix}/case_{n:04d}.{ext}"
        cases.append((path, family, context, known, risk))
        i += 1
    return cases


def _build_static_analysis_cases(target: int = 900) -> list[tuple]:
    cases: list[tuple] = []
    i = 0
    while len(cases) < target:
        prefix, suffix, line, rule, status, hi, med = _STATIC_SEEDS[
            i % len(_STATIC_SEEDS)
        ]
        path = f"{prefix}{i:04d}{suffix}" if suffix else prefix
        cases.append((path, line, rule, status, hi, med))
        i += 1
    return cases


EXTENSION_POLICY_CASES = _build_extension_policy_cases()
STATIC_ANALYSIS_CASES = _build_static_analysis_cases()


def test_extension_policy_matrix_matches_known_contexts() -> None:
    known_count = 0
    for path, family, context, known, risk in EXTENSION_POLICY_CASES:
        policy = extension_policy_for_path(path)
        assert policy["family"] == family
        assert policy["review_context"] == context
        assert policy["known"] is known
        if known:
            known_count += 1
            assert risk in policy["risk_tags"]
            assert policy["source"] == "retort_holdout_extension_policy_v1"
        else:
            assert policy["source"] == "fallback"
    assert known_count > 2000


def test_extension_policy_summary_preserves_language_and_context_breadth() -> None:
    paths = [case[0] for case in EXTENSION_POLICY_CASES]
    summary = extension_policy_summary(paths)
    assert summary["file_count"] == len(paths)
    assert summary["known_extension_count"] > 2000
    assert summary["unknown_extension_count"] > 0
    assert summary["language_family_count"] >= 10
    assert {"runtime", "frontend", "ci_config", "config", "docs"}.issubset(
        set(summary["review_contexts"])
    )
    assert "memory_safety" in summary["risk_tags"]
    assert "operator_contract" in summary["risk_tags"]


def test_static_analysis_matrix_keeps_blocking_and_review_severity_stable() -> None:
    observed_statuses = {"blocked": 0, "review": 0, "clean": 0}
    for (
        path,
        added_line,
        rule_id,
        expected_status,
        high_count,
        medium_count,
    ) in STATIC_ANALYSIS_CASES:
        result = scan_static_analysis_findings([_file_review(path, added_line)])
        assert result["status"] == expected_status
        assert result["summary"]["high_count"] == high_count
        assert result["summary"]["medium_count"] == medium_count
        if rule_id:
            assert result["findings"][0]["rule_id"] == rule_id
            assert result["findings"][0]["file"] == path
        else:
            assert result["findings"] == []
        observed_statuses[expected_status] += 1
    assert observed_statuses["blocked"] > observed_statuses["review"]
    assert observed_statuses["clean"] > 0


def test_context_bias_matrix_keeps_absorbed_review_priorities_visible() -> None:
    weights = context_rank_weights()
    assert file_grouping_enabled() is True
    assert context_signal_strength() >= 100
    for context, minimum in CONTEXT_WEIGHT_CASES:
        assert context_rank_weight(context) >= minimum
        assert weights[context] == context_rank_weight(context)
    assert weights["security"] >= weights["frontend"]
    assert weights["runtime"] >= weights["docs"]


def _file_review(path: str, added_line: str) -> dict[str, object]:
    return {
        "path": path,
        "hunks": [{"changes": [{"type": "add", "line": 7, "text": added_line}]}],
    }
