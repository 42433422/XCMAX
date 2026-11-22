from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(actor) -> TestClient:
    from app.fastapi_routes.tools_execute import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, headers=actor.headers)


def _assert_published_ocr_is_unverified(payload, run) -> None:
    """Mock publication checks dispatch; it does not prove downstream OCR delivery."""
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_inconclusive"
    assert payload["verification_code"] == "result_verifier_unavailable"
    assert payload["outcome"] == "unknown"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0].output["success"] is True
    assert run.tool_calls[0].output["published"] is True
    report = run.tool_calls[0].metadata["verification"]
    assert report["status"] == "inconclusive" and report["accepted"] is False
    assert report["code"] == "result_verifier_unavailable"
    assert all(check["status"] != "passed" for check in report["checks"])
    assert not {"tool.completed", "run.completed"} & {event.event_type for event in run.events}


def test_tools_execute_route_runs_registered_tool_through_agent_orchestrator(
    tmp_path, monkeypatch, local_tools, trusted_actor
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
        response = _client(
            trusted_actor(user_id=17, role="ocr-operator", permissions=["tool.ocr.request"])
        ).post(
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

    # The OCR event is published, but this write has no independent verifier.
    # The run stays blocked so the route does not claim a completed receipt.
    assert response.status_code == 202
    payload = response.json()
    assert payload["event"] == "ocr.requested"
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == "blocked"

    run = repo.get(payload["run_id"])
    assert run is not None
    _assert_published_ocr_is_unverified(payload, run)
    ocr_domain.emit_ocr_requested.assert_called_once()
    assert run.user_id == "17"
    assert run.status == "blocked"
    assert run.intent == "tools_execute_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"
    assert run.tool_calls[0].permission == "tool.ocr.request"
    assert run.tool_calls[0].cost_units == 1


def test_skills_execute_route_runs_registered_skill_through_agent_orchestrator(
    tmp_path, monkeypatch, local_tools, trusted_actor
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
        response = _client(
            trusted_actor(user_id=17, role="ocr-operator", permissions=["tool.ocr.request"])
        ).post(
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

    assert response.status_code == 202
    payload = response.json()
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == "blocked"

    run = repo.get(payload["run_id"])
    assert run is not None
    _assert_published_ocr_is_unverified(payload, run)
    ocr_domain.emit_ocr_requested.assert_called_once()
    assert run.status == "blocked"
    assert run.intent == "tools_execute_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"


def test_tools_execute_route_puts_medium_risk_tool_behind_confirmation(
    tmp_path,
    monkeypatch,
    trusted_actor,
) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = _client(
            trusted_actor(user_id=17, role="db-writer", permissions=["business_db.write"])
        ).post(
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
    assert payload["success"] is False
    assert payload["error_code"] == "approval_required"
    assert payload["agent_status"] == "waiting_user"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "waiting_user"
    assert run.tool_calls == []
    assert run.steps[0].tool_id == "business_db"
    assert run.steps[0].action == "write"
    assert run.steps[0].status == "waiting_user"
