from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def maintenance_session(tmp_path, monkeypatch, local_tools, trusted_actor):
    from app.fastapi_routes.domains.system.system_routes import router

    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    actor = trusted_actor(user_id=17, role="admin")
    app = FastAPI()
    app.include_router(router)
    headers = {**actor.headers, "Idempotency-Key": uuid4().hex, "X-User-Id": "tenant-a"}
    return TestClient(app, raise_server_exceptions=False, headers=headers), repo, actor


def _unverified_receipt(response, repo):
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_required"
    assert payload["execution_state"] == "unknown"
    assert "verification" not in payload
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    run = repo.get(payload["run_id"])
    assert run is not None and run.status == "blocked"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    report = run.tool_calls[0].metadata["verification"]
    assert report["accepted"] is False
    assert report["code"] == "result_verifier_unavailable"
    return payload, run, report


def test_system_printer_post_executes_system_maintenance_tool_through_agent(
    maintenance_session,
) -> None:
    """Check dispatch/billing; a mock cannot prove the host printer actually changed."""
    client, repo, actor = maintenance_session
    service = MagicMock()
    service.set_default_printer.return_value = {"success": True, "message": "ok"}

    with patch("app.application.facades.session_facade.get_system_service", return_value=service):
        response = ApprovedCapabilityClient(client, repo, actor).post(
            "/api/system/printer", json={"printer_name": "HP"}
        )

    payload, run, report = _unverified_receipt(response, repo)
    assert payload["agent_run_id"] == payload["run_id"]
    service.set_default_printer.assert_called_once_with("HP")
    assert run.user_id == "17"
    assert run.steps[0].action == "set_default_printer"
    assert run.tool_calls[0].action == "set_default_printer"
    assert run.tool_calls[0].permission == "tool.system_maintenance.set_default_printer"
    assert run.tool_calls[0].cost_units == 2
    assert report["status"] == "inconclusive"
    assert all(check["status"] != "passed" for check in report["checks"])
    assert run.steps[0].attempt_count == 1
    events = {event.event_type for event in run.events}
    assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= events
    assert not {"tool.completed", "run.completed"} & events


def test_performance_cache_invalidate_executes_system_maintenance_tool_through_agent(
    maintenance_session,
) -> None:
    client, repo, actor = maintenance_session
    optimizer = MagicMock()
    optimizer.redis_cache.delete.return_value = 1

    with patch(
        "app.utils.performance.performance_initializer.get_performance_optimizer",
        return_value=optimizer,
    ):
        response = ApprovedCapabilityClient(client, repo, actor).post(
            "/api/performance/cache/invalidate", json={"keys": ["k1"]}
        )

    payload, run, _ = _unverified_receipt(response, repo)
    assert "data" not in payload
    optimizer.redis_cache.delete.assert_called_once_with("k1")
    assert run.tool_calls[0].output["success"] is True
    assert run.tool_calls[0].output["data"]["deleted_count"] == 1
    assert run.tool_calls[0].action == "invalidate_performance_cache"


@pytest.mark.parametrize(
    "path,body,action,service_path",
    [
        (
            "/api/database/restore",
            {"backup_file": "backup.sql"},
            "restore_database",
            "app.application.facades.session_facade.get_database_service",
        ),
        (
            "/api/performance/optimize/reinitialize",
            None,
            "reinitialize_performance",
            "app.utils.performance.performance_initializer.init_performance_optimization",
        ),
    ],
)
def test_system_maintenance_waits_for_approval(
    path, body, action, service_path, maintenance_session
) -> None:
    client, repo, _ = maintenance_session
    with patch(service_path) as get_service:
        response = client.post(path, json=body)

    assert response.status_code == 202
    payload = response.json()
    assert payload["error_code"] == "approval_required"
    get_service.assert_not_called()
    run = repo.get(payload["run_id"])
    assert run is not None and run.status == "waiting_user"
    assert (run.steps[0].tool_id, run.steps[0].action) == ("system_maintenance", action)
    assert run.steps[0].risk == "high" and not run.tool_calls
