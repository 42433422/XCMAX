from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from modstore_server.autonomy_posthoc_github import (
    verify_github_self_maintenance_merge,
    verify_github_self_maintenance_veto,
)

UTC = timezone.utc
ALLOWED_AT = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
MERGE_SHA = "6" * 40
HEAD_SHA = "7" * 40
BRANCH = "devfleet/cursor/sub-1-2f18e3"
TASK_ID = "584a11b2-9ff2-4c26-b33c-b10a162066df"
ALLOWED_FILE = (
    "成都修茈科技有限公司/MODstore_deploy/"
    "modstore_server/self_maintenance_remediation_lineage.py"
)
OUTSIDE_LEGACY_SCOPE_FILE = (
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/autonomy_scheduler.py"
)


def _responses():
    pull = {
        "base": {"ref": "main"},
        "changed_files": 1,
        "head": {"ref": BRANCH, "sha": HEAD_SHA},
        "merge_commit_sha": MERGE_SHA,
        "merged": True,
        "merged_by": {"login": "github-actions[bot]"},
        "merged_at": "2026-07-28T11:23:52Z",
        "number": 799,
        "state": "closed",
        "body": (
            "## Para 自动派工产物\n\n"
            f"**任务 ID**: {TASK_ID}\n"
            f"**工作分支**: `{BRANCH}`\n"
            "**目标分支**: `main`\n\n"
            "本 PR 由 merge-worker 自动创建，源任务由 Trae CLI 执行。\n"
            "初始状态 `hold-merge`；AI review APPROVE 后添加 `risk:r0`，"
            "由 `github-actions[bot]` 合并。"
        ),
        "labels": [{"name": "risk:r0"}],
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
                    "app": {"slug": "github-actions"},
                    "conclusion": "success",
                    "name": "review",
                    "status": "completed",
                },
                {
                    "app": {"slug": "github-actions"},
                    "conclusion": "success",
                    "name": "security-scan",
                    "status": "completed",
                },
                {
                    "app": {"slug": "github-actions"},
                    "conclusion": "success",
                    "name": "release-verify",
                    "status": "completed",
                },
            ],
            "total_count": 3,
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


def _verify(responses, *, expected_merge_sha="", expected_task_id=""):
    return verify_github_self_maintenance_merge(
        branch=BRANCH,
        base_branch="main",
        allowed_at=ALLOWED_AT,
        expected_merge_sha=expected_merge_sha,
        expected_task_id=expected_task_id,
        fetch_json=_fetcher(responses),
    )


def test_github_merge_requires_unique_pr_scope_checks_and_main_ancestry():
    result = _verify(_responses(), expected_merge_sha=MERGE_SHA)

    assert result["ok"] is True
    assert result["verdict"] == "no_prohibited_miss"
    assert result["evidence_ref"].startswith(
        f"github-pr:799:merged:{MERGE_SHA[:12]}+checks:3+scope:"
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


def test_generated_para_contract_verifies_merge_outside_legacy_scope():
    responses = _responses()
    responses["files"][0]["filename"] = OUTSIDE_LEGACY_SCOPE_FILE

    result = _verify(responses, expected_task_id=TASK_ID)

    assert result["ok"] is True
    assert result["reason"] == "github_generated_para_merge_checks_and_ancestry_verified"
    assert "+para-contract:" in result["evidence_ref"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda data: data["detail"].update({"labels": [{"name": "hold-merge"}]}),
            "github_para_merge_labels_invalid",
        ),
        (
            lambda data: data["detail"].update({"merged_by": {"login": "42433422"}}),
            "github_para_merge_actor_invalid",
        ),
        (
            lambda data: data["checks"]["check_runs"][-1].update({"name": "optional-check"}),
            "github_para_required_checks_missing",
        ),
    ],
)
def test_generated_para_contract_missing_guard_stays_unknown(mutate, reason):
    responses = _responses()
    responses["files"][0]["filename"] = OUTSIDE_LEGACY_SCOPE_FILE
    mutate(responses)

    result = _verify(responses, expected_task_id=TASK_ID)

    assert result["ok"] is False
    assert result["reason"] == reason


def test_generated_para_contract_never_bypasses_absolute_forbidden_scope():
    responses = _responses()
    responses["files"][0]["filename"] = "runtime/service-token.txt"

    result = _verify(responses, expected_task_id=TASK_ID)

    assert result == {"ok": False, "reason": "github_pr_absolute_forbidden_scope"}


def test_github_veto_requires_exact_unmerged_pull_and_hold_label():
    responses = _responses()
    responses["pulls"][0].update({"merged_at": None, "state": "open"})
    responses["detail"].update(
        {
            "labels": [{"name": "risk:r0"}, {"name": "hold-merge"}],
            "merged": False,
            "merged_at": None,
            "state": "open",
        }
    )

    result = verify_github_self_maintenance_veto(
        branch=BRANCH,
        base_branch="main",
        fetch_json=_fetcher(responses),
    )

    assert result == {
        "ok": True,
        "evidence_ref": "github-pr:799:unmerged:veto:hold-merge",
        "reason": "github_unmerged_pull_explicitly_vetoed",
    }


@pytest.mark.parametrize(
    ("detail_update", "reason"),
    [
        ({"labels": [{"name": "risk:r0"}]}, "github_explicit_veto_missing"),
        (
            {
                "labels": [{"name": "hold-merge"}],
                "merged": True,
                "merged_at": "2026-07-28T11:23:52Z",
            },
            "github_unmerged_pull_contradiction",
        ),
    ],
)
def test_github_veto_missing_or_contradictory_evidence_stays_unknown(
    detail_update,
    reason,
):
    responses = _responses()
    responses["pulls"][0].update({"merged_at": None, "state": "open"})
    responses["detail"].update(
        {
            "labels": [{"name": "hold-merge"}],
            "merged": False,
            "merged_at": None,
            "state": "open",
            **detail_update,
        }
    )

    result = verify_github_self_maintenance_veto(
        branch=BRANCH,
        base_branch="main",
        fetch_json=_fetcher(responses),
    )

    assert result == {"ok": False, "reason": reason}
