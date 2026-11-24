from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(actor) -> TestClient:
    from app.fastapi_routes.domains.system.system_routes import router

    app = FastAPI()
    app.include_router(router)
    headers = {**actor.headers, "Idempotency-Key": uuid4().hex}
    return TestClient(app, raise_server_exceptions=False, headers=headers)


def _patch_agent_repo(repo: InMemoryAgentRunRepository):
    return patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    )


def _configure_billing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def test_system_printer_post_executes_system_maintenance_tool_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    """Check dispatch/billing; a mock cannot prove the host printer actually changed."""
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.set_default_printer.return_value = {"success": True, "message": "ok"}

    with (
        _patch_agent_repo(repo),
        patch("app.application.facades.session_facade.get_system_service", return_value=service),
    ):
        actor = trusted_actor(user_id=17, role="admin")
        response = ApprovedCapabilityClient(_client(actor), repo, actor).post(
            "/api/system/printer",
            json={"printer_name": "HP"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_inconclusive"
    assert payload["verification_code"] == "result_verifier_unavailable"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert payload["agent_run_id"] == payload["run_id"]
    service.set_default_printer.assert_called_once_with("HP")

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "17"
    assert run.status == "blocked"
    assert run.intent == "system_maintenance_set_default_printer"
    assert run.steps[0].risk == "medium"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    assert run.tool_calls[0].action == "set_default_printer"
    assert run.tool_calls[0].permission == "tool.system_maintenance.set_default_printer"
    assert run.tool_calls[0].cost_units == 2
    report = run.tool_calls[0].metadata["verification"]
    assert report["status"] == "inconclusive"
    assert report["accepted"] is False
    assert report["code"] == "result_verifier_unavailable"
    assert all(check["status"] != "passed" for check in report["checks"])
    assert run.steps[0].attempt_count == 1
    events = {event.event_type for event in run.events}
    assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= events
    assert not {"tool.completed", "run.completed"} & events


def test_database_restore_waits_for_approval_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.restore_database.return_value = {"success": True, "message": "restored"}

    with (
        _patch_agent_repo(repo),
        patch("app.application.facades.session_facade.get_database_service", return_value=service),
    ):
        response = _client(trusted_actor(user_id=17, role="admin")).post(
            "/api/database/restore",
            json={"backup_file": "backup.sql"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["error_code"] == "approval_required"
    service.restore_database.assert_not_called()
    run = repo.get(payload["run_id"])
    assert run is not None and run.status == "waiting_user"
    assert run.intent == "system_maintenance_restore_database"
    assert run.steps[0].risk == "high" and not run.tool_calls


def test_performance_cache_invalidate_executes_system_maintenance_tool_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    optimizer = MagicMock()
    optimizer.redis_cache.delete.return_value = 1

    with (
        _patch_agent_repo(repo),
        patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=optimizer,
        ),
    ):
        actor = trusted_actor(user_id=17, role="admin")
        response = ApprovedCapabilityClient(_client(actor), repo, actor).post(
            "/api/performance/cache/invalidate",
            json={"keys": ["k1"]},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["verification_code"] == "result_verifier_unavailable"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert payload["data"]["deleted_count"] == 1
    optimizer.redis_cache.delete.assert_called_once_with("k1")

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "system_maintenance_invalidate_performance_cache"
    assert run.status == "blocked"
    assert run.tool_calls[0].output["success"] is True
    assert run.tool_calls[0].metadata["verification"]["accepted"] is False
    assert run.steps[0].risk == "medium"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    assert run.tool_calls[0].action == "invalidate_performance_cache"


def test_performance_reinitialize_waits_for_approval_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    optimizer = MagicMock()
    optimizer.get_status.return_value = {"status": "ok"}

    with (
        _patch_agent_repo(repo),
        patch(
            "app.utils.performance.performance_initializer.init_performance_optimization",
            return_value=optimizer,
        ),
    ):
        response = _client(trusted_actor(user_id=17, role="admin")).post(
            "/api/performance/optimize/reinitialize",
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["error_code"] == "approval_required"
    optimizer.get_status.assert_not_called()
    run = repo.get(payload["run_id"])
    assert run is not None and run.status == "waiting_user"
    assert run.intent == "system_maintenance_reinitialize_performance"
    assert run.steps[0].risk == "high" and not run.tool_calls
