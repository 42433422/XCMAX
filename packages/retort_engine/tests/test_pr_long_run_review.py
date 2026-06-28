from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.pr_long_run_review import build_pr_long_run_review
from retort_engine.service import RetortService


def test_pr_long_run_review_promotes_complex_replay_to_production_run(tmp_path: Path) -> None:
    _write_long_run_inputs(tmp_path)

    result = build_pr_long_run_review(tmp_path, min_prs=10)

    assert result["status"] == "ready"
    assert result["summary"]["reviewed_pr_count"] == 10
    assert result["summary"]["distinct_repo_count"] == 10
    assert result["summary"]["publish_safety_matrix_ready"] is True
    assert validate_contract("pr_long_run_review_result", result)["valid"] is True


def test_service_exposes_pr_long_run_review(tmp_path: Path) -> None:
    _write_long_run_inputs(tmp_path)

    result = RetortService().pr_long_run_review({"project": str(tmp_path), "min_prs": 10})

    assert result["status"] == "ready"


def _write_long_run_inputs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    pull_requests = [
        {
            "pr_url": f"https://github.com/org{i}/repo{i}/pull/{i}",
            "status": "reviewed",
            "comment_count": 2,
            "file_count": 2,
            "hunk_count": 4,
            "reviewed_new_change_count": 15,
            "language_extensions": ["py" if i % 2 else "ts"],
        }
        for i in range(1, 11)
    ]
    (docs / "retort_complex_pr_replay.json").write_text(
        json.dumps({"status": "ready", "summary": {"complex_pr_count": 5}, "pull_requests": pull_requests}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_live_publish_probe.json").write_text(
        json.dumps({"status": "live_rolled_back", "summary": {"live_github_write": True, "rollback_verified": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_low_permission_probe.json").write_text(
        json.dumps({"status": "permission_denied_degraded", "summary": {"permission_denied": True, "degraded_without_write": True}, "evidence": {"real_network": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_readonly_degradation_probe.json").write_text(
        json.dumps({"status": "read_only_degraded", "summary": {"degraded_without_write": True, "degradation_artifact_ready": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_publish_sandbox.json").write_text(
        json.dumps({"status": "sandbox_rolled_back", "summary": {"rollback_verified": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
