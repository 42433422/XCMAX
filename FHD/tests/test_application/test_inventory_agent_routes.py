from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import inventory as inventory_routes


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(inventory_routes, "_svc", lambda: fake_service)
    app = FastAPI()
    app.include_router(inventory_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_inventory_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"inventory_{action}"
    assert run.tool_calls[0].tool_id == "inventory"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.inventory.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_inventory_structure_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_storage_location.return_value = {"success": True, "id": 11}
    svc.update_storage_location.return_value = {"success": True, "data": {"id": 10}}
    svc.create_warehouse.return_value = {"success": True, "data": {"id": 3}}
    svc.update_warehouse.return_value = {"success": True, "data": {"id": 3}}
    svc.delete_warehouse.return_value = {"success": True}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        create_location = client.post(
            "/api/inventory/locations",
            json={"code": "A-01"},
            headers={"X-User-Id": "tenant-a"},
        )
        update_location = client.put(
            "/api/inventory/locations/10",
            json={"status": "full"},
            headers={"X-User-Id": "tenant-a"},
        )
        create_warehouse = client.post(
            "/api/inventory/warehouses",
            json={"name": "主仓"},
            headers={"X-User-Id": "tenant-a"},
        )
        update_warehouse = client.put(
            "/api/inventory/warehouses/3",
            json={"name": "副仓"},
            headers={"X-User-Id": "tenant-a"},
        )
        delete_warehouse = client.delete(
            "/api/inventory/warehouses/3",
            headers={"X-User-Id": "tenant-a"},
        )

    assert create_location.status_code == 200
    assert update_location.status_code == 200
    assert create_warehouse.status_code == 200
    assert update_warehouse.status_code == 200
    assert delete_warehouse.status_code == 200

    svc.create_storage_location.assert_called_once_with({"code": "A-01"})
    svc.update_storage_location.assert_called_once_with(10, {"status": "full"})
    svc.create_warehouse.assert_called_once_with({"name": "主仓"})
    svc.update_warehouse.assert_called_once_with(3, {"name": "副仓"})
    svc.delete_warehouse.assert_called_once_with(3)

    _assert_inventory_run(repo, create_location.json()["run_id"], "create_storage_location")
    _assert_inventory_run(repo, update_location.json()["run_id"], "update_storage_location")
    _assert_inventory_run(repo, create_warehouse.json()["run_id"], "create_warehouse")
    _assert_inventory_run(repo, update_warehouse.json()["run_id"], "update_warehouse")
    _assert_inventory_run(repo, delete_warehouse.json()["run_id"], "delete_warehouse")


def test_inventory_stock_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.inventory_in.return_value = {"success": True}
    svc.inventory_out.return_value = {"success": True}
    svc.inventory_transfer.return_value = {"success": True}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        stock_in = client.post(
            "/api/inventory/in",
            json={"product_id": 1, "warehouse_id": 2, "quantity": 3},
            headers={"X-User-Id": "tenant-a"},
        )
        stock_out = client.post(
            "/api/inventory/out",
            json={"product_id": 1, "warehouse_id": 2, "quantity": 1, "unit_price": 5},
            headers={"X-User-Id": "tenant-a"},
        )
        transfer = client.post(
            "/api/inventory/transfer",
            json={
                "product_id": 1,
                "from_warehouse_id": 2,
                "to_warehouse_id": 3,
                "quantity": 1,
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert stock_in.status_code == 200
    assert stock_out.status_code == 200
    assert transfer.status_code == 200

    assert svc.inventory_in.call_args.kwargs["unit_price"] is None
    assert svc.inventory_in.call_args.kwargs["quantity"] == 3.0
    assert svc.inventory_out.call_args.kwargs["unit_price"] == 5.0
    assert svc.inventory_transfer.call_args.kwargs["from_warehouse_id"] == 2
    assert svc.inventory_transfer.call_args.kwargs["quantity"] == 1.0

    _assert_inventory_run(repo, stock_in.json()["run_id"], "stock_in")
    _assert_inventory_run(repo, stock_out.json()["run_id"], "stock_out")
    _assert_inventory_run(repo, transfer.json()["run_id"], "transfer")
