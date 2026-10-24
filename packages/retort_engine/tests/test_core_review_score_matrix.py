"""Core review score matrix (compact JSON-backed cases)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from retort_engine.pr_review import (
    _comment_rank_score,
    _core_review_score_summary,
    _rank_reason,
)

_DATA = json.loads(
    (
        Path(__file__).resolve().parent / "data" / "core_review_score_matrix.json"
    ).read_text(encoding="utf-8")
)
_AXIS_KEYS: list[str] = _DATA["axis_keys"]
_AXES: dict[str, list[object]] = _DATA["axes"]


def _decode(idxs: list[int]) -> dict[str, object]:
    return {key: _AXES[key][i] for key, i in zip(_AXIS_KEYS, idxs)}


CORE_SCORE_CASES = [
    pytest.param(_decode(idxs), score, id=f"case_{n:03d}")
    for n, (idxs, score) in enumerate(
        zip(_DATA["index_rows"], _DATA["expected_scores"], strict=True)
    )
]


@pytest.mark.parametrize("comment, expected_score", CORE_SCORE_CASES)
def test_core_comment_rank_score_matches_weight_matrix(
    comment: dict[str, object], expected_score: int
) -> None:
    assert _comment_rank_score(comment) == expected_score
    reason = _rank_reason(comment)
    assert str(comment["severity"]) in reason
    assert str(comment["review_context"]) in reason
    assert str(comment["capability"]) in reason
    assert f"bias={comment['absorbed_context_rank_weight']}" in reason
    assert f"policy={comment['absorbed_policy_rank_weight']}" in reason
    assert f"calibration={comment['calibration_rank_weight']}" in reason
    assert f"feedback={comment['feedback_rank_weight']}" in reason
    assert "semantic=" in reason


def test_cross_language_transfer_weight_changes_core_ordering() -> None:
    base_comment = {
        "severity": "medium",
        "review_context": "runtime",
        "absorbed_context_rank_weight": 10,
        "absorbed_policy_rank_weight": 10,
        "calibration_rank_weight": 10,
        "feedback_rank_weight": 10,
        "employee_actionable": True,
        "publishable": True,
    }
    static_analysis = {**base_comment, "capability": "static_analysis"}
    cross_language = {**base_comment, "capability": "cross_language_transfer"}
    assert (
        _comment_rank_score(cross_language) - _comment_rank_score(static_analysis) == 50
    )


def test_hunk_semantic_review_weight_beats_cross_language_when_confident() -> None:
    base_comment = {
        "severity": "high",
        "review_context": "ci_config",
        "absorbed_context_rank_weight": 20,
        "absorbed_policy_rank_weight": 20,
        "calibration_rank_weight": 20,
        "feedback_rank_weight": 0,
        "employee_actionable": True,
        "publishable": True,
    }
    cross_language = {**base_comment, "capability": "cross_language_transfer"}
    hunk_semantic = {
        **base_comment,
        "capability": "hunk_semantic_review",
        "semantic_confidence": 92,
    }
    assert _comment_rank_score(hunk_semantic) > _comment_rank_score(cross_language)
    assert "semantic=92" in _rank_reason(hunk_semantic)


def test_core_review_score_summary_proves_cross_language_transfer_is_top_ranked() -> (
    None
):
    summary = _core_review_score_summary(
        [
            {"capability": "cross_language_transfer", "rank_score": 612},
            {"capability": "static_analysis", "rank_score": 560},
        ]
    )
    assert (
        summary["model"]
        == "severity_context_transfer_publishability_v5_external_diagnostics"
    )
    assert summary["max_rank_score"] == 612
    assert summary["min_rank_score"] == 560
    assert summary["ranked_comment_count"] == 2
    assert summary["cross_language_ranked_comment_count"] == 1
    assert summary["cross_language_max_rank_score"] == 612
    assert summary["cross_language_top_ranked"] is True
    assert summary["cross_language_core_behavior_active"] is True
    assert summary["hunk_semantic_ranked_comment_count"] == 0
    assert summary["hunk_semantic_top_ranked"] is False
    assert summary["hunk_semantic_core_behavior_active"] is False


def test_core_review_score_summary_flags_missing_cross_language_core_behavior() -> None:
    summary = _core_review_score_summary(
        [{"capability": "static_analysis", "rank_score": 455}]
    )
    assert summary["cross_language_ranked_comment_count"] == 0
    assert summary["cross_language_max_rank_score"] == 0
    assert summary["cross_language_top_ranked"] is False
    assert summary["cross_language_core_behavior_active"] is False
    assert summary["hunk_semantic_core_behavior_active"] is False


def test_core_review_score_summary_proves_hunk_semantics_is_top_ranked() -> None:
    summary = _core_review_score_summary(
        [
            {"capability": "hunk_semantic_review", "rank_score": 740},
            {"capability": "cross_language_transfer", "rank_score": 690},
        ]
    )
    assert summary["hunk_semantic_ranked_comment_count"] == 1
    assert summary["hunk_semantic_max_rank_score"] == 740
    assert summary["hunk_semantic_top_ranked"] is True
    assert summary["hunk_semantic_core_behavior_active"] is True
    assert summary["cross_language_core_behavior_active"] is True
