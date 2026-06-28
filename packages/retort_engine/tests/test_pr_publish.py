from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox


def test_build_publish_dry_run_converts_review_comments(tmp_path: Path) -> None:
    review_file = tmp_path / "review.json"
    review_file.write_text(
        json.dumps(
            {
                "pr_url": "https://github.com/acme/repo/pull/1",
                "diff_url": "https://github.com/acme/repo/pull/1.diff",
                "review": {
                    "comments": [
                        {"file": "app.py", "line": 3, "message": "Fix token handling.", "severity": "high", "strategy": "security"},
                        {"file": "app.py", "line": 5, "message": "Remove debug print.", "severity": "low", "strategy": "noise"},
                        {"file": "app.py", "line": 5, "message": "Remove debug print.", "severity": "low", "strategy": "noise"},
                        {"file": "", "line": 1, "message": "file summary", "publishable": False},
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_publish_dry_run(review_file, max_comments=1)

    assert result["status"] == "dry_run_ready"
    assert result["summary"]["would_post_comment_count"] == 1
    assert result["summary"]["publishable_source_comment_count"] == 3
    assert result["summary"]["skipped_unpublishable_count"] == 1
    assert result["summary"]["idempotent"] is True
    assert result["summary"]["permission_required"] == "pull_request:write"
    assert result["summary"]["calibration_policy_enabled"] is True
    assert result["summary"]["selection_model"] == "rank_score_then_dedupe"
    assert result["comments"][0]["path"] == "app.py"
    assert result["rollback"]["strategy"] == "delete_created_review_comments"
    assert validate_contract("pr_publish_dry_run_result", result)["valid"] is True


def test_build_publish_dry_run_uses_rank_score_before_original_order(tmp_path: Path) -> None:
    review_file = tmp_path / "review.json"
    review_file.write_text(
        json.dumps(
            {
                "pr_url": "https://github.com/acme/repo/pull/2",
                "diff_url": "https://github.com/acme/repo/pull/2.diff",
                "review": {
                    "comments": [
                        {"file": "app.py", "line": 1, "message": "Low priority.", "severity": "low", "rank_score": 10},
                        {"file": "app.py", "line": 2, "message": "High calibrated priority.", "severity": "medium", "rank_score": 900},
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_publish_dry_run(review_file, max_comments=1)

    assert result["comments"][0]["line"] == 2
    assert result["comments"][0]["body"] == "High calibrated priority."


def test_run_publish_sandbox_creates_and_rolls_back_receipts(tmp_path: Path) -> None:
    dry_run_file = tmp_path / "publish.json"
    dry_run_file.write_text(
        json.dumps(
            {
                "pr_url": "https://github.com/acme/repo/pull/1",
                "summary": {"idempotency_key": "key-1"},
                "comments": [{"path": "app.py", "line": 3, "body": "Fix token handling."}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_publish_sandbox(dry_run_file)

    assert result["status"] == "sandbox_rolled_back"
    assert result["summary"]["created_comment_count"] == 1
    assert result["summary"]["rollback_verified"] is True
    assert result["rollback_receipts"][0]["deleted"] is True
    assert validate_contract("pr_publish_sandbox_result", result)["valid"] is True


def test_run_publish_sandbox_degrades_without_write_permission(tmp_path: Path) -> None:
    dry_run_file = tmp_path / "publish.json"
    dry_run_file.write_text(
        json.dumps(
            {
                "pr_url": "https://github.com/acme/repo/pull/1",
                "summary": {"idempotency_key": "key-1"},
                "comments": [{"path": "app.py", "line": 3, "body": "Fix token handling."}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_publish_sandbox(dry_run_file, permissions={"pull_request_write": False})

    assert result["status"] == "sandbox_permission_denied"
    assert result["summary"]["created_comment_count"] == 0
    assert result["summary"]["permission_denied"] is True
    assert result["evidence"]["degraded_without_write"] is True


def test_run_publish_sandbox_records_rollback_failure(tmp_path: Path) -> None:
    dry_run_file = tmp_path / "publish.json"
    dry_run_file.write_text(
        json.dumps(
            {
                "pr_url": "https://github.com/acme/repo/pull/1",
                "summary": {"idempotency_key": "key-1"},
                "comments": [{"path": "app.py", "line": 3, "body": "Fix token handling."}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first = run_publish_sandbox(dry_run_file)
    comment_id = first["created_receipts"][0]["comment_id"]

    result = run_publish_sandbox(dry_run_file, fail_rollback_ids={comment_id})

    assert result["status"] == "sandbox_rollback_failed"
    assert result["summary"]["rollback_verified"] is False
    assert result["rollback_receipts"][0]["rollback_error"] == "simulated_delete_failed"
