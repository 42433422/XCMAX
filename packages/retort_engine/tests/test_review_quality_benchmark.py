from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.review_quality_benchmark import build_review_quality_benchmark


def test_review_quality_benchmark_runs_curated_golden_set(tmp_path: Path) -> None:
    result = build_review_quality_benchmark(tmp_path, sample_count=30)

    assert result["status"] == "ready"
    assert result["summary"]["sample_count"] == 30
    assert result["summary"]["curated_expected_conclusion_count"] == 30
    assert result["summary"]["missed_finding_count"] == 0
    assert result["summary"]["false_positive_count"] == 0
    assert result["summary"]["incremental_skip_verified_count"] == 5
    assert validate_contract("review_quality_benchmark_result", result)["valid"] is True
