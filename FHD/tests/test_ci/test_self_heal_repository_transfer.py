"""#3686: self-heal source identity survives a real GitHub repository transfer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "scripts" / "ci"
if str(CI) not in sys.path:
    sys.path.insert(0, str(CI))

import self_heal_freshness as freshness
import self_heal_reconcile as recovery

REPO = "xcagi/XCMAX"
OLD = "42433422/XCMAX"
REPO_ID = 1262665373
RUN_ID = 44715182498
PATH = ".github/workflows/fhd-deploy.yml"
TITLE = "fhd-deploy production apply-latest"
SHA = "a" * 40


def incident(extra: str = "") -> dict:
    return {
        "number": 3378,
        "state": "open",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
        "labels": [{"name": "auto-incident"}, {"name": "ai-implement"}],
        "body": (
            f"- Workflow: `{TITLE}`\n"
            f"- Run ID: `{RUN_ID}`\n"
            "- Branch: `main`\n"
            f"- Head Repository: `{OLD}`\n"
            f"- Self-Heal-Run: `{RUN_ID}/1`\n"
            f"- Self-Heal-Workflow: `291181633@{PATH}`\n"
            + extra
        ),
    }


class GitHub:
    def __init__(self):
        self.calls = []
        self.status = 301
        self.history = {"url": f"https://api.github.com/repositories/{REPO_ID}"}
        self.run_id = RUN_ID
        self.owner_id = REPO_ID
        self.head_id = REPO_ID
        self.responses = {}

    def __call__(self, path: str, params: dict):
        self.calls.append(path)
        if path in self.responses:
            response = self.responses[path]
            if isinstance(response, Exception):
                raise response
            return response
        if path == f"/repos/{REPO}/actions/runs/{RUN_ID}":
            return 200, {
                "id": self.run_id,
                "name": TITLE,
                "workflow_id": 291181633,
                "path": PATH,
                "head_sha": SHA,
                "head_branch": "main",
                "head_repository": {"id": self.head_id, "full_name": REPO},
                "repository": {"id": self.owner_id, "full_name": REPO},
                "run_attempt": 1,
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "failure",
                "created_at": "2026-11-20T10:00:00Z",
                "pull_requests": [],
            }
        if path == f"/repos/{REPO}":
            return 200, {"id": REPO_ID, "full_name": REPO}
        if path == f"/repos/{OLD}":
            return self.status, self.history
        if path == "/repos/other/repo":
            return 404, {"message": "Not Found"}
        if path == f"/repos/{REPO}/issues/3378/comments":
            return 200, []
        raise AssertionError(f"unexpected GitHub API path: {path}")


def test_official_migration_proves_identity_not_production_recovery():
    github = GitHub()
    result = freshness.reconcile_source(incident(), REPO, github)
    assert (result.action, result.reason, result.disposition) == (
        freshness.PROCEED,
        "not_code_ci_whitelisted",
        "unfiltered",
    )
    assert result.head_repo_id == REPO_ID
    assert f"/repos/{OLD}" in github.calls

    unresolved = recovery.reconcile_one(
        incident(),
        repo=REPO,
        get=github,
        write=lambda *args: pytest.fail("cannot close an unverified deployment"),
        dispatch=lambda *args, **kwargs: pytest.fail("cannot create new Para task"),
        dry_run=False,
    )
    assert unresolved["state"] == "unresolved"
    assert unresolved["reason"] == "dispatch_receipt_missing"


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (200, {"id": 42, "full_name": OLD}),
        (200, {"id": REPO_ID, "full_name": "elsewhere/reused"}),
        (301, {"url": "https://api.github.com/repositories/42"}),
        (301, {"url": "https://evil.example/repositories/1262665373"}),
        (301, {"url": "http://api.github.com/repositories/1262665373"}),
        (404, {"message": "Not Found"}),
        (500, {}),
    ],
)
def test_reused_unknown_or_untrusted_alias_blocks(status, payload):
    github = GitHub()
    github.status, github.history = status, payload
    result = freshness.reconcile_source(incident(), REPO, github)
    assert result.action == freshness.BLOCK
    assert result.reason == "incident_source_branch_or_repository_mismatch"


@pytest.mark.parametrize("field", ["run_id", "owner_id", "head_id"])
def test_run_and_repository_ids_must_still_match(field):
    github = GitHub()
    setattr(github, field, 42)
    assert freshness.reconcile_source(incident(), REPO, github).action == freshness.BLOCK


def test_migration_api_failure_is_not_a_proven_transfer():
    github = GitHub()
    github.responses[f"/repos/{OLD}"] = freshness.LookupFailed("403")
    assert freshness.reconcile_source(incident(), REPO, github).action == freshness.BLOCK


@pytest.mark.parametrize(
    ("old_line", "new_line"),
    [
        ("- Branch: `main`", "- Branch: `someone-else`"),
        (
            f"- Self-Heal-Workflow: `291181633@{PATH}`",
            "- Self-Heal-Workflow: `291181633@.github/workflows/other.yml`",
        ),
        (f"- Self-Heal-Run: `{RUN_ID}/1`", f"- Self-Heal-Run: `{RUN_ID}/2`"),
        (f"- Run ID: `{RUN_ID}`", "- Run ID: `999`"),
        (f"- Head Repository: `{OLD}`", "- Head Repository: `other/repo`"),
    ],
)
def test_branch_workflow_attempt_and_source_marker_cannot_be_rewritten(old_line, new_line):
    item = incident()
    item["body"] = item["body"].replace(old_line, new_line)
    assert freshness.reconcile_source(item, REPO, GitHub()).action == freshness.BLOCK


def test_recorded_repository_id_is_binding_even_with_matching_names():
    item = incident("- Head Repository ID: `42`\n")
    decision = freshness.reconcile_source(item, REPO, GitHub())
    assert (decision.action, decision.reason) == (
        freshness.BLOCK,
        "incident_source_repository_id_mismatch",
    )


def test_missing_api_id_or_untrusted_repository_path_blocks_without_url_request():
    github = GitHub()
    github.head_id = 0
    assert freshness.reconcile_source(incident(), REPO, github).action == freshness.BLOCK

    github = GitHub()
    item = incident()
    item["body"] = item["body"].replace(OLD, "someone/../else")
    assert freshness.reconcile_source(item, REPO, github).action == freshness.BLOCK
    assert "/repos/someone/../else" not in github.calls


def test_new_incident_persists_verified_api_id_but_does_not_dedupe_on_it():
    source = freshness.reconcile_source(incident(), REPO, GitHub())
    markers = freshness.source_markers(source)
    assert f"Head Repository ID: `{REPO_ID}`" in markers
    assert f"Self-Heal-Run: `{RUN_ID}/1`" in markers

    github = GitHub()
    github.responses[f"/repos/{REPO}/issues"] = (
        200,
        [
            {
                "state": "open",
                "html_url": f"https://github.com/{REPO}/issues/9",
                "body": f"- Head Repository ID: `{REPO_ID}`\n",
            }
        ],
    )
    assert freshness.find_marked_issue(github, REPO, markers) == ""
