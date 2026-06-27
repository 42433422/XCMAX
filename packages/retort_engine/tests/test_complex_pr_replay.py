from __future__ import annotations

from pathlib import Path
from typing import Any

from retort_engine.complex_pr_replay import build_complex_pr_replay_report
from retort_engine.contracts import validate_contract


def test_complex_pr_replay_summarizes_real_pr_shape(tmp_path: Path) -> None:
    def reviewer(url: str) -> dict[str, Any]:
        number = int(url.rsplit("/", 1)[-1])
        return {
            "status": "reviewed",
            "pr_url": url,
            "summary": {
                "file_count": 3,
                "hunk_count": 6,
                "comment_count": 4,
                "fetched_bytes": 12000 + number,
                "truncated": number == 3,
            },
            "review": {
                "summary": {"reviewed_new_change_count": 40},
                "files": [{"path": f"app/{number}.py"}, {"path": f"web/{number}.ts"}, {"path": f"docs/{number}.md"}],
                "comments": [
                    {"severity": "high"},
                    {"severity": "medium"},
                    {"severity": "low"},
                    {"severity": "info"},
                ],
            },
        }

    result = build_complex_pr_replay_report(tmp_path, pr_urls=["https://github.com/o/r/pull/1", "https://github.com/o/r/pull/2", "https://github.com/o/r/pull/3"], reviewer=reviewer)

    assert result["status"] == "ready"
    assert result["summary"]["reviewed_pr_count"] == 3
    assert result["summary"]["complex_pr_count"] == 3
    assert result["summary"]["total_comment_count"] == 12
    assert result["summary"]["total_reviewed_new_change_count"] == 120
    assert result["summary"]["distinct_extension_count"] == 3
    assert validate_contract("complex_pr_replay_result", result)["valid"] is True
