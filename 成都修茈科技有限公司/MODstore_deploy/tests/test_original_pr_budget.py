"""Original PR repairs retain their own identity through the shared budget gateway."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from modstore_server import customer_ticket_github
from modstore_server import para_github_repair as repair
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server import strategic_workspace_receipts as receipts
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import digest
from tests import test_strategic_portfolio as strategic_tests
from tests.test_strategic_workspace_bridge import (
    REPO,
    SOURCE,
    bootstrap,
    configured,
    database,
    grant,
    model,
    workspace,
)

PR_SOURCE = "d" * 40
TARGET = "c" * 40


@pytest.fixture
def original(workspace, monkeypatch):
    state = workspace
    state.budget_id = repair.budget_request_id(state.request_id)
    state.control = f"/api/service/mac-control/strategic-runs/{state.budget_id}"
    state.original_key = UUID(state.request_id).hex
    request = {
        "source": repair.REPAIR_KIND,
        "repository": REPO,
        "source_sha": PR_SOURCE,
        "github_issue": 123,
        "pull_request": 7,
        "source_run_id": 99,
        "message": "Repair the original PR failure.",
    }
    with state.factory() as db:
        db.add(
            MacControlTask(
                id=state.original_key,
                actor=repair.REPAIR_ACTOR,
                request_key="original-pr-99",
                request_digest=digest(request),
                request_json=json.dumps(request),
                state="queued",
                reason="",
                para_task_id="",
                attempt_id="",
                device_id="",
                lease_until=0,
                snapshot_json="{}",
                created_at=time.time(),
                updated_at=time.time(),
            )
        )
        db.commit()
    state.opportunity["input_data"]["remote_execution"] = {
        "kind": bridge.KIND,
        "repository": REPO,
        "source_sha": SOURCE,
        "provider": "openai",
        "model": "approved-model",
        "original_request_kind": repair.REPAIR_KIND,
        "original_request_id": state.request_id,
        "approval_digest": digest(request),
    }
    state.pr_head, state.fixed_ci, state.revoked = PR_SOURCE, False, False
    state.ci_status = "queued"
    state.submitted, state.lost_ack = [], False

    def github(method, path, body=None):
        if path.endswith("/issues/123"):
            return {
                "state": "open",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "labels": [{"name": "auto-incident"}, {"name": "ai-implement"}],
                "body": "- Self-Heal-Run: `99/1`",
            }
        if path.endswith("/pulls/7"):
            return {
                "state": "open",
                "draft": False,
                "labels": [{"name": "needs-human"}] if state.revoked else [],
                "head": {"sha": state.pr_head, "ref": "fix/original", "repo": {"full_name": REPO}},
                "base": {"ref": "main", "repo": {"full_name": REPO}},
            }
        if path.endswith("/runs/99"):
            return {
                "head_sha": PR_SOURCE,
                "head_branch": "fix/original",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "failure",
                "workflow_id": 55,
                "head_repository": {"full_name": REPO},
            }
        if "/workflows/55/runs?" in path:
            return {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 77,
                        "workflow_id": 55,
                        "run_attempt": 1,
                        "event": "pull_request",
                        "head_sha": TARGET,
                        "head_branch": "fix/original",
                        "status": state.ci_status,
                        "conclusion": "success" if state.fixed_ci else "failure",
                        "repository": {"full_name": REPO},
                        "pull_requests": [],  # GitHub can omit associations after PR identity readback.
                    }
                ],
            }
        if "/git/ref/heads/" in path:
            return {"object": {"sha": TARGET}}
        return state.github(method, path, body)

    state.read_github = github
    monkeypatch.setattr(customer_ticket_github, "github", github)
    monkeypatch.setattr(
        "modstore_server.para_model_admission.platform_model_admission",
        lambda _profile="repair": state.allocation,
    )

    def devices():
        result = state.devices()
        result[0]["capabilities"]["supports_exact_commit"] = True
        return result

    def submit(body):
        state.submitted.append(deepcopy(body))
        assert body["branch"] == PR_SOURCE and body["tool_name"] == "opencode"
        value = {
            "id": "task-fix",
            "status": "running",
            "title": body["title"],
            "description": body["prompt"],
            "repo_url": body["repo_url"],
            "branch": PR_SOURCE,
            "auto_merge": False,
            "subTasks": [
                {
                    "id": "sub-fix",
                    "device_id": "cloud",
                    "tool_name": "opencode",
                    "status": "running",
                    "branch_name": "devfleet/opencode/sub-fix",
                }
            ],
        }
        state.tasks[value["id"]] = value
        if state.lost_ack:
            raise repair.ParaUnavailable("lost_ack")
        return {"id": value["id"]}

    client = lambda **_: SimpleNamespace(
        devices=devices,
        submit=submit,
        tasks=lambda: list(state.tasks.values()),
        task=lambda task_id: deepcopy(state.tasks[task_id]),
        close=lambda: None,
    )
    monkeypatch.setattr(repair, "ParaClient", client)
    monkeypatch.setattr("modstore_server.mac_control_transport.ParaClient", client)
    return state


def attach_original(state):
    state.decision_id = strategic_tests.proposal(
        state.factory,
        rows=[state.opportunity],
        caps=state.caps,
    )
    status = runtime.run_portfolio_cycle(state.decision_id, owner_user_id=7)
    saved = status["tasks"]["a"]
    assert saved["status"] == "waiting", saved
    assert saved["worker_binding"]["receipt_id"] == state.budget_id
    return status


def start_original(state):
    repair.sync(state.factory)
    assert not state.github.writes and not state.submitted
    attach_original(state)
    for _ in range(5):
        repair.sync(state.factory)
    assert len(state.github.writes) == len(state.submitted) == 1
    bootstrap(state)
    task = state.tasks["task-fix"]
    sub = task["subTasks"][0]
    with state.factory() as db:
        row = db.get(MacControlTask, state.original_key)
        attempt = row.attempt_id
    return {
        "phase": "execute",
        "run_id": 42,
        "task_id": task["id"],
        "subtask_id": sub["id"],
        "attempt_id": attempt,
        "device_id": "cloud",
        "title": task["title"],
        "description": task["description"],
        "repo_url": task["repo_url"],
        "base_branch": PR_SOURCE,
        "work_branch": sub["branch_name"],
        "auto_merge": False,
    }


@pytest.mark.parametrize("lost_ack", [False, True])
@pytest.mark.parametrize("final_ci", ["success", "failure"])
def test_original_task_budget_native_usage_publication_and_original_ci_close_once(
    original, monkeypatch, lost_ack, final_ci
):
    state = original
    state.lost_ack = lost_ack
    identity = start_original(state)
    bound = grant(state, identity)
    assert bound["control_task_id"] == state.original_key and "event_id" not in bound
    model(state, monkeypatch)
    raw = state.tasks["task-fix"]
    report = {
        "source": "executor_git_readback",
        "pushed": False,
        "publication": "artifact_pending",
        "base_sha": PR_SOURCE,
        "branch": identity["work_branch"],
        "task_id": identity["task_id"],
        "subtask_id": identity["subtask_id"],
        "attempt_id": identity["attempt_id"],
        "commit_sha": TARGET,
        "archive_sha256": "c" * 64,
        "bundle_sha256": "d" * 64,
    }
    raw["status"] = raw["subTasks"][0]["status"] = "completed"
    raw["subTasks"][0]["logs"] = [{"content": json.dumps(report)}]
    repair.sync(state.factory)
    with state.factory() as db:
        status = repair.run_status(db.get(MacControlTask, state.original_key))
    assert status["publication_candidate"]["commit_sha"] == TARGET
    assert status["strategic_budget"]["request_id"] == state.budget_id
    assert status["strategic_budget"]["original_request_id"] == state.request_id
    state.github.phase("completed")
    state.github.jobs = state.github.jobs[:2]
    repair.sync(state.factory)
    with state.factory() as db:
        assert db.get(MacControlTask, state.original_key).state == "execution_completed"
        published = repair.run_status(db.get(MacControlTask, state.original_key))
        assert published["publication_authorized"]
    state.revoked = True
    with state.factory() as db:
        observed = repair.run_status(db.get(MacControlTask, state.original_key))
        assert not observed["publication_authorized"]
        assert observed["finished"] and observed["conclusion"] == "success"
        assert observed["publication_candidate"] == published["publication_candidate"]
    state.revoked = False
    assert receipts.reconcile_request(state.budget_id)  # Native phase idle, PR not yet repaired.
    assert portfolio.portfolio_status(state.decision_id)["tasks"]["a"]["status"] == "waiting"
    state.pr_head = TARGET
    assert not receipts.reconcile_request(state.budget_id)  # Queued CI remains pending.
    state.ci_status, state.fixed_ci = "completed", final_ci == "success"
    assert receipts.reconcile_request(state.budget_id)
    saved = portfolio.portfolio_status(state.decision_id)["tasks"]["a"]
    assert saved["status"] == ("completed" if final_ci == "success" else "failed")
    receipt = saved["execution_receipt"]["remote_receipt"]
    assert receipt["verification"]["head_sha"] == TARGET
    assert receipt["delivery"]["status"] == "not_verified"
    assert not receipts.reconcile_request(state.budget_id)
    repair.sync(state.factory)
    assert len(state.github.writes) == len(state.submitted) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "0" * 32),
        ("task_id", "foreign-task"),
        ("base_branch", SOURCE),
        ("device_id", "foreign-device"),
        ("phase", "resume"),
    ],
)
def test_original_grant_rejects_other_tasks_or_controller_as_source(original, field, value):
    identity = start_original(original)
    if field == "task_id":
        original.tasks[value] = {**original.tasks["task-fix"], "id": value}
    response = original.client.post(
        original.control + "/task-grant",
        json={**identity, field: value},
        headers=original.bootstrap_headers,
    )
    assert response.status_code == 409, response.text
    assert not portfolio.portfolio_status(original.decision_id)["tasks"]["a"]["calls"]


@pytest.mark.parametrize("change", ["request", "incident", "company"])
def test_original_authority_revocation_blocks_new_model_calls(original, change):
    identity = start_original(original)
    grant(original, identity)
    if change == "request":
        with original.factory() as db:
            row = db.get(MacControlTask, original.original_key)
            request = json.loads(row.request_json)
            request["message"] = "different operation"
            row.request_json = json.dumps(request)
            db.commit()
    elif change == "incident":
        original.revoked = True
    else:
        portfolio.mutate_portfolio(
            original.decision_id, lambda _r, _p, state, _db: state.update(halted=True)
        )
    response = original.client.get(original.control + "/v1/models", headers=original.model_headers)
    assert response.status_code == 409
    assert not portfolio.portfolio_status(original.decision_id)["tasks"]["a"]["calls"]


def test_original_unknown_usage_cannot_publish_or_replay(original, monkeypatch):
    identity = start_original(original)
    bound = grant(original, identity)
    model(original, monkeypatch, usage=False)
    assert not bridge.candidate_metered(original.budget_id, bound)
    replay = original.client.post(
        original.control + "/claim",
        headers=original.management,
        json={
            k: original.bootstrap[k]
            for k in (
                "run_id",
                "run_attempt",
                "repository",
                "source_sha",
                "phase",
                "execution_isolation",
            )
        },
    )
    assert replay.status_code == 409
    repair.sync(original.factory)
    assert len(original.github.writes) == len(original.submitted) == 1


def test_older_unbudgeted_request_does_not_starve_approved_original(original):
    with original.factory() as db:
        current = db.get(MacControlTask, original.original_key)
        db.add(
            MacControlTask(
                id="f" * 32,
                actor=repair.REPAIR_ACTOR,
                request_key="older-unbudgeted-original",
                request_digest=current.request_digest,
                request_json=current.request_json,
                state="queued",
                reason="",
                para_task_id="",
                attempt_id="",
                device_id="",
                lease_until=0,
                snapshot_json="{}",
                created_at=0,
                updated_at=0,
            )
        )
        db.commit()
    identity = start_original(original)
    assert grant(original, identity)["control_task_id"] == original.original_key
    with original.factory() as db:
        old = db.get(MacControlTask, "f" * 32)
        assert old.state == "waiting_device" and not old.attempt_id


def test_worker_recovery_reads_beyond_three_pages_without_filters():
    seen = []

    def github(_method, path):
        assert "event=" not in path and "branch=" not in path
        page = int(path.rsplit("=", 1)[1])
        seen.append(page)
        return {
            "total_count": 301,
            "workflow_runs": [
                {"id": i, "display_title": "original" if i == 301 else "other"}
                for i in range((page - 1) * 100 + 1, min(page * 100, 301) + 1)
            ],
        }

    assert repair._find_run(github, REPO, "original") == 301
    assert seen == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "rows,total",
    [
        ([{"id": 1, "display_title": "same"}, {"id": 2, "display_title": "same"}], 2),
        ([{"id": 1, "display_title": "same"}], 2),
        ([{"id": 1, "display_title": "same"}, {"id": 1, "display_title": "same"}], 2),
    ],
)
def test_worker_recovery_requires_complete_unique_run_inventory(rows, total):
    assert (
        repair._find_run(lambda *_: {"workflow_runs": rows, "total_count": total}, REPO, "same")
        is None
    )


@pytest.mark.parametrize("mutation", ["duplicate", "attempt", "run", "source", "inventory"])
def test_original_publication_requires_one_complete_native_publisher(monkeypatch, mutation):
    row = SimpleNamespace(
        id="1" * 32, state="running", para_task_id="task-fix", attempt_id="a" * 32
    )
    request = {"repository": REPO, "source_sha": PR_SOURCE}
    candidate = {
        "request_id": str(UUID(hex=row.id)),
        "run_id": "42",
        "repository": REPO,
        "base_sha": PR_SOURCE,
        "task_id": row.para_task_id,
        "attempt_id": row.attempt_id,
        "branch": "devfleet/fix",
        "commit_sha": TARGET,
    }
    job = {
        "name": "publish-candidate",
        "conclusion": "success",
        "status": "completed",
        "run_id": 42,
        "run_attempt": 1,
        "head_sha": SOURCE,
    }
    jobs, total = [job], 1
    if mutation == "duplicate":
        jobs.append({**job, "conclusion": "failure"})
        total = 2
    elif mutation == "inventory":
        total = 2
    else:
        job[{"attempt": "run_attempt", "run": "run_id", "source": "head_sha"}[mutation]] = (
            "0" * 40 if mutation == "source" else 2
        )
    transitions = []
    monkeypatch.setattr(
        repair, "transition", lambda _db, _task, state, *a, **kw: transitions.append(state)
    )
    repair._publish_readback(
        None,
        row,
        request,
        {"candidate": candidate},
        {"id": 42, "head_sha": SOURCE, "conclusion": "success"},
        lambda _m, path: (
            {"jobs": jobs, "total_count": total}
            if "/jobs?" in path
            else {"object": {"sha": TARGET}}
        ),
    )
    assert transitions == ["reconciling"]
