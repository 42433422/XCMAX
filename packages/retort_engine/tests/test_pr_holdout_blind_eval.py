from __future__ import annotations

from pathlib import Path
import json

from retort_engine.contracts import validate_contract
from retort_engine.pr_holdout_blind_eval import build_pr_holdout_blind_eval


def test_holdout_blind_eval_is_ready_with_distinct_unseen_prs(tmp_path: Path) -> None:
    urls = [f"https://github.com/owner{i}/repo{i}/pull/{i}" for i in range(1, 4)]
    result = build_pr_holdout_blind_eval(tmp_path, pr_urls=urls, target_prs=3, reviewer=_reviewer)

    assert result["status"] == "ready"
    assert result["summary"]["reviewed_pr_count"] == 3
    assert result["summary"]["accepted_pr_count"] == 3
    assert result["summary"]["blind_against_prior_reports"] is True
    assert result["summary"]["holdout_label_count"] == 3
    assert validate_contract("pr_holdout_blind_eval_result", result)["valid"] is True


def test_holdout_blind_eval_records_single_pr_failure_without_aborting(tmp_path: Path) -> None:
    urls = [
        "https://github.com/owner1/repo1/pull/1",
        "https://github.com/owner2/repo2/pull/2",
        "https://github.com/owner3/repo3/pull/3",
    ]

    def reviewer(url: str) -> dict[str, object]:
        if url.endswith("/2"):
            raise RuntimeError("network down")
        return _reviewer(url)

    result = build_pr_holdout_blind_eval(tmp_path, pr_urls=urls, target_prs=3, reviewer=reviewer)

    assert result["status"] == "needs_more_evidence"
    assert result["summary"]["reviewed_pr_count"] == 2
    assert result["summary"]["failed_pr_count"] == 1
    assert [case["status"] for case in result["cases"]] == ["reviewed", "failed", "reviewed"]


def test_holdout_blind_eval_detects_prior_long_run_overlap(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    overlap = "https://github.com/owner1/repo1/pull/1"
    (docs / "retort_complex_pr_replay.json").write_text(
        '{"pull_requests":[{"pr_url":"https://github.com/owner1/repo1/pull/1"}]}',
        encoding="utf-8",
    )
    urls = [overlap, "https://github.com/owner2/repo2/pull/2", "https://github.com/owner3/repo3/pull/3"]
    result = build_pr_holdout_blind_eval(tmp_path, pr_urls=urls, target_prs=3, reviewer=_reviewer)

    assert result["status"] == "needs_more_evidence"
    assert result["summary"]["overlap_with_prior_long_run_count"] == 1
    assert result["summary"]["blind_against_prior_reports"] is False


def test_holdout_blind_eval_blocks_when_too_many_prs_are_truncated(tmp_path: Path) -> None:
    urls = [f"https://github.com/owner{i}/repo{i}/pull/{i}" for i in range(1, 5)]

    def reviewer(url: str) -> dict[str, object]:
        payload = _reviewer(url)
        payload["summary"]["truncated"] = True  # type: ignore[index]
        return payload

    result = build_pr_holdout_blind_eval(tmp_path, pr_urls=urls, target_prs=4, reviewer=reviewer)

    assert result["status"] == "needs_more_evidence"
    assert result["summary"]["truncated_pr_count"] == 4
    assert result["summary"]["reviewed_pr_count"] == 4


def test_holdout_blind_eval_writes_output_report(tmp_path: Path) -> None:
    urls = [f"https://github.com/owner{i}/repo{i}/pull/{i}" for i in range(1, 4)]
    output = tmp_path / "docs" / "holdout.json"

    result = build_pr_holdout_blind_eval(tmp_path, pr_urls=urls, target_prs=3, output=output, reviewer=_reviewer)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert persisted["status"] == "ready"
    assert persisted["summary"]["accepted_pr_count"] == 3


def _reviewer(url: str) -> dict[str, object]:
    number = int(url.rsplit("/", 1)[-1])
    suffixes = (".py", ".go", ".ts")
    path = f"src/file{number}{suffixes[(number - 1) % len(suffixes)]}"
    return {
        "status": "reviewed",
        "pr_url": url,
        "summary": {
            "file_count": 1,
            "hunk_count": 1,
            "comment_count": 1,
            "truncated": False,
            "fetched_bytes": 1200,
        },
        "review": {
            "summary": {
                "file_count": 1,
                "hunk_count": 1,
                "comment_count": 1,
                "reviewed_new_change_count": 3,
            },
            "files": [{"path": path}],
            "comments": [{"publishable": True}],
        },
    }
