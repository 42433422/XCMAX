"""Public task metadata cannot become an execution identity or host routing flag."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.application.agent_orchestrator.run_models import AgentRun
from app.fastapi_routes.domains.agent.routes import router
from app.infrastructure.auth.agent_principal import (
    AgentPrincipal,
    bind_agent_runtime_context,
    require_agent_principal,
)


@pytest.mark.parametrize("tenant", ["", "7"])
def test_create_run_overwrites_client_identity_before_persistence(tenant):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_agent_principal] = lambda: AgentPrincipal(
        user_id="17", tenant_id=tenant
    )
    captured = {}

    def start(**kwargs):
        captured.update(kwargs["runtime_context"])
        return AgentRun(user_id=kwargs["user_id"], message=kwargs["message"], status="completed")

    with patch("app.fastapi_routes.domains.agent.routes.AgentOrchestrator") as factory:
        factory.return_value.start_run.side_effect = start
        response = TestClient(app).post(
            "/api/agent/runs",
            json={
                "message": "读取当前页面",
                "auto_execute": False,
                "runtime_context": {
                    "actor_id": "other",
                    "local_user_id": "other",
                    "user_id": "other",
                    "tenant_id": "999",
                    "service_source": "fastapi_customer_route",
                    "route_module": "arbitrary",
                    "route_confirmed": True,
                    "is_admin": True,
                    "_runtime_context": {"tenant_id": "999"},
                    "conversation_id": "conversation-1",
                },
            },
        )
    assert response.status_code == 200
    assert captured == {
        "user_id": "17",
        "local_user_id": "17",
        "actor_id": "17",
        "tenant_id": tenant,
        "conversation_id": "conversation-1",
    }


def test_administrator_resume_preserves_original_task_account():
    run = AgentRun(
        user_id="owner", message="task", metadata={"runtime_context": {"tenant_id": "7"}}
    )
    context = bind_agent_runtime_context(
        {"local_user_id": "attacker", "tenant_id": "999", "source": "resume"},
        AgentPrincipal(user_id="administrator", tenant_id="3", is_admin=True),
        run=run,
    )
    assert context == {
        "user_id": "owner",
        "local_user_id": "owner",
        "actor_id": "owner",
        "tenant_id": "7",
        "source": "resume",
    }


def test_disabled_session_cannot_fall_back_to_a_client_identity_header(monkeypatch):
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    request = Request({"type": "http", "headers": [], "path": "/api/agent/runs"})
    with patch(
        "app.infrastructure.auth.agent_principal.resolve_session_user",
        return_value=SimpleNamespace(id=17, is_active=False),
    ):
        with pytest.raises(HTTPException) as error:
            require_agent_principal(request, x_user_id="other")
    assert error.value.status_code == 403
