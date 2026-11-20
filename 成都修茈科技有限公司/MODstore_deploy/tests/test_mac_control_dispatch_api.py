from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_api import router as admin_router
from modstore_server.mac_control_dispatch_api import SERVICE_ACTOR, router
from modstore_server.mac_control_store import accept
from modstore_server.models import Base

TOKEN = "t" * 48
ROTATED = "r" * 48


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("MODSTORE_MAC_CONTROL_ENABLED", "1")
    monkeypatch.setenv("XCMAX_FACTORY_CAPABILITY_TOKEN", "fixture-only")
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", digest(TOKEN))

    def database():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    app.dependency_overrides[get_db] = database
    yield TestClient(app), factory
    engine.dispose()


def auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def body(**overrides) -> dict:
    return {"request_key": "gh-issue-2234-1", "message": "fix issue", **overrides}


def test_rejects_missing_or_wrong_token(setup):
    client, _ = setup
    assert client.post("/api/service/mac-control/tasks", json=body()).status_code == 401
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth("x" * 48))
    ).status_code == 401


def test_unconfigured_token_fails_closed(setup, monkeypatch):
    client, _ = setup
    monkeypatch.delenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256")
    response = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    assert response.status_code == 503


@pytest.mark.parametrize("tool", ["cursor", "opencode"])
def test_creates_code_task_only_for_mac_with_service_actor(setup, tool):
    client, factory = setup
    response = client.post(
        "/api/service/mac-control/tasks",
        json=body(github_issue=2234, mode="review", target="windows", tool=tool),
        headers=auth(),
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["id"]
    with factory() as db:
        task = db.get(MacControlTask, task_id)
        request = json.loads(task.request_json)
    assert task.actor == SERVICE_ACTOR
    assert request["mode"] == "code"
    assert request["target"] == "mac"
    assert request["tool"] == tool
    assert request["github_issue"] == 2234
    assert request["ticket_id"] is None and request["customer_id"] is None


def test_idempotent_by_request_key(setup):
    client, _ = setup
    first = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    second = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    conflict = client.post(
        "/api/service/mac-control/tasks", json=body(message="other"), headers=auth()
    )
    assert conflict.status_code == 409


def test_disabled_mac_control_returns_503(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setenv("MODSTORE_MAC_CONTROL_ENABLED", "0")
    response = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    assert response.status_code == 503


def test_token_rotation_accepts_any_configured_digest(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", f"{digest(TOKEN)}, {digest(ROTATED)}")
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth(ROTATED))
    ).status_code == 202
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", digest(ROTATED))
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth(TOKEN))
    ).status_code == 401


def test_cannot_read_tasks_created_by_other_actors(setup):
    client, factory = setup
    with factory() as db:
        admin_task = accept(
            db,
            actor="admin:1",
            key="admin-request-1",
            request={"message": "x", "mode": "code"},
        )
        admin_task_id = admin_task.id
    response = client.get(f"/api/service/mac-control/tasks/{admin_task_id}", headers=auth())
    assert response.status_code == 404


def test_reads_own_task_without_customer_facts(setup):
    client, _ = setup
    created = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    task_id = created.json()["task"]["id"]
    response = client.get(f"/api/service/mac-control/tasks/{task_id}", headers=auth())
    assert response.status_code == 200
    task = response.json()["task"]
    assert task["state"] == "queued" and task["terminal"] is False
    assert "request" not in task and "facts" not in task


def test_service_token_is_not_an_admin_credential(setup):
    client, _ = setup
    # Admin routes resolve the real require_admin dependency, which rejects this token.
    listed = client.get("/api/admin/mac-control/tasks", headers=auth())
    created = client.post("/api/admin/mac-control/tasks", headers=auth(), json=body())
    assert listed.status_code in {401, 403}
    assert created.status_code in {401, 403}


@pytest.mark.parametrize("lost_dispatch_response", [False, True])
@pytest.mark.parametrize("pool,tool", [(False, "codex"), (True, "codex"), (True, "opencode")])
def test_original_pr_uses_hosted_worker_and_reads_back_publication(
    setup,
    monkeypatch,
    lost_dispatch_response,
    pool,
    tool,
):
    from modstore_server import customer_ticket_github as bridge
    from modstore_server import para_github_repair as repair
    from modstore_server import para_model_admission as admission

    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1" if tool == "opencode" else "0")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1" if pool else "0")
    waiting = {"status": "waiting", "reason": "no_verified_headroom"}
    allocated = {"status": "admitted", "model": "coding-route", "approved_models": ["coding-route"]}
    decision = [waiting if pool else None]
    monkeypatch.setattr(admission, "platform_model_admission", lambda: decision[0])

    client, factory = setup
    repo, old, new = "owner/repo", "a" * 40, "b" * 40
    monkeypatch.setattr(
        bridge,
        "configuration",
        lambda: {
            "repository": repo,
            "configured": True,
            "para_configured": True,
        },
    )
    route = "/api/service/mac-control/github-pr-tasks"
    payload = body(source_sha=old, github_issue=5, pull_request=7, source_run_id=99)
    assert client.post(route, json=payload).status_code == 401
    result = client.post(route, headers=auth(), json=payload)
    assert result.status_code == 202, result.text
    task = result.json()["task"]
    assert task["executor"] == repair.REPAIR_KIND
    assert client.post(route, headers=auth(), json=payload).json()["task"]["id"] == task["id"]
    request_id = str(uuid.UUID(hex=task["id"]))
    status_url = f"/api/service/mac-control/github-runs/{request_id}"
    record_url = f"/api/service/mac-control/tasks/{task['id']}"
    name = f"para-workspace-{request_id}"
    branch, device = "devfleet/fix", "cloud"
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_DEVICE_ID", device)
    initial_run = {
        "id": 33,
        "display_title": name,
        "event": "workflow_dispatch",
        "path": f".github/workflows/{repair.WORKFLOW}",
        "head_branch": "main",
        "run_attempt": 1,
        "repository": {"full_name": repo},
        "status": "queued",
    }
    posted = []

    def github(method, path, data=None):
        if method == "POST":
            posted.append(data["inputs"]["request_id"])
            assert path.endswith(f"/{repair.WORKFLOW}/dispatches") and data["ref"] == "main"
            if lost_dispatch_response:
                raise HTTPException(502)
            return {"workflow_run_id": 33}
        if path.endswith("/pulls/7"):
            return {
                "state": "open",
                "draft": False,
                "head": {"sha": old, "ref": "fix/x", "repo": {"full_name": repo}},
                "base": {"ref": "main", "repo": {"full_name": repo}},
            }
        if path.endswith("/issues/5"):
            return {
                "state": "open",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "labels": [{"name": label} for label in ("ai-implement", "auto-incident")],
                "body": "- Self-Heal-Run: `99/1`",
            }
        if path.endswith("/runs/99"):
            return {
                "head_sha": old,
                "head_branch": "fix/x",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "failure",
                "head_repository": {"full_name": repo},
            }
        if path.endswith("/runs/33"):
            return initial_run
        if "/runs?" in path:
            return {"workflow_runs": [initial_run]}
        if path.endswith("/runs/33/jobs"):
            return {"jobs": [{"name": "publish-candidate", "conclusion": "success"}]}
        if path.endswith(f"/git/ref/heads/{branch}"):
            return {"object": {"sha": new}}
        pytest.fail(f"unexpected GitHub call {method} {path}")

    class CloudClient:
        def __init__(self, *, github_worker):
            assert github_worker

        def devices(self):
            return [
                {
                    "id": device,
                    "status": "online",
                    "lastSeen": datetime.now(UTC).isoformat(),
                    "tools": [{"toolName": tool, "status": "idle"}],
                    "capabilities": {
                        "github_actions": True,
                        "github_request_id": request_id,
                        "github_run_id": 33,
                        "github_run_attempt": 1,
                        "github_stage": "execute",
                        "supports_exact_commit": True,
                    },
                }
            ]

        def submit(self, data):
            assert data["branch"] == old and data["auto_merge"] is False
            assert data["tool_name"] == tool
            submitted.append(data["title"])
            return {"id": "para1"}

        def task(self, task_id):
            assert task_id == "para1"
            title = submitted[0]
            report = {
                "source": "executor_git_readback",
                "pushed": False,
                "publication": "artifact_pending",
                "base_sha": old,
                "branch": branch,
                "task_id": task_id,
                "subtask_id": "sub1",
                "attempt_id": title.split(":")[2].split("]")[0],
                "commit_sha": new,
                "archive_sha256": "c" * 64,
                "bundle_sha256": "d" * 64,
            }
            return {
                "id": task_id,
                "status": "completed",
                "title": title,
                "repo_url": f"https://github.com/{repo}.git",
                "subTasks": [
                    {
                        "id": "sub1",
                        "device_id": device,
                        "branch_name": branch,
                        "status": "completed",
                        "logs": [{"content": json.dumps(report)}],
                    },
                ],
            }

        def close(self):
            pass

    submitted = []
    monkeypatch.setattr(bridge, "github", github)
    monkeypatch.setattr(repair, "ParaClient", CloudClient)
    if pool:
        repair.sync(factory)
        assert posted == [] and submitted == []
        assert client.get(status_url, headers=auth()).json()["model_allocation"] == waiting
        decision[0] = allocated
    repair.sync(factory)
    if pool:
        assert client.get(status_url, headers=auth()).json()["model_allocation"] == allocated
    monkeypatch.setattr(
        admission,
        "platform_model_admission",
        lambda: pytest.fail("an accepted workflow must retain its original allocation"),
    )
    initial_run["status"] = "in_progress"
    repair.sync(factory)
    # Changing the policy after acceptance cannot replace the original attempt.
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "0" if tool == "opencode" else "1")
    repair.sync(factory)
    status = client.get(status_url, headers=auth()).json()
    assert status["run_id"] == 33 and status["source_sha"] == old
    assert not status["finished"] and status["publication_candidate"]["commit_sha"] == new
    initial_run.update(status="completed", conclusion="success")
    repair.sync(factory)
    repair.sync(factory)
    final = client.get(record_url, headers=auth()).json()["task"]
    assert (final["state"], final["github_run_id"], final["para_task_id"]) == (
        "execution_completed",
        33,
        "para1",
    )
    assert final["execution"]["reports"][0]["report"]["commit_sha"] == new
    assert posted == [request_id] and len(submitted) == 1
