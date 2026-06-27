from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.pr_publish import build_publish_dry_run


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
    assert result["summary"]["permission_required"] == "pull_request:write"
    assert result["comments"][0]["path"] == "app.py"
    assert result["rollback"]["strategy"] == "delete_created_review_comments"
    assert validate_contract("pr_publish_dry_run_result", result)["valid"] is True
