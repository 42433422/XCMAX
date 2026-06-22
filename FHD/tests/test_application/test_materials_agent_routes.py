from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import materials as materials_routes


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        materials_routes,
        "get_material_application_service",
        lambda: fake_service,
    )
    app = FastAPI()
    app.include_router(materials_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_material_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"materials_{action}"
    assert run.tool_calls[0].tool_id == "materials"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.materials.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_material_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_material.return_value = {"success": True, "data": {"id": 1, "name": "树脂"}}
    svc.update_material.return_value = {"success": True, "data": {"id": 1}}
    svc.delete_material.return_value = None
    svc.batch_delete_materials.return_value = None
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        create = client.post(
            "/api/materials",
            json={"name": "树脂", "min_quantity": 12, "material_code": "R-001"},
            headers={"X-User-Id": "tenant-a"},
        )
        update = client.put(
            "/api/materials/1",
            json={"name": "树脂 v2"},
            headers={"X-User-Id": "tenant-a"},
        )
        delete = client.delete(
            "/api/materials/1",
            headers={"X-User-Id": "tenant-a"},
        )
        batch = client.post(
            "/api/materials/batch-delete",
            json={"material_ids": [1, 2], "ids": [3]},
            headers={"X-User-Id": "tenant-a"},
        )

    assert create.status_code == 200
    assert update.status_code == 200
    assert delete.status_code == 200
    assert batch.status_code == 200

    create_payload = create.json()
    update_payload = update.json()
    delete_payload = delete.json()
    batch_payload = batch.json()
    assert create_payload["agent_run_id"] == create_payload["run_id"]
    assert update_payload["data"]["name"] == "树脂 v2"
    assert delete_payload["message"] == "删除成功"
    assert batch_payload["deleted_count"] == 2
    assert batch_payload["message"] == "已删除 2 条记录"

    svc.create_material.assert_called_once()
    assert svc.create_material.call_args.args[0]["min_stock"] == 12
    svc.update_material.assert_called_once_with(1, name="树脂 v2")
    svc.delete_material.assert_called_once_with(1)
    svc.batch_delete_materials.assert_called_once_with([1, 2])

    _assert_material_run(repo, create_payload["run_id"], "create")
    _assert_material_run(repo, update_payload["run_id"], "update")
    _assert_material_run(repo, delete_payload["run_id"], "delete")
    _assert_material_run(repo, batch_payload["run_id"], "batch_delete")


def test_material_create_failure_is_recorded_on_agent_run(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_material.return_value = {"success": False, "message": "duplicate"}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = client.post(
            "/api/materials",
            json={"name": "重复项"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"] == "duplicate"
    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "failed"
    assert run.tool_calls[0].tool_id == "materials"
    assert run.tool_calls[0].action == "create"
    assert run.tool_calls[0].status == "failed"
