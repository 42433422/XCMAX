from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.review_quality_benchmark import build_review_quality_benchmark


def test_review_quality_benchmark_runs_curated_golden_set(tmp_path: Path) -> None:
    result = build_review_quality_benchmark(tmp_path, sample_count=30, negative_sample_count=4)

    assert result["status"] == "ready"
    assert result["summary"]["sample_count"] == 34
    assert result["summary"]["positive_sample_count"] == 30
    assert result["summary"]["negative_sample_count"] == 4
    assert result["summary"]["curated_expected_conclusion_count"] == 34
    assert result["summary"]["missed_finding_count"] == 0
    assert result["summary"]["false_positive_count"] == 0
    assert result["summary"]["negative_blocker_false_positive_count"] == 0
    assert result["summary"]["incremental_skip_verified_count"] == 5
    assert result["summary"]["aggregate_score"] == 100
    assert result["summary"]["baseline_aggregate_score"] < result["summary"]["aggregate_score"]
    assert result["summary"]["post_absorption_score_delta"] > 0
    assert result["summary"]["publishable_comment_count"] >= result["summary"]["sample_count"]
    assert result["baseline_comparison"]["status"] == "improved"
    assert result["baseline_comparison"]["same_pr_set_replayed"] is True
    assert result["summary"]["macro_category_pass_rate"] == 1.0
    assert result["evidence"]["aggregation"] == "lm_eval_style_task_category_macro_average"
    assert result["category_summary"]["secret_detection"]["recall"] == 1.0
    assert result["category_summary"]["incremental_review_detection"]["incremental_skip_verified_count"] == 5
    assert result["category_summary"]["fake_fixture_key_no_blocker"]["false_positive_count"] == 0
    assert all(sample["publishable_comment_count"] >= 1 for sample in result["samples"])
    assert validate_contract("review_quality_benchmark_result", result)["valid"] is True
