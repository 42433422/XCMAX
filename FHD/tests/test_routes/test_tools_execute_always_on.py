"""Regression: /api/tools/execute must not 405 behind SPA history fallback."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.spa_fallback import register_spa_history_fallback
from app.fastapi_routes.tools_execute import router as tools_execute_router


def test_spa_fallback_alone_returns_405_for_tools_execute_post() -> None:
    app = FastAPI()
    register_spa_history_fallback(app)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/tools/execute", json={"tool_id": "t1"})
    assert response.status_code == 405


def test_tools_execute_post_not_405_when_router_mounted() -> None:
    app = FastAPI()
    app.include_router(tools_execute_router)
    register_spa_history_fallback(app)
    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.fastapi_routes.tools_execute.run_tools_execute_agent",
        return_value=({"success": True, "message": "ok"}, 200),
    ):
        response = client.post("/api/tools/execute", json={"tool_id": "t1"})
    assert response.status_code != 405
    assert response.status_code == 200
    assert response.json().get("success") is True