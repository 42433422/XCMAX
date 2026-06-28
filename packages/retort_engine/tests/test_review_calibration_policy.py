from __future__ import annotations

import json
from pathlib import Path

from retort_engine.review_calibration_policy import build_review_calibration_policy


def test_review_calibration_policy_enables_weights_from_ready_reports(tmp_path: Path) -> None:
    _write_ready_reports(tmp_path)

    policy = build_review_calibration_policy(tmp_path)

    assert policy["enabled"] is True
    assert policy["weights"]["security"] > 0
    assert policy["weights"]["runtime"] > 0
    assert policy["weights"]["tests"] > 0
    assert policy["summary"]["holdout_ready"] is True
    assert policy["summary"]["adjudication_ready"] is True
    assert policy["summary"]["rollback_ready"] is True
    assert policy["evidence"]["behavior"] == "calibration_reports_directly_adjust_review_rank_score_and_publish_order"


def test_review_calibration_policy_disables_weights_when_holdout_is_not_blind(tmp_path: Path) -> None:
    _write_ready_reports(tmp_path, blind=False)

    policy = build_review_calibration_policy(tmp_path)

    assert policy["enabled"] is False
    assert all(value == 0 for value in policy["weights"].values())
    assert policy["summary"]["holdout_ready"] is False
    assert policy["summary"]["rollback_ready"] is True


def _write_ready_reports(root: Path, *, blind: bool = True) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "retort_pr_holdout_blind_eval.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {
                    "blind_against_prior_reports": blind,
                    "reviewed_pr_count": 24,
                    "distinct_repo_count": 20,
                    "distinct_extension_count": 12,
                },
            }
        ),
        encoding="utf-8",
    )
    (docs / "retort_review_adjudication_calibration.json").write_text(
        json.dumps({"status": "ready", "summary": {"pass_rate": 0.98}}),
        encoding="utf-8",
    )
    (docs / "retort_pr_failure_rollback_replay.json").write_text(
        json.dumps({"status": "ready", "summary": {"all_failures_rolled_back": True, "rollback_verified_count": 3}}),
        encoding="utf-8",
    )
