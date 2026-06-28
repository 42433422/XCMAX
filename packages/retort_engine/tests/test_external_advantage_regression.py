from __future__ import annotations

from retort_engine.external_advantage_matrix import build_external_advantage_matrix
from retort_engine.external_advantage_regression import verify_external_advantage_rows


def test_external_advantage_deltas_are_executable_behavior_regressions(tmp_path):
    matrix = build_external_advantage_matrix(tmp_path)

    regression = verify_external_advantage_rows(matrix["matrix"])

    assert regression["status"] == "ready"
    assert regression["summary"]["regression_case_count"] == matrix["summary"]["case_count"]
    assert regression["summary"]["passed_regression_case_count"] == matrix["summary"]["case_count"]
    assert regression["summary"]["direct_execution_case_count"] == matrix["summary"]["case_count"]
    assert regression["summary"]["all_use_direct_review_execution"] is True
    assert regression["summary"]["all_delta_regressions_verified"] is True
    assert regression["summary"]["all_have_before_after_scores"] is True
    assert regression["summary"]["all_have_positive_delta"] is True
    assert regression["summary"]["all_match_expected_context"] is True
    assert regression["summary"]["all_match_expected_severity"] is True
    assert regression["summary"]["all_have_publishable_output"] is True


def test_external_advantage_matrix_exposes_regression_backing(tmp_path):
    result = build_external_advantage_matrix(tmp_path)

    assert result["summary"]["regression_status"] == "ready"
    assert result["summary"]["all_delta_regressions_verified"] is True
    assert result["summary"]["all_use_direct_review_execution"] is True
    assert result["summary"]["direct_regression_case_count"] == result["summary"]["case_count"]
    assert result["summary"]["passed_regression_case_count"] == result["summary"]["case_count"]
    assert result["evidence"]["regression_verifier"] == "retort_engine.external_advantage_regression.verify_external_advantage_rows"
    assert result["evidence"]["regression_runtime"] == "retort_engine.pr_review.review_diff"
    assert result["evidence"]["regression_model"] == "executable_input_output_diff_replay"
    assert result["evidence"]["regression_test_module"] == "tests/test_external_advantage_regression.py"
