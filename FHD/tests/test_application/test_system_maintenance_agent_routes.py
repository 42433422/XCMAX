from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.domains.system.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


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
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.set_default_printer.return_value = {"success": True, "message": "ok"}

    with (
        _patch_agent_repo(repo),
        patch("app.application.facades.session_facade.get_system_service", return_value=service),
    ):
        response = _client().post(
            "/api/system/printer",
            json={"printer_name": "HP"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_run_id"] == payload["run_id"]
    service.set_default_printer.assert_called_once_with("HP")

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "system_maintenance_set_default_printer"
    assert run.steps[0].risk == "medium"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    assert run.tool_calls[0].action == "set_default_printer"
    assert run.tool_calls[0].permission == "tool.system_maintenance.set_default_printer"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed"} <= {
        event.event_type for event in run.events
    }


def test_database_restore_executes_system_maintenance_tool_through_agent(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    service = MagicMock()
    service.restore_database.return_value = {"success": True, "message": "restored"}

    with (
        _patch_agent_repo(repo),
        patch("app.application.facades.session_facade.get_database_service", return_value=service),
    ):
        response = _client().post(
            "/api/database/restore",
            json={"backup_file": "backup.sql"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    service.restore_database.assert_called_once_with("backup.sql")

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "system_maintenance_restore_database"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    assert run.tool_calls[0].action == "restore_database"
    assert run.tool_calls[0].permission == "tool.system_maintenance.restore_database"
    assert run.tool_calls[0].cost_units == 2


def test_performance_cache_invalidate_executes_system_maintenance_tool_through_agent(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    optimizer = MagicMock()
    optimizer.redis_cache.delete.return_value = 1

    with (
        _patch_agent_repo(repo),
        patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=optimizer
        ),
    ):
        response = _client().post(
            "/api/performance/cache/invalidate",
            json={"keys": ["k1"]},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["deleted_count"] == 1
    optimizer.redis_cache.delete.assert_called_once_with("k1")

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "system_maintenance_invalidate_performance_cache"
    assert run.steps[0].risk == "medium"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    assert run.tool_calls[0].action == "invalidate_performance_cache"


def test_performance_reinitialize_executes_system_maintenance_tool_through_agent(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    _configure_billing(monkeypatch, tmp_path)
    optimizer = MagicMock()
    optimizer.get_status.return_value = {"status": "ok"}

    with (
        _patch_agent_repo(repo),
        patch(
            "app.utils.performance_initializer.init_performance_optimization",
            return_value=optimizer,
        ),
    ):
        response = _client().post(
            "/api/performance/optimize/reinitialize",
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "ok"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "system_maintenance_reinitialize_performance"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "system_maintenance"
    assert run.tool_calls[0].action == "reinitialize_performance"
