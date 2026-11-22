"""One original PR request uses an explicitly approved company task and native grants."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from modstore_server import customer_ticket_github, mac_control_transport
from modstore_server import para_github_repair as repair
from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_remote_bridge as remote
from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_dispatch_api import router
from modstore_server.mac_control_store import request_cancellation
from modstore_server.models import IncidentEvent, RetortEvolutionRun
from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
from tests import test_strategic_company_resources as company
from tests import test_strategic_portfolio as base
from tests import test_strategic_usage_reconciliation as accounting
from tests.test_para_github_publication import artifact, isolation_artifact, publisher
from tests.test_strategic_responses import _http, _payload

database = company.database
configured = company.configured
upstream_master = accounting.upstream_master
gateway = accounting.gateway
TOKEN = "original-pr-dispatch-token-" * 3
REPO = "owner/repo"
SOURCE, CONTROLLER, CANDIDATE = "a" * 40, "c" * 40, "b" * 40


@pytest.fixture
def work(configured, gateway, monkeypatch):
    import_module("litellm.proxy.spend_tracking.usage_capture")
    monkeypatch.setattr(accounting, "MODEL", "approved-model")
    monkeypatch.setattr(remote, "get_session_factory", lambda: configured)
    for name, value in {
        "DEVFLEET_FORCE_OPENCODE": "1",
        "MODSTORE_PARA_PLATFORM_POOL": "1",
        "MODSTORE_MAC_CONTROL_ENABLED": "1",
        "XCMAX_FACTORY_CAPABILITY_TOKEN": "fixture-only",
        "MODSTORE_PARA_GITHUB_DEVICE_ID": "cloud",
        "MODSTORE_PUBLIC_ORIGIN": "https://xiu-ci.com",
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256": hashlib.sha256(TOKEN.encode()).hexdigest(),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        customer_ticket_github,
        "configuration",
        lambda: {
            "repository": REPO,
            "configured": True,
            "para_configured": True,
        },
    )
    state = SimpleNamespace(
        factory=configured,
        writes=[],
        reads=[],
        submissions=[],
        raw=None,
        phase="execute",
        source_attempt=3,
        pr_sha=SOURCE,
        ci_runs=[],
        incident_labels=["auto-incident", "ai-implement"],
        pr_labels=[],
    )
    state.run = {
        "id": 42,
        "event": "workflow_dispatch",
        "path": f".github/workflows/{repair.WORKFLOW}",
        "head_branch": "main",
        "head_sha": CONTROLLER,
        "run_attempt": 1,
        "repository": {"full_name": REPO},
        "status": "queued",
        "conclusion": None,
    }
    now = datetime.now(UTC)
    state.jobs = [
        {
            "id": 101,
            "run_id": 42,
            "run_attempt": 1,
            "head_sha": CONTROLLER,
            "name": "employee-workspace",
            "status": "in_progress",
            "conclusion": None,
            "started_at": (now - timedelta(seconds=2)).isoformat(),
            "completed_at": now.isoformat(),
        }
    ]

    def github(method, path, body=None):
        if method == "POST":
            state.writes.append(deepcopy(body))
            assert body["inputs"]["request_id"] == state.request_id
            return {"workflow_run_id": 42}
        state.reads.append(path)
        if path.endswith("/commits/main"):
            return {"sha": CONTROLLER}
        if path.endswith("/issues/5"):
            return {
                "state": "open",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "labels": [{"name": label} for label in state.incident_labels],
                "body": f"- Self-Heal-Run: `99/{state.source_attempt}`",
            }
        if path.endswith("/pulls/7"):
            return {
                "state": "open",
                "draft": False,
                "head": {"sha": state.pr_sha, "ref": "fix/old", "repo": {"full_name": REPO}},
                "base": {"ref": "main", "repo": {"full_name": REPO}},
                "labels": [{"name": label} for label in state.pr_labels],
            }
        if path.endswith(("/runs/99", "/runs/99/attempts/3")):
            return {
                "id": 99,
                "event": "pull_request",
                "workflow_id": 77,
                "head_sha": SOURCE,
                "head_branch": "fix/old",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 3 if "/attempts/" in path else state.source_attempt,
                "head_repository": {"full_name": REPO},
            }
        if path.endswith("/runs/42"):
            return deepcopy(state.run)
        if "/runs?" in path:
            runs = state.ci_runs if "/workflows/77/" in path else [state.run]
            return {"workflow_runs": deepcopy(runs), "total_count": len(runs)}
        if path.endswith("/jobs?per_page=100"):
            return {"total_count": len(state.jobs), "jobs": deepcopy(state.jobs)}
        if "/git/ref/heads/" in path:
            return {"object": {"sha": CANDIDATE}}
        pytest.fail(f"unexpected native read {method} {path}")

    monkeypatch.setattr(customer_ticket_github, "github", github)
    state.github = github
    allocation = {
        "status": "admitted",
        "provider": "litellm",
        "model": accounting.MODEL,
        "approved_models": [accounting.MODEL],
    }
    monkeypatch.setattr(
        "modstore_server.para_model_admission.platform_model_admission", lambda: allocation
    )

    class Para:
        def __init__(self, **_kwargs):
            pass

        def devices(self):
            return [
                {
                    "id": "cloud",
                    "status": "online",
                    "lastSeen": datetime.now(UTC).isoformat(),
                    "tools": [{"toolName": "opencode", "status": "idle"}],
                    "capabilities": {
                        "github_actions": True,
                        "github_request_id": state.request_id,
                        "github_run_id": "42",
                        "github_run_attempt": "1",
                        "github_stage": "execute",
                        "supports_exact_commit": True,
                    },
                }
            ]

        def submit(self, payload):
            state.submissions.append(deepcopy(payload))
            state.raw = {
                "id": "para-one",
                "status": "running",
                "title": payload["title"],
                "description": payload["prompt"],
                "repo_url": payload["repo_url"],
                "branch": payload["branch"],
                "auto_merge": False,
                "subTasks": [
                    {
                        "id": "sub-one",
                        "device_id": "cloud",
                        "status": "running",
                        "tool_name": "opencode",
                        "branch_name": "devfleet/original-repair",
                        "logs": [],
                    }
                ],
            }
            if getattr(state, "on_submit", None):
                state.on_submit()
            return {"id": "para-one"}

        def task(self, task_id):
            assert task_id == "para-one"
            return deepcopy(state.raw)

        def tasks(self):
            return [deepcopy(state.raw)] if state.raw else []

        def close(self):
            pass

    monkeypatch.setattr(repair, "ParaClient", Para)
    monkeypatch.setattr(mac_control_transport, "ParaClient", Para)
    app = FastAPI()
    app.include_router(router)

    def db():
        with configured() as session:
            yield session

    app.dependency_overrides[get_db] = db
    state.client = TestClient(app)
    state.auth = {"Authorization": f"Bearer {TOKEN}"}
    payload = {
        "request_key": "original-pr-99-3",
        "message": "Repair the original failure",
        "source_sha": SOURCE,
        "github_issue": 5,
        "pull_request": 7,
        "source_run_id": 99,
        "source_run_attempt": 3,
    }
    created = state.client.post(
        "/api/service/mac-control/github-pr-tasks", json=payload, headers=state.auth
    )
    assert created.status_code == 202, created.text
    state.task_id = created.json()["task"]["id"]
    state.request_id = str(uuid.UUID(hex=state.task_id))
    state.run["display_title"] = f"para-workspace-{state.request_id}"
    state.control = f"/api/service/mac-control/strategic-runs/{state.request_id}"
    state.status_url = f"/api/service/mac-control/github-runs/{state.request_id}"
    with configured() as session:
        task = session.get(MacControlTask, state.task_id)
        state.original_json, state.original_digest = task.request_json, task.request_digest
    yield state
    state.client.close()


def approve(work, *, expected="waiting"):
    tariffs = [
        {
            "provider": "litellm",
            "model": accounting.MODEL,
            "input_cents_per_million": 100,
            "output_cents_per_million": 100,
            "source": "approved-native-price",
        }
    ]
    work.company_id = company.budget(
        work.factory, tokens=600000, compute_seconds=1000, tariffs=tariffs
    )
    spec = {
        "kind": repair.REPAIR_KIND,
        "original_request_id": work.request_id,
        "original_request_sha256": work.original_digest,
        "repository": REPO,
        "source_sha": SOURCE,
        "controller_sha": CONTROLLER,
        "github_issue": 5,
        "pull_request": 7,
        "source_run_id": 99,
        "source_run_attempt": 3,
        "provider": "litellm",
        "model": accounting.MODEL,
    }
    work.decision_id = company.proposal(
        rows=[
            base.opportunity(
                tokens=200000, compute_seconds=300, input_data={"remote_execution": spec}
            )
        ],
        caps=base.limits(tokens=300000, tariffs=tariffs),
    )
    result = runtime.run_portfolio_cycle(work.decision_id, owner_user_id=7)
    assert result["processed"] == 1
    assert result["tasks"]["a"]["status"] == expected, result
    with work.factory() as session:
        task = session.get(MacControlTask, work.task_id)
        assert (task.request_json, task.request_digest) == (
            work.original_json,
            work.original_digest,
        )
        assert session.scalar(select(func.count()).select_from(RetortEvolutionRun)) == 0
        assert session.scalar(select(func.count()).select_from(IncidentEvent)) == 0


def start(work):
    repair.sync(work.factory)
    assert len(work.writes) == 1 and not work.submissions
    work.run["status"] = "in_progress"
    identity = {
        "run_id": 42,
        "run_attempt": 1,
        "phase": "execute",
        "repository": REPO,
        "source_sha": CONTROLLER,
        "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
    }
    response = work.client.post(work.control + "/claim", json=identity, headers=work.auth)
    assert response.status_code == 200, response.text
    work.bootstrap = response.json()["bootstrap_token"]
    repair.sync(work.factory)
    assert len(work.submissions) == 1
    with work.factory() as session:
        task = session.get(MacControlTask, work.task_id)
        work.attempt = task.attempt_id
    work.identity = {
        "phase": "execute",
        "run_id": 42,
        "task_id": "para-one",
        "subtask_id": "sub-one",
        "attempt_id": work.attempt,
        "device_id": "cloud",
        "title": work.raw["title"],
        "description": work.raw["description"],
        "repo_url": work.raw["repo_url"],
        "base_branch": SOURCE,
        "work_branch": "devfleet/original-repair",
        "auto_merge": False,
    }
    response = work.client.post(
        work.control + "/task-grant",
        json=work.identity,
        headers={"Authorization": f"Bearer {work.bootstrap}"},
    )
    assert response.status_code == 200, response.text
    work.grant = response.json()
    assert work.grant["schema"] == repair.SCHEMA and "event_id" not in work.grant


def candidate(work):
    receipt = {
        "source": "executor_git_readback",
        "pushed": False,
        "publication": "artifact_pending",
        "base_sha": SOURCE,
        "branch": "devfleet/original-repair",
        "task_id": "para-one",
        "subtask_id": "sub-one",
        "attempt_id": work.attempt,
        "commit_sha": CANDIDATE,
        "archive_sha256": "d" * 64,
        "bundle_sha256": hashlib.sha256(b"bundle").hexdigest(),
    }
    work.raw["status"] = work.raw["subTasks"][0]["status"] = "completed"
    work.raw["subTasks"][0]["logs"] = [{"content": json.dumps(receipt)}]
    repair.sync(work.factory)
    return work.client.get(work.status_url, headers=work.auth).json()


def publish(work):
    work.run.update(status="completed", conclusion="success")
    work.jobs[0].update(status="completed", conclusion="success")
    work.jobs.append({**work.jobs[0], "id": 102, "name": "publish-candidate"})
    repair.sync(work.factory)
    return work.client.get(work.status_url, headers=work.auth).json()


def original_ci(work, *, status="queued", conclusion=None, run_id=100, attempt=1):
    work.pr_sha = CANDIDATE
    work.ci_runs = [
        {
            "id": run_id,
            "run_attempt": attempt,
            "workflow_id": 77,
            "head_sha": CANDIDATE,
            "head_branch": "fix/old",
            "event": "pull_request",
            "repository": {"full_name": REPO},
            "pull_requests": [{"number": 7}],
            "status": status,
            "conclusion": conclusion,
        }
    ]


def call_model(work, monkeypatch, *, meter="reported"):
    saved = p.portfolio_status(work.decision_id)["tasks"]["a"]
    seen = _http(
        monkeypatch,
        (work.decision_id, saved),
        meter=meter,
        provider="litellm",
        headers={"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"},
    )
    response = work.client.post(
        work.control + "/v1/responses",
        json=_payload(model=accounting.MODEL),
        headers={"Authorization": f"Bearer {work.grant['model_token']}"},
    )
    assert response.status_code == 200, response.text
    return seen


def publisher_proof(work, observed):
    """Feed the real HTTP descriptor/gate into the existing trusted publisher."""
    manifest = observed["publication_candidate"]
    bundle, bundle_digest = artifact(manifest)
    isolated, metadata = isolation_artifact(
        {
            "request_id": work.request_id,
            "run_id": "42",
            "source_sha": SOURCE,
            "controller_sha": CONTROLLER,
            "candidate_sha": CANDIDATE,
        }
    )
    metadata.update(name=f"para-execution-{work.request_id}", workflow_run={"id": 42})
    artifacts = {
        "total_count": 2,
        "artifacts": [
            metadata,
            {
                "id": 456,
                "name": f"para-candidate-{work.request_id}",
                "digest": bundle_digest,
                "size_in_bytes": len(bundle),
                "workflow_run": {"id": 42},
                "expired": False,
            },
        ],
    }
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "42",
        "GITHUB_SHA": CONTROLLER,
        "GITHUB_REPOSITORY": REPO,
        "PARA_GITHUB_REQUEST_ID": work.request_id,
    }
    return publisher.verify_original_publication(
        observed,
        env,
        lambda path: artifacts if "/artifacts?" in path else deepcopy(work.run),
        lambda artifact_id: bundle if artifact_id == 456 else isolated,
        allow_finished=observed["finished"],
    )


def test_unbound_original_request_waits_without_dispatch_or_retort_impersonation(work, monkeypatch):
    monkeypatch.setattr(
        customer_ticket_github,
        "github",
        lambda *_: pytest.fail("no outbound work without approval"),
    )
    repair.sync(work.factory)
    assert not work.writes and not work.submissions
    response = work.client.get(work.status_url, headers=work.auth).json()
    assert response["status"] == "awaiting_approval"
    assert response["strategic_budget"] == response["publication_authorization"] == {}


def test_original_request_budget_grant_measured_call_and_same_candidate_terminal(work, monkeypatch):
    approve(work)
    start(work)
    seen = call_model(work, monkeypatch)
    observed = candidate(work)
    gate = observed["publication_authorization"]
    assert gate["authorized"] is True and gate["usage_complete"] is True, observed
    assert gate["candidate_sha256"] == p.digest(observed["publication_candidate"])
    assert gate["source_sha"] == SOURCE and gate["controller_sha"] == CONTROLLER
    assert gate["source_run_attempt"] == 3
    assert (
        publisher_proof(work, observed).authorization["candidate_sha256"]
        == gate["candidate_sha256"]
    )
    final = publish(work)
    assert final["finished"] and final["publication_authorization"]["authorized"] is True
    assert publisher_proof(work, final).authorization["authorized"] is True
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "FHD"))
    from scripts.dev import para_issue_dispatch, para_pr_repair

    execution = work.client.get(
        f"/api/service/mac-control/tasks/{work.task_id}", headers=work.auth
    ).json()["task"]["execution"]
    branch, head = para_issue_dispatch.branch_from_execution(execution)
    assert (branch, head) == (observed["publication_candidate"]["branch"], CANDIDATE)
    target = para_pr_repair.Target(7, "fix/old", SOURCE, 99, 8, "ci.yml", 3)
    assert para_pr_repair.candidate_belongs_to_task(branch, execution, target)
    task = p.portfolio_status(work.decision_id)["tasks"]["a"]
    assert task["status"] == "waiting" and task["actual_tokens"] == 13
    assert "model_grant" not in task["remote_state"]
    assert all(grant["status"] == "closed" for grant in task["remote_state"]["task_grants"])
    assert company.totals(work.company_id)["slots"] == 0
    work.source_attempt = 4
    original_ci(work)
    repair.sync(work.factory)
    assert p.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "waiting"
    original_ci(work, status="completed", conclusion="success", attempt=2)
    repair.sync(work.factory)
    repair.sync(work.factory)
    task = p.portfolio_status(work.decision_id)["tasks"]["a"]
    assert task["status"] == "completed" and task["actual_tokens"] == 13
    receipt = task["execution_receipt"]["remote_receipt"]
    assert receipt["verification"]["run_id"] == 100
    assert receipt["verification"]["run_attempt"] == 2
    assert receipt["verification"]["head_sha"] == CANDIDATE
    assert receipt["delivery"]["status"] == "not_verified"
    assert f"/repos/{REPO}/actions/runs/99/attempts/3" in work.reads
    assert len(seen["requests"]) == len(work.writes) == len(work.submissions) == 1
    with work.factory() as session:
        original = session.get(MacControlTask, work.task_id)
        assert (original.request_json, original.request_digest) == (
            work.original_json,
            work.original_digest,
        )
    p.stop_portfolio(work.decision_id, owner_user_id=7, actor="admin:7", reason="operator veto")
    refused = work.client.get(work.status_url, headers=work.auth).json()
    assert refused["publication_authorization"]["authorized"] is False
    with pytest.raises(ValueError, match="expired_or_revoked"):
        publisher_proof(work, refused)


def test_unknown_usage_keeps_original_candidate_unpublishable(work, monkeypatch):
    approve(work)
    start(work)
    call_model(work, monkeypatch, meter="absent")
    observed = candidate(work)
    assert observed["publication_candidate"]["commit_sha"] == CANDIDATE
    assert observed["publication_authorization"]["authorized"] is False
    assert observed["publication_authorization"]["usage_complete"] is False
    with pytest.raises(ValueError, match="expired_or_revoked"):
        publisher_proof(work, observed)
    assert company.totals(work.company_id)["held"]["tokens"] > 0
    work.run.update(status="completed", conclusion="success")
    work.jobs[0].update(status="completed", conclusion="success")
    work.jobs.append({**work.jobs[0], "id": 102, "name": "publish-candidate"})
    repair.sync(work.factory)
    record = work.client.get(
        f"/api/service/mac-control/tasks/{work.task_id}", headers=work.auth
    ).json()["task"]
    assert record["terminal"] is False
    assert not record["execution"].get("reports")
    assert company.totals(work.company_id)["held"]["tokens"] > 0
    assert company.totals(work.company_id)["slots"] == 1


def test_source_attempt_change_cannot_acquire_an_original_budget(work):
    work.source_attempt = 4
    approve(work, expected="unknown")
    with work.factory() as session:
        task = session.get(MacControlTask, work.task_id)
        assert "strategic_request" not in json.loads(task.snapshot_json)
    assert not work.writes and not work.submissions


@pytest.mark.parametrize("interrupt", [False, True])
def test_source_change_before_original_dispatch_closes_the_unused_budget(
    work, monkeypatch, interrupt
):
    from modstore_server import strategic_workspace_receipts as receipts

    approve(work)
    work.source_attempt = 4
    if interrupt:

        def unavailable(_request_id):
            raise p.PortfolioError("original accounting read temporarily unavailable")

        with monkeypatch.context() as scoped:
            scoped.setattr(receipts, "reconcile_request", unavailable)
            repair.sync(work.factory)
        with work.factory() as session:
            row = session.get(MacControlTask, work.task_id)
            assert row.state == "cancelled" and row.reason == repair.CANCEL_PENDING
        assert p.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "waiting"
    repair.sync(work.factory)
    assert not work.writes and not work.submissions
    with work.factory() as session:
        row = session.get(MacControlTask, work.task_id)
        assert row.state == "cancelled"
        assert not json.loads(row.snapshot_json).get("runner_intent")
        assert not row.attempt_id and not row.para_task_id
    saved = p.portfolio_status(work.decision_id)["tasks"]["a"]
    assert saved["status"] == "failed"
    assert not saved["calls"] and saved["actual_tokens"] == 0
    charged = company.totals(work.company_id)
    assert charged["slots"] == 0
    assert all(value == 0 for value in charged["held"].values())
    assert not receipts.reconcile_request(work.request_id)


@pytest.mark.parametrize("lost_ack", [False, True])
def test_unknown_runner_submission_cannot_be_settled_as_local_cancellation(
    work, monkeypatch, lost_ack
):
    approve(work)
    revealed = False

    def github(method, path, body=None):
        if method == "POST":
            result = work.github(method, path, body)
            with work.factory() as session:
                request_cancellation(session, session.get(MacControlTask, work.task_id))
            if lost_ack:
                raise HTTPException(502, "native workflow accepted but acknowledgement was lost")
            return result
        if "/runs?" in path and not revealed:
            return {"total_count": 0, "workflow_runs": []}
        return work.github(method, path, body)

    monkeypatch.setattr(customer_ticket_github, "github", github)
    repair.sync(work.factory)
    with work.factory() as session:
        row = session.get(MacControlTask, work.task_id)
        snapshot = json.loads(row.snapshot_json)
        assert snapshot["runner_intent"] is True and not snapshot.get("run_id")
        request_cancellation(session, row)
    repair.sync(work.factory)
    repair.sync(work.factory)
    assert p.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "waiting"
    assert company.totals(work.company_id)["slots"] == 1
    assert len(work.writes) == 1 and not work.submissions
    revealed = True
    work.run.update(status="completed", conclusion="cancelled")
    repair.sync(work.factory)
    assert p.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "waiting"
    assert company.totals(work.company_id)["slots"] == 1
    work.jobs[0].update(status="completed", conclusion="cancelled")
    repair.sync(work.factory)
    assert p.portfolio_status(work.decision_id)["tasks"]["a"]["status"] == "failed"
    assert company.totals(work.company_id)["slots"] == 0
    assert len(work.writes) == 1 and not work.submissions


def test_concurrent_admin_cancellation_wins_before_original_dispatch_intent(work, monkeypatch):
    approve(work)

    def github(method, path, body=None):
        result = work.github(method, path, body)
        if path.endswith("/commits/main"):
            with work.factory() as session:
                request_cancellation(session, session.get(MacControlTask, work.task_id))
        return result

    monkeypatch.setattr(customer_ticket_github, "github", github)
    repair.sync(work.factory)
    repair.sync(work.factory)
    assert not work.writes and not work.submissions
    saved = p.portfolio_status(work.decision_id)["tasks"]["a"]
    assert saved["status"] == "failed" and not saved["calls"]
    assert company.totals(work.company_id)["slots"] == 0


def test_task_grant_waits_for_its_original_submit_ack_without_a_second_attempt(work):
    approve(work)
    pending = []

    def before_ack():
        with work.factory() as session:
            row = session.get(MacControlTask, work.task_id)
            assert row.state == "dispatching" and not row.para_task_id
            attempt = row.attempt_id
        identity = {
            "phase": "execute",
            "run_id": 42,
            "task_id": "para-one",
            "subtask_id": "sub-one",
            "attempt_id": attempt,
            "device_id": "cloud",
            "title": work.raw["title"],
            "description": work.raw["description"],
            "repo_url": work.raw["repo_url"],
            "base_branch": SOURCE,
            "work_branch": "devfleet/original-repair",
            "auto_merge": False,
        }
        response = work.client.post(
            work.control + "/task-grant",
            json=identity,
            headers={"Authorization": f"Bearer {work.bootstrap}"},
        )
        assert (
            response.status_code == 409
            and response.json()["detail"] == "workspace original task receipt is pending"
        )
        assert not remote.read_request(work.request_id)[1].get("task_grants")
        pending.append(attempt)

    work.on_submit = before_ack
    start(work)
    assert pending == [work.attempt]
    assert len(work.submissions) == len(work.writes) == 1


def test_changed_source_attempt_refuses_phase_grant_after_original_dispatch(work):
    approve(work)
    repair.sync(work.factory)
    work.source_attempt = 4
    work.run["status"] = "in_progress"
    response = work.client.post(
        work.control + "/claim",
        json={
            "run_id": 42,
            "run_attempt": 1,
            "phase": "execute",
            "repository": REPO,
            "source_sha": CONTROLLER,
            "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
        },
        headers=work.auth,
    )
    assert response.status_code == 409 and "no longer current" in response.text
    repair.sync(work.factory)
    assert not work.submissions and len(work.writes) == 1
    assert (
        work.client.get(work.status_url, headers=work.auth).json()["status"] == "cancel_requested"
    )


def test_revoked_approval_stops_model_grant_without_upstream_call(work, monkeypatch):
    approve(work)
    start(work)
    saved = p.portfolio_status(work.decision_id)["tasks"]["a"]
    seen = _http(monkeypatch, (work.decision_id, saved), provider="litellm")
    p.stop_portfolio(work.decision_id, owner_user_id=7, actor="admin:7", reason="operator veto")
    response = work.client.post(
        work.control + "/v1/responses",
        json=_payload(model=accounting.MODEL),
        headers={"Authorization": f"Bearer {work.grant['model_token']}"},
    )
    assert response.status_code == 409
    assert not seen["requests"]
