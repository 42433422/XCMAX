from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_api import router as admin_router
from modstore_server.mac_control_dispatch_api import SERVICE_ACTOR, _issue_key, router
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


def issue_body(number: int, **overrides) -> dict:
    return body(
        **{
            "request_key": _issue_key("owner/repo", number),
            "github_issue": number,
            "repository": "owner/repo",
            "base_branch": "main",
            "message": (
                f"修复 GitHub issue #{number}（owner/repo）：t\n\n"
                "基线分支：main。只做 issue 要求的最小改动，正文"
            ),
            **overrides,
        }
    )


def test_rejects_missing_or_wrong_token(setup):
    client, _ = setup
    assert client.post("/api/service/mac-control/tasks", json=body()).status_code == 401
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth("x" * 48))
    ).status_code == 401


def test_training_failure_transport_requires_auth_and_redacts_employee_credentials(
    setup, monkeypatch
):
    from modstore_server import capability_trainer

    client, _ = setup
    monkeypatch.setattr(
        capability_trainer,
        "mine",
        lambda *args, **kwargs: [
            {
                "employee_id": "daily-orchestrator",
                "failure_reason": "failed password=private-password",
                "count": 2,
                "samples": [
                    {
                        "task": "invoice token=private-token",
                        "run_id": "private-run",
                        "failure_reason": "failed password=private-password",
                    }
                ],
            }
        ],
    )
    rejected = client.get("/api/service/mac-control/training/failures")
    assert rejected.status_code == 401
    assert "private" not in rejected.text
    response = client.get("/api/service/mac-control/training/failures", headers=auth())
    assert response.status_code == 200
    assert "private-password" not in response.text and "private-token" not in response.text
    cluster = response.json()["clusters"][0]
    assert cluster["employee_id"] == "daily-orchestrator" and cluster["count"] == 2
    assert cluster["samples"][0]["run_id"] == "private-run"
    assert "invoice" in cluster["samples"][0]["task"]


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
        json=issue_body(2234, mode="review", target="windows", tool=tool),
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


@pytest.mark.parametrize("pool,tool", [(False, "codex"), (True, "codex"), (True, "opencode")])
def test_original_pr_waits_for_explicit_budget_even_with_shared_capacity(
    setup, monkeypatch, pool, tool
):
    from modstore_server import customer_ticket_github as bridge
    from modstore_server import para_github_repair as repair
    from modstore_server import para_model_admission as admission

    client, factory = setup
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1" if tool == "opencode" else "0")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1" if pool else "0")
    monkeypatch.setattr(
        bridge,
        "configuration",
        lambda: {
            "repository": "owner/repo",
            "configured": True,
            "para_configured": True,
        },
    )
    monkeypatch.setattr(
        bridge,
        "github",
        lambda *_: pytest.fail("unapproved work cannot leave the service"),
    )
    monkeypatch.setattr(
        repair,
        "ParaClient",
        lambda **_: pytest.fail("unapproved work cannot create a worker"),
    )
    monkeypatch.setattr(
        admission,
        "platform_model_admission",
        lambda: pytest.fail("shared capacity grants no original budget"),
    )
    route = "/api/service/mac-control/github-pr-tasks"
    payload = body(
        source_sha="a" * 40,
        github_issue=5,
        pull_request=7,
        source_run_id=99,
        source_run_attempt=2,
    )
    assert client.post(route, json=payload).status_code == 401
    result = client.post(route, headers=auth(), json=payload)
    assert result.status_code == 202, result.text
    task = result.json()["task"]
    assert task["executor"] == repair.REPAIR_KIND and task["state"] == "awaiting_approval"
    with factory() as db:
        original = db.get(MacControlTask, task["id"])
        frozen = original.request_json, original.request_digest
    repair.sync(factory)
    assert client.post(route, headers=auth(), json=payload).json()["task"]["id"] == task["id"]
    assert (
        client.post(route, headers=auth(), json={**payload, "source_run_attempt": 3}).status_code
        == 409
    )
    request_id = str(uuid.UUID(hex=task["id"]))
    status = client.get(f"/api/service/mac-control/github-runs/{request_id}", headers=auth()).json()
    assert status["status"] == "awaiting_approval" and status["source_run_attempt"] == 2
    assert status["strategic_budget"] == status["publication_authorization"] == {}
    with factory() as db:
        original = db.get(MacControlTask, task["id"])
        assert (original.request_json, original.request_digest) == frozen
    for change in (
        {"source_run_attempt": 0},
        {"source_run_attempt": -1},
        {"strategic_budget": {"approved": True}},
    ):
        assert client.post(route, headers=auth(), json={**payload, **change}).status_code == 422
    del payload["source_run_attempt"]
    assert client.post(route, headers=auth(), json=payload).status_code == 422


def test_legacy_published_original_pr_remains_readback_only(setup, monkeypatch):
    from modstore_server import customer_ticket_github as bridge
    from modstore_server import para_github_repair as repair

    client, factory = setup
    branch, commit = "devfleet/original-legacy", "b" * 40
    with factory() as db:
        row = accept(
            db,
            actor=repair.REPAIR_ACTOR,
            key="original-legacy",
            request={
                "source": repair.REPAIR_KIND,
                "repository": "owner/repo",
                "message": "old repair",
                "github_issue": 5,
                "pull_request": 7,
                "source_run_id": 99,
                "source_sha": "a" * 40,
            },
        )
        task_id, request_id = row.id, str(uuid.UUID(hex=row.id))
        row.state, row.para_task_id, row.attempt_id = "running", "para-old", "a" * 32
        row.snapshot_json = json.dumps(
            {
                "runner_intent": True,
                "run_id": 33,
                "candidate": {
                    "branch": branch,
                    "commit_sha": commit,
                    "request_id": request_id,
                    "run_id": "33",
                    "repository": "owner/repo",
                    "base_sha": "a" * 40,
                    "task_id": "para-old",
                    "attempt_id": "a" * 32,
                },
            }
        )
        db.commit()
    native = {
        "id": 33,
        "display_title": f"para-workspace-{request_id}",
        "event": "workflow_dispatch",
        "path": f".github/workflows/{repair.WORKFLOW}",
        "head_branch": "main",
        "head_sha": "c" * 40,
        "run_attempt": 1,
        "repository": {"full_name": "owner/repo"},
        "status": "completed",
        "conclusion": "success",
    }
    reads = []

    def github(method, path, _body=None):
        assert method == "GET"
        reads.append(path)
        if path.endswith("/runs/33"):
            return native
        if path.endswith("/runs/33/attempts/1/jobs?per_page=100"):
            return {
                "total_count": 1,
                "jobs": [
                    {
                        "id": 102,
                        "run_id": 33,
                        "run_attempt": 1,
                        "head_sha": native["head_sha"],
                        "name": "publish-candidate",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            }
        if path.endswith(f"/git/ref/heads/{branch}"):
            return {"object": {"sha": commit}}
        pytest.fail(f"unexpected legacy observation {path}")

    monkeypatch.setattr(bridge, "github", github)
    monkeypatch.setattr(
        repair,
        "ParaClient",
        lambda **_: pytest.fail("legacy publication cannot dispatch again"),
    )
    repair.sync(factory)
    repair.sync(factory)
    final = client.get(f"/api/service/mac-control/tasks/{task_id}", headers=auth()).json()["task"]
    assert final["state"] == "execution_completed" and final["github_run_id"] == 33
    assert final["execution"]["reports"][0]["report"]["commit_sha"] == commit
    assert len(reads) == 3
    with factory() as db:
        assert "strategic_request" not in json.loads(db.get(MacControlTask, task_id).snapshot_json)


def test_stable_issue_lookup_and_immutable_scope(setup):
    client, factory = setup
    route = "/api/service/mac-control/tasks"
    lookup = "/api/service/mac-control/issues/5/task"
    scope = {"repository": "owner/repo", "base_branch": "main"}
    assert client.get(lookup, params=scope).status_code == 401
    assert client.get(lookup, params=scope, headers=auth()).json()["task"] is None
    first = client.post(route, json=issue_body(5), headers=auth())
    assert first.status_code == 202, first.text
    task_id = first.json()["task"]["id"]
    assert client.get(lookup, params=scope, headers=auth()).json()["task"]["id"] == task_id
    assert client.post(route, json=issue_body(5), headers=auth()).json()["task"]["id"] == task_id
    for change in ({"base_branch": "other"}, {"message": "changed"}, {"tool": "codex"}):
        assert client.post(route, json=issue_body(5, **change), headers=auth()).status_code == 409
    assert (
        client.post(
            route, json=issue_body(5, request_key="gh-issue-5-random"), headers=auth()
        ).status_code
        == 409
    )
    with factory() as db:
        assert db.query(MacControlTask).filter_by(actor=SERVICE_ACTOR).count() == 1


def _legacy_body(run_id: int) -> dict:
    payload = issue_body(5, request_key=f"gh-issue-5-run-{run_id}")
    del payload["repository"], payload["base_branch"]
    return payload


def _seed_legacy(factory, run_id: int, *, state: str = "waiting_device") -> str:
    payload = _legacy_body(run_id)
    with factory() as db:
        task = accept(
            db,
            actor=SERVICE_ACTOR,
            key=payload["request_key"],
            request={
                "message": payload["message"],
                "target": "mac",
                "tool": "cursor",
                "mode": "code",
                "source_sha": "",
                "ticket_id": None,
                "customer_id": None,
                "source": "github_issue_dispatch",
                "github_issue": 5,
            },
        )
        task.state = state
        db.commit()
        return task.id


@pytest.mark.parametrize("state", ["waiting_device", "execution_completed", "failed", "cancelled"])
def test_existing_legacy_task_recovered_even_without_github_receipt(setup, state):
    client, factory = setup
    task_id = _seed_legacy(factory, 100, state=state)
    lookup = "/api/service/mac-control/issues/5/task"
    scope = {"repository": "owner/repo", "base_branch": "main"}
    found = client.get(lookup, params=scope, headers=auth())
    assert found.status_code == 200
    assert found.json()["task"]["id"] == task_id
    assert found.json()["task"]["state"] == state
    replay = client.post("/api/service/mac-control/tasks", json=_legacy_body(101), headers=auth())
    assert replay.status_code == 202, replay.text
    assert replay.json()["task"]["id"] == task_id
    for mismatch in ({"base_branch": "other"}, {"repository": "other/repo"}):
        assert client.get(lookup, params={**scope, **mismatch}, headers=auth()).status_code == 409
    with factory() as db:
        assert db.query(MacControlTask).filter_by(actor=SERVICE_ACTOR).count() == 1


def test_old_callers_are_canonicalized_and_duplicate_legacy_tasks_block(setup):
    client, factory = setup
    route = "/api/service/mac-control/tasks"
    first = client.post(route, json=_legacy_body(1), headers=auth())
    second = client.post(route, json=_legacy_body(2), headers=auth())
    assert first.status_code == second.status_code == 202
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    _seed_legacy(factory, 3)
    lookup = "/api/service/mac-control/issues/5/task"
    scope = {"repository": "owner/repo", "base_branch": "main"}
    assert client.get(lookup, params=scope, headers=auth()).status_code == 409
    assert client.post(route, json=_legacy_body(4), headers=auth()).status_code == 409
    with factory() as db:
        assert db.query(MacControlTask).filter_by(actor=SERVICE_ACTOR).count() == 2
