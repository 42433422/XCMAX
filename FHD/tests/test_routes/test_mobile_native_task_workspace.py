from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import (
    InMemoryAgentRunRepository,
    set_agent_run_repository_for_tests,
)
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_models import AgentTask
from app.fastapi_routes.mobile_extensions.routes_tasks import TaskRoutes
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal


@pytest.fixture
def native():
    repo = InMemoryAgentRunRepository()
    set_agent_run_repository_for_tests(repo)
    app = FastAPI()
    app.include_router(TaskRoutes(SimpleNamespace(), lambda: None).router, prefix="/api/mobile/v1")
    app.dependency_overrides[require_agent_principal] = lambda: AgentPrincipal(
        user_id="owner", tenant_id="tenant"
    )
    yield TestClient(app), repo
    set_agent_run_repository_for_tests(None)


@pytest.mark.parametrize("suffix", ["", "/read", "/archive"])
def test_native_task_preserves_desktop_tenant_boundary(native, suffix):
    client, repo = native
    task = AgentTask(task_id="private", user_id="owner", tenant_id="other", title="private")
    repo.save_task(task)
    before = task.to_dict()
    response = client.request(
        "POST" if suffix else "GET", f"/api/mobile/v1/workspace/agent/tasks/private{suffix}"
    )
    assert response.status_code == 404
    assert repo.get_task(user_id="owner", tenant_id="other", task_id="private").to_dict() == before


@pytest.mark.parametrize("action", ["pause", "resume", "cancel", "retry", "continue"])
def test_native_run_cannot_control_another_mod(native, action):
    client, repo = native
    run = AgentRun(
        user_id="owner",
        message="private",
        status="running",
        metadata={
            "runtime_context": {
                "tenant_id": "tenant",
                "_mod_authorization": {"mod_id": "private-mod"},
            }
        },
    )
    repo.save(run)
    before = run.to_dict()
    response = client.post(f"/api/mobile/v1/workspace/agent/runs/{run.run_id}/{action}", json={})
    assert response.status_code in {403, 404}
    assert repo.get(run.run_id).to_dict() == before


def test_native_task_surface_keeps_original_auth_dependency(native):
    client, _ = native
    client.app.dependency_overrides.clear()
    response = client.get("/api/mobile/v1/workspace/agent/tasks/private")
    assert response.status_code == 401
    assert client.post("/api/mobile/v1/workspace/agent/runs", json={}).status_code == 404
