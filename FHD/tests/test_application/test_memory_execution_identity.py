"""Memory lifecycle binds account ownership across HTTP and persisted tasks."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.fastapi_routes.domains.misc.routes import router


@pytest.fixture
def memory_service(monkeypatch, tmp_path):
    import app.services.user_memory_service as module

    monkeypatch.setattr(module, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(module, "JSON_MEMORY_PATH", str(tmp_path / "memory.json"))
    module.reset_user_memory_service()
    yield module.get_user_memory_service()
    module.reset_user_memory_service()


def execute(action, params, actor="7"):
    return AgentToolExecutor().execute(
        AgentStep(node_id="memory", tool_id="memory_v2", action=action, params=params),
        runtime_context={"local_user_id": actor, "tenant_id": "1"},
    )


def test_task_memory_read_and_mutation_are_account_scoped_and_persist(memory_service):
    created = execute(
        "propose_candidate",
        {
            "memory_type": "preference",
            "key": "delivery",
            "value": "周五",
            "source": "user_explicit",
        },
    )
    assert created["success"] is True
    memory_id = created["candidate"]["memory_id"]
    assert execute("list", {})["memories"][0]["memory_id"] == memory_id
    assert execute("list", {}, actor="8")["memories"] == []
    rejected = execute("confirm", {"memory_id": memory_id}, actor="8")
    assert rejected["success"] is False
    confirmed = execute("confirm", {"memory_id": memory_id})
    assert confirmed["success"] is True
    assert execute("summary", {})["summary"]["by_status"]["active"] == 1
    from app.services.user_memory_service import get_user_memory_service, reset_user_memory_service

    reset_user_memory_service()
    assert get_user_memory_service().get_preference("7", "delivery") == "周五"


def test_raw_tool_context_and_model_user_id_cannot_select_memory_owner(memory_service):
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    forged = execute_registered_workflow_tool(
        "memory_v2",
        "list",
        {"user_id": "8", "_runtime_context": {"local_user_id": "8", "user_id": "8"}},
    )
    assert forged["success"] is False
    assert forged["code"] == "MEMORY_IDENTITY_REQUIRED"
    assert execute("list", {"user_id": "8"})["code"] == "MEMORY_ACCOUNT_MISMATCH"


def test_memory_http_requires_session_and_rejects_other_account(memory_service, monkeypatch):
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    with patch("app.infrastructure.auth.agent_principal.resolve_session_user", return_value=None):
        response = client.get("/memory/v2", headers={"X-User-ID": "8"})
        assert response.status_code == 401
    user = SimpleNamespace(
        id=7, tenant_id=1, is_active=True, username="owner", role="user", tier=""
    )
    with patch("app.infrastructure.auth.agent_principal.resolve_session_user", return_value=user):
        response = client.get("/memory/v2", params={"user_id": "8"})
        assert response.status_code == 403
        response = client.get("/memory/v2/summary", params={"user_id": "default"})
        assert response.status_code == 200
        assert response.json()["user_id"] == "7"
        response = client.post(
            "/memory/v2/candidates",
            json={"user_id": "8", "memory_type": "preference", "key": "injected", "value": "x"},
        )
        assert response.status_code == 403
