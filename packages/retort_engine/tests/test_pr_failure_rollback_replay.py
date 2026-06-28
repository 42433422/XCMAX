from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.pr_failure_rollback_replay import build_pr_failure_rollback_replay


def test_failure_rollback_replay_reverts_failed_candidate_for_real_prs(tmp_path: Path) -> None:
    urls = [
        "https://github.com/owner1/repo1/pull/1",
        "https://github.com/owner2/repo2/pull/2",
        "https://github.com/owner3/repo3/pull/3",
    ]

    result = build_pr_failure_rollback_replay(tmp_path, pr_urls=urls, min_cases=3, reviewer=_reviewer)

    assert result["status"] == "ready"
    assert result["summary"]["real_pr_reviewed_count"] == 3
    assert result["summary"]["failed_gate_count"] == 3
    assert result["summary"]["rollback_verified_count"] == 3
    assert result["summary"]["all_failures_rolled_back"] is True
    assert result["summary"]["uses_git_revert"] is True
    assert all(case["gate_returncode"] == 17 for case in result["cases"])
    assert all(case["candidate_commit"] != case["revert_commit"] for case in result["cases"])
    assert validate_contract("pr_failure_rollback_replay_result", result)["valid"] is True


def test_failure_rollback_replay_blocks_when_pr_review_fails(tmp_path: Path) -> None:
    urls = [
        "https://github.com/owner1/repo1/pull/1",
        "https://github.com/owner2/repo2/pull/2",
        "https://github.com/owner3/repo3/pull/3",
    ]

    def reviewer(url: str) -> dict[str, object]:
        if url.endswith("/2"):
            raise RuntimeError("fetch failed")
        return _reviewer(url)

    result = build_pr_failure_rollback_replay(tmp_path, pr_urls=urls, min_cases=3, reviewer=reviewer)

    assert result["status"] == "needs_more_evidence"
    assert result["summary"]["real_pr_reviewed_count"] == 2
    assert result["summary"]["rollback_verified_count"] == 3
    assert result["cases"][1]["review_status"] == "failed"
    assert result["cases"][1]["real_pr_reviewed"] is False


def test_failure_rollback_replay_writes_report(tmp_path: Path) -> None:
    urls = [
        "https://github.com/owner1/repo1/pull/1",
        "https://github.com/owner2/repo2/pull/2",
        "https://github.com/owner3/repo3/pull/3",
    ]
    output = tmp_path / "docs" / "rollback.json"

    result = build_pr_failure_rollback_replay(tmp_path, pr_urls=urls, min_cases=3, output=output, reviewer=_reviewer)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert persisted["status"] == "ready"
    assert persisted["summary"]["target_case_count"] == 3
    assert persisted["evidence"]["rollback_engine"] == "git_revert_in_isolated_sandbox"


def _reviewer(url: str) -> dict[str, object]:
    number = int(url.rsplit("/", 1)[-1])
    return {
        "status": "reviewed",
        "pr_url": url,
        "summary": {
            "file_count": number,
            "hunk_count": number + 1,
            "comment_count": number + 2,
            "fetched_bytes": 1000 + number,
        },
        "review": {
            "summary": {
                "reviewed_new_change_count": number + 3,
            },
        },
    }
