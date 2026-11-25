"""Regression: /api/tools/execute must not 405 behind SPA history fallback."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.spa_fallback import register_spa_history_fallback
from app.fastapi_routes.tools_execute import router as tools_execute_router
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_spa_fallback_alone_returns_405_for_tools_execute_post() -> None:
    app = FastAPI()
    register_spa_history_fallback(app)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/tools/execute", json={"tool_id": "t1"})
    assert response.status_code == 405


def test_tools_execute_post_not_405_when_router_mounted(trusted_actor) -> None:
    app = FastAPI()
    app.include_router(tools_execute_router)
    register_spa_history_fallback(app)
    client = TestClient(app, raise_server_exceptions=False)
    actor = trusted_actor()
    with patch(
        "app.fastapi_routes.tools_execute.run_tools_execute_agent",
        return_value=({"success": True, "message": "ok"}, 200),
    ) as dispatch:
        denied = client.post("/api/tools/execute", json={"tool_id": "t1"})
        assert denied.status_code == 401
        dispatch.assert_not_called()
        response = client.post("/api/tools/execute", json={"tool_id": "t1"}, headers=actor.headers)
    assert response.status_code != 405
    assert response.status_code == 200
    assert response.json().get("success") is True


@pytest.mark.parametrize(
    "path, status", [("/api/tools/execute", 400), ("/api/skills/execute", 404)]
)
def test_invalid_tool_request_does_not_expose_parser_details(trusted_actor, path, status) -> None:
    app = FastAPI()
    app.include_router(tools_execute_router)
    client = TestClient(app, raise_server_exceptions=False)
    actor = trusted_actor()
    private_detail = "internal parser configuration at /private/runtime/settings.json"
    with (
        patch(
            "app.fastapi_routes.tools_execute._resolve_tool_request",
            side_effect=ValueError(private_detail),
        ) as parse,
        patch(
            "app.application.agent_orchestrator.AgentOrchestrator.start_run_from_plan"
        ) as dispatch,
    ):
        response = client.post(path, json={"tool_id": "synthetic"}, headers=actor.headers)
    assert response.status_code == status
    if status == 400:
        parse.assert_called_once()
        assert response.json()["success"] is False
        assert response.json()["error_code"] == "invalid_tool_arguments"
    else:
        parse.assert_not_called()
    assert private_detail not in response.text
    dispatch.assert_not_called()
