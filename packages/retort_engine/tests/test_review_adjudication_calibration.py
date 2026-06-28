from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.review_adjudication_calibration import build_review_adjudication_calibration
from retort_engine.service import RetortService


def test_review_adjudication_calibration_runs_no_human_oracle_cases(tmp_path: Path) -> None:
    output = tmp_path / "docs" / "retort_review_adjudication_calibration.json"

    result = build_review_adjudication_calibration(tmp_path, output=output)

    assert result["status"] == "ready"
    assert result["summary"]["no_human_operating_model"] is True
    assert result["summary"]["human_review_required"] is False
    assert result["summary"]["calibration_label_count"] == 50
    assert result["summary"]["human_label_count"] == 50
    assert result["summary"]["label_source_type"] == "retort_oracle_no_human"
    assert result["summary"]["positive_case_count"] >= 30
    assert result["summary"]["negative_case_count"] >= 15
    assert result["summary"]["pass_rate"] >= 0.9
    assert result["summary"]["pre_calibration_pass_rate"] < result["summary"]["post_calibration_pass_rate"]
    assert result["summary"]["calibration_improvement_delta"] > 0
    assert result["summary"]["false_negative_count"] == 0
    assert result["summary"]["false_positive_count"] == 0
    assert result["summary"]["pre_calibration_false_negative_count"] > result["summary"]["false_negative_count"]
    assert result["summary"]["pre_calibration_false_positive_count"] > result["summary"]["false_positive_count"]
    assert result["summary"]["false_negative_reduction"] > 0
    assert result["summary"]["false_positive_reduction"] > 0
    assert result["summary"]["feedback_recalibration_applied"] is True
    assert result["evidence"]["style"] == "curated_no_human_oracle_adjudication_labels"
    assert any(case["pre_calibration"]["passed"] is False and case["post_calibration"]["passed"] is True for case in result["cases"])
    assert {"security", "tests", "ci_config", "runtime"} <= set(result["summary"]["contexts"])
    assert output.is_file()
    assert validate_contract("review_adjudication_calibration_result", result)["valid"] is True


def test_service_exposes_review_adjudication_calibration(tmp_path: Path) -> None:
    result = RetortService().review_adjudication_calibration({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["calibration_label_count"] == 50
    assert result["summary"]["human_label_count"] == 50
    assert result["summary"]["human_review_required"] is False
    assert result["summary"]["feedback_recalibration_applied"] is True
