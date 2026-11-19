"""REST boundary tests for exact-head admission and durable post-merge recovery."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))
import ai_self_heal_sla as sla

HEAD, MERGE, NEW_MAIN = "d" * 40, "a" * 40, "f" * 40


def client_with_transport(handler) -> sla.GitHubClient:
    client = sla.GitHubClient.__new__(sla.GitHubClient)
    client.repo = "test/repo"
    client.token = "test"
    client.client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"X-GitHub-Api-Version": sla.GITHUB_API_VERSION},
    )
    client.workflow_dispatch_client = client.client
    client.branch_update_client = None
    client.require_independent_workflow_dispatch = True
    return client


def check_run(**changes):
    return {
        "name": "test",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        **changes,
    }


@pytest.mark.parametrize(
    "last_page",
    [
        check_run(conclusion="failure"),
        check_run(status="queued"),
        check_run(head_sha=NEW_MAIN),
    ],
)
def test_all_check_pages_belong_to_completed_current_head(last_page):
    pages = []

    def handle(request):
        assert request.url.params["per_page"] == "100"
        assert request.url.params["filter"] == "latest"
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(
            200,
            json={
                "total_count": 101,
                "check_runs": [check_run()] * 100 if page == 1 else [last_page],
            },
        )

    ok, _ = client_with_transport(handle).get_pr_check_runs(1, HEAD)
    assert not ok
    assert pages == [1, 2]


@pytest.mark.parametrize("failure", ["http", "truncated", "limit"])
def test_incomplete_check_inventory_fails_closed(failure, monkeypatch):
    if failure == "limit":
        monkeypatch.setattr(sla, "API_MAX_PAGES", 1)

    def handle(request):
        if request.url.params["page"] == "2":
            return httpx.Response(503, json={})
        return httpx.Response(
            200,
            json={
                "total_count": 101,
                "check_runs": [check_run()] * (1 if failure == "truncated" else 100),
            },
        )

    ok, reason = client_with_transport(handle).get_pr_check_runs(1, HEAD)
    assert not ok
    assert {
        "http": "api_error_503",
        "truncated": "incomplete_collection",
        "limit": "pagination_limit",
    }[failure] in reason


def test_legacy_status_on_later_page_also_blocks_merge():
    def handle(request):
        if request.url.path.endswith("check-runs"):
            return httpx.Response(200, json={"total_count": 1, "check_runs": [check_run()]})
        page = request.url.params["page"]
        return httpx.Response(
            200,
            json={
                "sha": HEAD,
                "total_count": 101,
                "statuses": (
                    [{"state": "success"}] * 100 if page == "1" else [{"state": "pending"}]
                ),
            },
        )

    assert client_with_transport(handle).get_pr_check_runs(1, HEAD) == (
        False,
        "commit_status_not_green",
    )


def test_review_uses_latest_current_head_across_all_pages():
    def handle(request):
        assert request.url.params["head_sha"] == HEAD
        first = request.url.params["page"] == "1"
        run = {
            "id": 1 if first else 101,
            "name": "AI Review",
            "head_sha": HEAD,
            "event": "pull_request",
            "path": sla.AI_REVIEW_WORKFLOW_PATH,
            "created_at": "2026-11-19T00:00:00Z",
            "status": "completed" if first else "in_progress",
            "conclusion": "success" if first else None,
        }
        return httpx.Response(
            200,
            json={"total_count": 101, "workflow_runs": [run] * 100 if first else [run]},
        )

    ok, reason = client_with_transport(handle).get_workflow_run_conclusion(HEAD, "AI Review")
    assert not ok
    assert "not_completed" in reason


def test_review_response_for_another_head_cannot_pass():
    def handle(request):
        return httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "name": "AI Review",
                        "head_sha": NEW_MAIN,
                        "event": "pull_request",
                        "path": sla.AI_REVIEW_WORKFLOW_PATH,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
        )

    assert not client_with_transport(handle).get_workflow_run_conclusion(HEAD, "AI Review")[0]


@pytest.mark.parametrize(
    "changes",
    [
        {"path": ".github/workflows/imposter.yml"},
        {"event": "workflow_dispatch"},
        {"repository": {"full_name": "someone/else"}},
    ],
)
def test_same_name_workflow_cannot_impersonate_independent_review(changes):
    run = {
        "name": "AI Review",
        "head_sha": HEAD,
        "event": "pull_request",
        "path": sla.AI_REVIEW_WORKFLOW_PATH,
        "repository": {"full_name": "test/repo"},
        "status": "completed",
        "conclusion": "success",
        **changes,
    }
    client = client_with_transport(
        lambda request: httpx.Response(200, json={"workflow_runs": [run]})
    )
    assert not client.get_workflow_run_conclusion(HEAD, "AI Review")[0]


class GitHubState:
    """A stateful HTTP boundary; only GitHub-owned data survives a new client."""

    def __init__(self):
        self.now = time.time()
        self.pr = {
            "number": 1,
            "title": "change",
            "html_url": "https://github.com/test/repo/pull/1",
            "head": {"sha": HEAD, "ref": "feature/change"},
            "base": {"ref": "main"},
            "user": {"login": "octocat"},
            "labels": [],
            "draft": False,
            "created_at": datetime.fromtimestamp(self.now - 3600, UTC).isoformat(),
            "state": "open",
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
        }
        self.comments = []
        self.runs = {workflow: [] for workflow in sla.POST_MERGE_WORKFLOWS}
        self.requests = []
        self.dispatch_modes = {}
        self.crash_after_post = False
        self.discovery_error = False
        self.save_error_after_dispatch = False

    def client(self):
        return client_with_transport(self.handle)

    def merge(self):
        self.pr.update(
            state="closed",
            merged=True,
            merge_commit_sha=MERGE,
            merged_at=datetime.fromtimestamp(self.now, UTC).isoformat(),
        )

    def prepare(self):
        self.client().prepare_delivery(sla.GitHubClient._pr_info(self.pr, "regular"))
        self.merge()

    def state(self):
        return self.client().load_delivery(1)

    def dispatches(self):
        return [
            (path, body)
            for method, path, body in self.requests
            if method == "POST" and path.endswith("/dispatches")
        ]

    def handle(self, request):
        assert request.headers["X-GitHub-Api-Version"] == sla.GITHUB_API_VERSION
        path = request.url.path.removeprefix("/repos/test/repo/")
        body = json.loads(request.content) if request.content else {}
        method = request.method
        self.requests.append((method, path, body))
        if path == "pulls/1" and method == "GET":
            return httpx.Response(200, json=self.pr)
        if path == "pulls/1/merge":
            assert method == "PUT"
            if body.get("sha") != self.pr["head"]["sha"]:
                return httpx.Response(409, json={"message": "Head changed"})
            self.merge()
            return httpx.Response(200, json={"merged": True, "sha": MERGE})
        if path == f"labels/{sla.DELIVERY_LABEL}":
            return httpx.Response(200, json={"name": sla.DELIVERY_LABEL})
        if path == "issues/1/labels":
            self.pr["labels"].extend({"name": label} for label in body["labels"])
            return httpx.Response(200, json=self.pr["labels"])
        if path == f"issues/1/labels/{sla.DELIVERY_LABEL}" and method == "DELETE":
            self.pr["labels"] = [
                label for label in self.pr["labels"] if label["name"] != sla.DELIVERY_LABEL
            ]
            return httpx.Response(200, json=[])
        if path == "issues":
            if request.url.params["labels"] != sla.DELIVERY_LABEL:
                assert request.url.params["state"] == "open"
                return httpx.Response(200, json=[])
            assert request.url.params["state"] == "all"
            pending = any(label["name"] == sla.DELIVERY_LABEL for label in self.pr["labels"])
            return httpx.Response(200, json=[{"number": 1, "pull_request": {}}] if pending else [])
        if path == "issues/1/comments":
            if method == "GET":
                return httpx.Response(200, json=self.comments)
            comment = {
                "id": len(self.comments) + 1,
                "body": body["body"],
                "user": {"login": "github-actions[bot]"},
            }
            self.comments.append(comment)
            return httpx.Response(201, json=comment)
        if path.startswith("issues/comments/"):
            if self.save_error_after_dispatch and self.dispatches():
                return httpx.Response(503, json={"message": "write unavailable"})
            comment = next(
                item for item in self.comments if item["id"] == int(path.rsplit("/", 1)[1])
            )
            comment["body"] = body["body"]
            return httpx.Response(200, json=comment)
        if path.startswith("actions/runs/"):
            run = next(
                (
                    run
                    for runs in self.runs.values()
                    for run in runs
                    if run["id"] == int(path.rsplit("/", 1)[1])
                ),
                None,
            )
            return httpx.Response(200 if run else 404, json=run or {})
        for index, workflow in enumerate(sla.POST_MERGE_WORKFLOWS):
            if path == f"actions/workflows/{workflow}/runs":
                if self.discovery_error:
                    return httpx.Response(503, json={})
                return httpx.Response(
                    200,
                    json={
                        "workflow_runs": self.runs[workflow],
                        "total_count": len(self.runs[workflow]),
                    },
                )
            if path == f"actions/workflows/{workflow}/dispatches":
                assert body == {
                    "ref": "main",
                    "return_run_details": True,
                    "inputs": {"release_sha": MERGE},
                }
                mode = self.dispatch_modes.get(workflow, "200")
                if mode == "403":
                    return httpx.Response(403, json={"message": "Permission denied"})
                if mode == "invisible":
                    return httpx.Response(204)
                if mode == "invisible_200":
                    return httpx.Response(200, json={})
                if mode == "invisible_timeout":
                    raise httpx.ReadTimeout("unknown acceptance", request=request)
                if mode == "invisible_503":
                    return httpx.Response(503, json={"message": "Unknown server result"})
                run = {
                    "id": 100 + sum(map(len, self.runs.values())),
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "head_sha": NEW_MAIN,
                    "path": f".github/workflows/{workflow}",
                    "display_title": f"{sla.POST_MERGE_RUN_TITLES[index]} {MERGE}",
                    "status": "queued",
                    "conclusion": None,
                    "html_url": "https://github.com/test/repo/actions/runs/100",
                }
                self.runs[workflow].append(run)
                if self.crash_after_post:
                    raise KeyboardInterrupt("runner terminated after server accepted dispatch")
                if mode == "timeout":
                    raise httpx.ReadTimeout("response lost", request=request)
                return (
                    httpx.Response(204)
                    if mode == "204"
                    else httpx.Response(200, json={"workflow_run_id": run["id"]})
                )
        raise AssertionError(f"unexpected REST call {method} {path}")


@pytest.fixture
def github(monkeypatch):
    api = GitHubState()
    monkeypatch.setattr(sla.time, "time", lambda: api.now)
    return api


def test_closed_pr_recovers_merge_intent_using_actual_merge_sha(github):
    github.prepare()  # Runner stopped between GitHub's merge and local receipt update.
    assert github.state()["merge_sha"] == ""
    client = github.client()
    assert client.list_pending_deliveries() == [1]
    assert client.reconcile_delivery(1) == "pending"
    state = github.state()
    assert state["merge_sha"] == MERGE
    assert not state["deployment_verified"]
    assert all(receipt["run_id"] for receipt in state["workflows"].values())
    assert len(github.dispatches()) == 2
    assert all(body["inputs"]["release_sha"] != NEW_MAIN for _, body in github.dispatches())


def test_crash_after_post_reconciles_observed_run_before_sending_anything(github):
    github.prepare()
    github.crash_after_post = True
    with pytest.raises(KeyboardInterrupt):
        github.client().reconcile_delivery(1)
    first = github.state()["workflows"][sla.POST_MERGE_WORKFLOWS[0]]
    assert first["status"] == "dispatching" and first["attempts"] == 1
    assert "run_id" not in first
    github.crash_after_post = False
    assert github.client().reconcile_delivery(1) == "pending"
    assert len(github.dispatches()) == 2  # First workflow not dispatched again.


def test_receipt_write_failure_after_post_does_not_lose_durable_intent(github):
    github.prepare()
    github.save_error_after_dispatch = True
    with pytest.raises(httpx.HTTPStatusError):
        github.client().reconcile_delivery(1)
    github.save_error_after_dispatch = False
    assert github.client().reconcile_delivery(1) == "pending"
    assert len(github.dispatches()) == 2


def test_observed_run_disappearing_never_authorizes_redispatch(github):
    github.prepare()
    github.client().reconcile_delivery(1)
    github.client().reconcile_delivery(1)
    assert all(receipt["status"] == "running" for receipt in github.state()["workflows"].values())
    github.runs = {workflow: [] for workflow in sla.POST_MERGE_WORKFLOWS}
    github.now += sla.DELIVERY_VISIBILITY_SECONDS + 1
    assert github.client().reconcile_delivery(1) == "pending"
    assert len(github.dispatches()) == 2
    assert all(
        receipt["status"] == "unavailable" for receipt in github.state()["workflows"].values()
    )


def test_partial_failure_retries_only_missing_workflow_then_tracks_completion(github):
    github.prepare()
    first, second = sla.POST_MERGE_WORKFLOWS
    github.dispatch_modes[second] = "403"
    assert github.client().reconcile_delivery(1) == "dispatch_failed"
    github.now += sla.DELIVERY_VISIBILITY_SECONDS + 1
    github.dispatch_modes[second] = "200"
    assert github.client().reconcile_delivery(1) == "pending"
    assert len(github.dispatches()) == 3
    github.runs[first][0].update(status="completed", conclusion="success")
    github.runs[second][0]["status"] = "in_progress"
    assert github.client().reconcile_delivery(1) == "pending"
    assert len(github.dispatches()) == 3
    github.runs[second][0].update(status="completed", conclusion="success")
    assert github.client().reconcile_delivery(1) == "ci_passed"
    assert github.client().list_pending_deliveries() == []
    assert github.state()["deployment_verified"] is False


@pytest.mark.parametrize("mode", ["204", "timeout"])
def test_unknown_dispatch_result_adopts_exact_run_without_reposting(github, mode):
    github.prepare()
    github.dispatch_modes = dict.fromkeys(sla.POST_MERGE_WORKFLOWS, mode)
    github.client().reconcile_delivery(1)
    github.client().reconcile_delivery(1)
    assert len(github.dispatches()) == 2
    assert all(receipt["status"] == "running" for receipt in github.state()["workflows"].values())


@pytest.mark.parametrize(
    "mode", ["invisible", "invisible_200", "invisible_timeout", "invisible_503"]
)
def test_unknown_dispatch_never_reposts_after_visibility_window(github, mode):
    github.prepare()
    github.dispatch_modes = dict.fromkeys(sla.POST_MERGE_WORKFLOWS, mode)
    github.client().reconcile_delivery(1)
    github.client().reconcile_delivery(1)
    assert len(github.dispatches()) == 2
    for _ in range(sla.DELIVERY_MAX_ATTEMPTS):
        github.now += sla.DELIVERY_VISIBILITY_SECONDS + 1
        result = github.client().reconcile_delivery(1)
        assert result in ("pending", "dispatch_failed")
        assert len(github.dispatches()) == 2
    github.now += sla.DELIVERY_MAX_AGE_SECONDS
    assert github.client().reconcile_delivery(1) == "blocked"
    assert len(github.dispatches()) == 2
    assert {label["name"] for label in github.pr["labels"]} == {sla.NEEDS_HUMAN_LABEL}


def test_only_definitively_rejected_dispatch_has_bounded_retries(github):
    github.prepare()
    github.dispatch_modes = dict.fromkeys(sla.POST_MERGE_WORKFLOWS, "403")
    github.client().reconcile_delivery(1)
    for _ in range(sla.DELIVERY_MAX_ATTEMPTS):
        github.now += sla.DELIVERY_VISIBILITY_SECONDS + 1
        result = github.client().reconcile_delivery(1)
    assert result == "blocked"
    assert len(github.dispatches()) == 2 * sla.DELIVERY_MAX_ATTEMPTS
    assert {label["name"] for label in github.pr["labels"]} == {sla.NEEDS_HUMAN_LABEL}


def test_expired_delivery_does_not_dispatch(github):
    github.prepare()
    github.now += sla.DELIVERY_MAX_AGE_SECONDS + 1
    assert github.client().reconcile_delivery(1) == "blocked"
    assert not github.dispatches()


def test_failed_ci_requires_human_and_does_not_claim_deployment(github):
    github.prepare()
    github.client().reconcile_delivery(1)
    for runs in github.runs.values():
        runs[0].update(status="completed", conclusion="failure")
    assert github.client().reconcile_delivery(1) == "blocked"
    assert len(github.dispatches()) == 2
    assert github.state()["deployment_verified"] is False
    assert "ci_failed:" in github.state()["error"]


def test_main_dry_run_never_mutates_pending_closed_pr(github, monkeypatch, tmp_path):
    github.prepare()
    original_comments = json.dumps(github.comments)
    client = github.client()
    monkeypatch.setattr(sla, "GitHubClient", lambda repo, token: client)
    monkeypatch.setenv("GITHUB_TOKEN", "test")
    monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")
    monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
    monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")
    before = len(github.requests)
    assert sla.main(["--dry-run"]) == 0
    assert all(method == "GET" for method, _, _ in github.requests[before:])
    assert json.dumps(github.comments) == original_comments
    assert not (tmp_path / "stale.jsonl").exists()


def test_missing_dedicated_token_never_falls_back_to_primary_token(github):
    github.prepare()
    client = github.client()
    client.workflow_dispatch_client = None
    assert client.reconcile_delivery(1) == "dispatch_failed"
    assert not github.dispatches()


def test_label_without_receipt_can_resume_before_merge(github):
    github.pr["labels"] = [{"name": sla.DELIVERY_LABEL}]
    assert github.client().reconcile_delivery(1) == "pending"
    assert not github.dispatches()
    github.prepare()
    assert github.client().reconcile_delivery(1) == "pending"
    assert len(github.dispatches()) == 2


def test_closed_unmerged_pr_cleans_up_prepared_delivery(github):
    github.prepare()
    github.pr["merged"] = False
    assert github.client().reconcile_delivery(1) == "not_merged"
    assert not github.dispatches()
    assert not github.client().list_pending_deliveries()


def test_run_discovery_failure_fails_closed_without_new_dispatch(github):
    github.prepare()
    github.discovery_error = True
    with pytest.raises(ValueError, match="api_error_503"):
        github.client().reconcile_delivery(1)
    assert not github.dispatches()


@pytest.mark.parametrize(
    "field,value", [("merge_commit_sha", NEW_MAIN), ("head", {"sha": NEW_MAIN})]
)
def test_changed_pr_identity_blocks_replay(github, field, value):
    github.prepare()
    state = github.state()
    state["merge_sha"] = MERGE
    github.client().save_delivery(state)
    github.pr[field] = value
    assert github.client().reconcile_delivery(1) == "blocked"
    assert not github.dispatches()


def test_run_id_cannot_substitute_a_different_release_sha(github):
    github.prepare()
    github.client().reconcile_delivery(1)
    github.runs[sla.POST_MERGE_WORKFLOWS[0]][0]["display_title"] = "CI/CD " + NEW_MAIN
    assert github.client().reconcile_delivery(1) == "blocked"
    assert github.state()["error"] == "delivery_run_identity_mismatch"
    assert len(github.dispatches()) == 2


def test_user_comment_cannot_supply_a_trusted_delivery_receipt(github):
    github.prepare()
    github.comments[0]["user"]["login"] = "octocat"
    assert github.client().load_delivery(1) is None


def test_merge_endpoint_atomically_rejects_unverified_new_head(github):
    github.pr["head"]["sha"] = NEW_MAIN
    assert github.client().merge_pr(1, expected_head_sha=HEAD) == (
        False,
        "conflict",
        "",
    )
    assert not github.pr["merged"]
    request = next(body for method, path, body in github.requests if path == "pulls/1/merge")
    assert request["sha"] == HEAD


@pytest.mark.parametrize(
    "changes",
    [
        {"draft": True},
        {"labels": [{"name": "hold-merge"}]},
        {"labels": [{"name": "risk:r3"}]},
        {"base": {"ref": "develop"}},
        {"head": {"ref": "feature/change", "sha": NEW_MAIN}},
    ],
)
def test_fresh_snapshot_preserves_vetoes(github, changes):
    original = sla.GitHubClient._pr_info(github.pr, "regular")
    github.pr.update(changes)
    assert not github.client().check_merge_snapshot(original)[0]
    assert not github.dispatches()
