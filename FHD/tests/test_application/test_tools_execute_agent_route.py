from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.domains.system.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_tools_execute_route_runs_registered_tool_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = True
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain),
    ):
        response = _client().post(
            "/api/tools/execute",
            json={
                "tool_id": "ocr",
                "action": "request",
                "params": {
                    "request_id": "tools-ocr-1",
                    "image_url": "https://example.invalid/label.png",
                    "ocr_type": "invoice",
                    "user_id": "tenant-a",
                },
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["event"] == "ocr.requested"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "tools_execute_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"
    assert run.tool_calls[0].permission == "tool.ocr.request"
    assert run.tool_calls[0].cost_units == 1


def test_skills_execute_route_runs_registered_skill_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = True
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain),
    ):
        response = _client().post(
            "/api/skills/execute",
            json={
                "skill_id": "ocr",
                "action": "request",
                "params": {
                    "request_id": "skills-ocr-1",
                    "image_url": "https://example.invalid/label.png",
                    "ocr_type": "invoice",
                    "user_id": "tenant-a",
                },
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.intent == "tools_execute_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"


def test_tools_execute_route_puts_medium_risk_tool_behind_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = _client().post(
            "/api/tools/execute",
            json={
                "tool_id": "business_db",
                "action": "write",
                "params": {
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"customer_name": "ACME Trading"},
                },
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_status"] == "waiting_user"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "waiting_user"
    assert run.tool_calls == []
    assert run.steps[0].tool_id == "business_db"
    assert run.steps[0].action == "write"
    assert run.steps[0].status == "waiting_user"
