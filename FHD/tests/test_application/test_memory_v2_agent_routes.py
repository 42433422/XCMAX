from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client() -> TestClient:
    from app.fastapi_routes.domains.misc.misc_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_memory_client(monkeypatch, trusted_actor):
    actor = trusted_actor(
        user_id=7, role="admin", permissions=["memory_v2.read", "memory_v2.write"]
    )
    original = _client

    def client():
        result = original()
        result.headers.update(actor.headers)
        return result

    monkeypatch.setattr(__import__(__name__, fromlist=["_client"]), "_client", client)
    return actor


def _patch_agent_repo(repo: InMemoryAgentRunRepository):
    return patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    )


def _configure_runtime(monkeypatch, tmp_path) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod

    memory_dir = tmp_path / "memory"
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "JSON_MEMORY_PATH", str(memory_dir / "memory_store.json"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    memory_mod.reset_user_memory_service()


def _concurrent_memory_candidate_write(user_id, key, value, barrier) -> None:
    from app.application.memory_v2_facade import get_user_memory_service

    barrier.wait(timeout=15)
    get_user_memory_service().propose_memory_candidate(
        user_id, "preference", key, value, source="user_explicit"
    )


@pytest.mark.parametrize("account_tier", ["normal", "personal"])
def test_memory_v2_lifecycle_routes_require_shared_approval(
    tmp_path, monkeypatch, authenticated_memory_client, account_tier
):
    import app.domain.shared_services.user_memory_service as memory_mod
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.db.models.user import User

    actor = authenticated_memory_client
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).account_tier = account_tier
    owner = scoped_personal_memory_id(actor.context)
    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)
    try:
        service = memory_mod.get_user_memory_service()
        candidate = service.propose_memory_candidate(
            owner, "preference", "customer", "七彩乐园", source="user_explicit"
        )["candidate"]
        memory_id = candidate["memory_id"]
        before = Path(memory_mod.JSON_MEMORY_PATH).read_bytes()
        cases = [
            (
                "POST",
                "/memory/v2/candidates",
                {
                    "user_id": "7",
                    "memory_type": "preference",
                    "key": "customer",
                    "value": "彩虹乐园",
                    "source": "user_explicit",
                },
                "propose_candidate",
            ),
            ("POST", f"/memory/v2/{memory_id}/confirm", {"user_id": "7"}, "confirm"),
            (
                "POST",
                f"/memory/v2/{memory_id}/reject",
                {"user_id": "7", "reason": "不是偏好"},
                "reject",
            ),
            (
                "PATCH",
                f"/memory/v2/{memory_id}",
                {"user_id": "7", "key": "favorite_customer", "value": "彩虹乐园"},
                "correct",
            ),
            ("DELETE", f"/memory/v2/{memory_id}?user_id=7&reason=用户删除", None, "delete"),
        ]
        with _patch_agent_repo(repo), _client() as client:
            for method, path, body, action in cases:
                response = client.request(
                    method, path, json=body, headers={"Idempotency-Key": f"memory-{action}"}
                )
                assert response.status_code == 202, response.text
                receipt = response.json()
                assert receipt["success"] is False and receipt["pending_approval"] is True
                run = repo.get(receipt["run_id"])
                assert run.user_id == "7" and run.status == "waiting_user"
                assert run.steps[0].tool_id == "memory_v2" and run.steps[0].action == action
                assert "user_id" not in run.steps[0].params
                assert not run.tool_calls
                assert "step.approved" not in {event.event_type for event in run.events}
                repeated = client.request(
                    method, path, json=body, headers={"Idempotency-Key": f"memory-{action}"}
                )
                assert repeated.status_code == 202, repeated.text
                assert repeated.json()["run_id"] == receipt["run_id"]
                assert repeated.json()["approval_request_id"] == receipt["approval_request_id"]
        assert Path(memory_mod.JSON_MEMORY_PATH).read_bytes() == before
        assert service.get_preference(owner, "customer") is None
    finally:
        memory_mod.reset_user_memory_service()


def test_memory_v2_blocked_source_fails_after_explicit_shared_approval(
    tmp_path, monkeypatch, authenticated_memory_client, local_tools
):
    import app.domain.shared_services.user_memory_service as memory_mod
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.infrastructure.tenant_scope import tenant_scope

    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)
    actor = authenticated_memory_client
    owner = scoped_personal_memory_id(actor.context)
    try:
        service = memory_mod.get_user_memory_service()
        candidate = service.propose_memory_candidate(
            owner, "preference", "customer", "污染客户", confidence=0.95, source="llm_guess"
        )["candidate"]
        assert candidate["status"] == "rejected" and candidate["source_policy"] == "blocked"
        with _patch_agent_repo(repo):
            response = _client().post(
                f"/memory/v2/{candidate['memory_id']}/confirm",
                json={"user_id": "7"},
                headers={"Idempotency-Key": "blocked-memory"},
            )
            assert response.status_code == 202, response.text
            run = repo.get(response.json()["run_id"])
            assert not run.tool_calls
            issue_approval_grant(run, principal_id=str(actor.user_id))
            with tenant_scope(actor.tenant_id):
                done = AgentOrchestrator(repository=repo).continue_run(
                    run.run_id,
                    approved_by=str(actor.user_id),
                    runtime_context=run.metadata["runtime_context"],
                    approval_request_id=run.metadata["approval_request_id"],
                )
        assert done.status == "blocked", done.error
        assert done.metadata["non_retryable"] is True
        assert done.tool_calls[0].tool_id == "memory_v2"
        assert done.tool_calls[0].action == "confirm"
        assert done.tool_calls[0].output["success"] is False
        assert "tool.failed" in {event.event_type for event in done.events}
        assert service.get_preference(owner, "customer") is None
    finally:
        memory_mod.reset_user_memory_service()


def test_memory_store_keeps_concurrent_same_and_other_user_writes(tmp_path, monkeypatch) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod

    memory_dir = tmp_path / "memory"
    memory_path = memory_dir / "memory_store.json"
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "JSON_MEMORY_PATH", str(memory_path))
    memory_mod.reset_user_memory_service()

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    writes = [
        ("memory-a", "first", "A"),
        ("memory-a", "second", "B"),
        ("memory-b", "third", "C"),
    ]
    processes = [
        context.Process(target=_concurrent_memory_candidate_write, args=(*write, barrier))
        for write in writes
    ]
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + 25
        for process in processes:
            process.join(max(0, deadline - time.monotonic()))
        alive = [process for process in processes if process.is_alive()]
        for process in alive:
            process.terminate()
        for process in alive:
            process.join(5)
        assert not alive
        assert [process.exitcode for process in processes] == [0, 0, 0]

        memory_mod.reset_user_memory_service()
        service = memory_mod.get_user_memory_service()
        assert service.get_memory_v2_summary("memory-a")["by_status"] == {"pending": 2}
        assert service.get_memory_v2_summary("memory-b")["by_status"] == {"pending": 1}
        persisted = json.loads(memory_path.read_text(encoding="utf-8"))
        assert set(persisted) == {"memory-a", "memory-b"}
        assert {row["key"] for row in persisted["memory-a"]["memory_v2_records"]} == {
            "first",
            "second",
        }
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        memory_mod.reset_user_memory_service()


@pytest.mark.parametrize("path", ["/memory/v2", "/memory/v2/summary"])
def test_memory_reads_require_session_and_reject_another_owner(path):
    client = _client()
    assert client.get(path, params={"user_id": "other-owner"}).status_code == 403
    assert client.get(path, headers={"X-User-Id": "other-owner"}).status_code == 403
    client.headers.clear()
    assert client.get(path, params={"user_id": "7"}).status_code == 401


def test_memory_write_rejects_forged_owner_before_execution():
    client = _client()
    body = {"user_id": "other-owner", "memory_type": "preference", "key": "test", "value": "forged"}
    assert client.post("/memory/v2/candidates", json=body).status_code == 403
    client.headers.clear()
    assert client.post("/memory/v2/candidates", json=body).status_code == 401


def test_numeric_username_cannot_select_another_canonical_owner(trusted_actor):
    from app.db.models.user import User

    actor = trusted_actor(user_id=7)
    with actor.factory.begin() as db:
        db.get(User, 7).username = "8"
    client = _client()
    client.headers.update(actor.headers)
    assert client.get("/memory/v2", params={"user_id": "8"}).status_code == 403
    assert client.get("/memory/v2", params={"user_id": "7"}).status_code == 200


@pytest.mark.parametrize("role", ["user", "admin"])
def test_memory_tools_bind_owner_before_role_bypass(trusted_actor, role):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    actor = trusted_actor(user_id=7, role=role)
    assert (
        actor_tool_denial("memory_v2", "propose_candidate", actor.context, {"user_id": "7"}) is None
    )
    denied = actor_tool_denial("memory_v2", "propose_candidate", actor.context, {"user_id": "8"})
    assert denied["reason"] == "memory_owner_mismatch"


@pytest.mark.parametrize(
    "tool,action",
    [
        ("sales", "query"),
        ("reports", "export"),
        ("reports", "sales_summary"),
        ("employee", "list"),
        ("employee", "execute"),
        ("excel_analysis", "read"),
        ("excel_analysis", "statistics"),
        ("excel_analysis", "structure"),
        ("excel_analysis", "query"),
    ],
)
def test_business_role_can_execute_registered_read_report_employee_chain(
    trusted_actor, tool, action
):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    actor = trusted_actor(user_id=8, role="user")
    assert actor_tool_denial(tool, action, actor.context, {}) is None
    viewer = trusted_actor(user_id=9, role="viewer")
    assert actor_tool_denial(tool, action, viewer.context, {})["reason"] == "permission_denied"
