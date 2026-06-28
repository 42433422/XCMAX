from __future__ import annotations

from retort_engine.external_advantage_adjudicator import adjudicate_external_advantage_rows, blind_third_party_adjudicate_external_advantages
from retort_engine.external_advantage_matrix import build_external_advantage_matrix


def test_external_advantage_adjudicator_recomputes_improvement_without_review_diff(tmp_path):
    matrix = build_external_advantage_matrix(tmp_path)

    adjudication = adjudicate_external_advantage_rows(matrix["matrix"])

    assert adjudication["status"] == "ready"
    assert adjudication["summary"]["adjudicated_case_count"] == matrix["summary"]["case_count"]
    assert adjudication["summary"]["accepted_case_count"] == matrix["summary"]["case_count"]
    assert adjudication["summary"]["minimum_recomputed_delta"] > 0
    assert adjudication["summary"]["severity_context_publishability_all_verified"] is True
    assert "without_calling_review_diff" in adjudication["evidence"]["independence_boundary"]


def test_external_advantage_matrix_exposes_independent_adjudication(tmp_path):
    result = build_external_advantage_matrix(tmp_path)

    assert result["summary"]["independent_adjudication_status"] == "ready"
    assert result["summary"]["independent_all_cases_accepted"] is True
    assert result["summary"]["independent_accepted_case_count"] == result["summary"]["case_count"]
    assert result["summary"]["independent_minimum_recomputed_delta"] > 0
    assert result["evidence"]["independent_adjudicator"] == "retort_engine.external_advantage_adjudicator.adjudicate_external_advantage_rows"


def test_blind_third_party_adjudicator_recomputes_without_score_fields(tmp_path):
    matrix = build_external_advantage_matrix(tmp_path)

    adjudication = blind_third_party_adjudicate_external_advantages(matrix["matrix"])

    assert adjudication["status"] == "ready"
    assert adjudication["summary"]["accepted_case_count"] == matrix["summary"]["case_count"]
    assert adjudication["summary"]["minimum_blind_recomputed_delta"] >= 65
    assert adjudication["summary"]["all_delta_at_least_65"] is True
    assert adjudication["summary"]["score_fields_consumed"] is False
    assert "no_baseline_or_retort_score_fields" in adjudication["evidence"]["independence_boundary"]
