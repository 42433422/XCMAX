from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from modstore_server.autonomy_posthoc_github import (
    verify_github_self_maintenance_merge,
)

UTC = timezone.utc
ALLOWED_AT = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
MERGE_SHA = "6" * 40
HEAD_SHA = "7" * 40
BRANCH = "devfleet/cursor/sub-1-2f18e3"
ALLOWED_FILE = (
    "成都修茈科技有限公司/MODstore_deploy/"
    "modstore_server/self_maintenance_remediation_lineage.py"
)


def _responses():
    pull = {
        "base": {"ref": "main"},
        "changed_files": 1,
        "head": {"ref": BRANCH, "sha": HEAD_SHA},
        "merge_commit_sha": MERGE_SHA,
        "merged": True,
        "merged_at": "2026-07-28T11:23:52Z",
        "number": 799,
        "state": "closed",
    }
    return {
        "detail": deepcopy(pull),
        "pulls": [pull],
        "files": [
            {
                "additions": 4,
                "deletions": 1,
                "filename": ALLOWED_FILE,
                "patch": "@@ -1 +1 @@",
            }
        ],
        "checks": {
            "check_runs": [
                {
                    "conclusion": "success",
                    "status": "completed",
                }
            ],
            "total_count": 1,
        },
        "comparison": {
            "merge_base_commit": {"sha": MERGE_SHA},
            "status": "ahead",
        },
    }


def _fetcher(responses):
    def _fetch(path, params=None):
        if path.endswith("/pulls"):
            assert params == {
                "head": f"42433422:{BRANCH}",
                "per_page": "20",
                "state": "all",
            }
            return responses["pulls"]
        if path.endswith("/pulls/799"):
            return responses["detail"]
        if path.endswith("/files"):
            return responses["files"]
        if path.endswith("/check-runs"):
            return responses["checks"]
        if "/compare/" in path:
            return responses["comparison"]
        raise AssertionError(f"unexpected GitHub path: {path}")

    return _fetch


def _verify(responses, *, expected_merge_sha=""):
    return verify_github_self_maintenance_merge(
        branch=BRANCH,
        base_branch="main",
        allowed_at=ALLOWED_AT,
        expected_merge_sha=expected_merge_sha,
        fetch_json=_fetcher(responses),
    )


def test_github_merge_requires_unique_pr_scope_checks_and_main_ancestry():
    result = _verify(_responses(), expected_merge_sha=MERGE_SHA)

    assert result["ok"] is True
    assert result["verdict"] == "no_prohibited_miss"
    assert result["evidence_ref"].startswith(
        f"github-pr:799:merged:{MERGE_SHA[:12]}+checks:1+scope:"
    )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda data: data["pulls"].append(deepcopy(data["pulls"][0])),
            "github_merged_pull_not_unique",
        ),
        (
            lambda data: data["files"][0].update({"filename": ".github/workflows/deploy.yml"}),
            "github_pr_forbidden_scope",
        ),
        (
            lambda data: data["checks"]["check_runs"][0].update({"conclusion": "failure"}),
            "github_check_run_not_successful",
        ),
        (
            lambda data: data["comparison"]["merge_base_commit"].update({"sha": "8" * 40}),
            "github_merge_not_in_base_ancestry",
        ),
    ],
)
def test_github_merge_incomplete_or_contradictory_evidence_stays_unknown(
    mutate,
    reason,
):
    responses = _responses()
    mutate(responses)

    result = _verify(responses)

    assert result == {"ok": False, "reason": reason}


def test_github_merge_rejects_para_sha_contradiction_before_secondary_calls():
    result = _verify(_responses(), expected_merge_sha="9" * 40)

    assert result == {"ok": False, "reason": "github_merge_sha_contradiction"}
