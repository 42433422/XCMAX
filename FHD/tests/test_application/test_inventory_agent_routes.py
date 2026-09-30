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


@pytest.mark.parametrize("action,method,path,payload,expected,result", [
    ("create_storage_location", "POST", "/locations", {"code": "A-01"}, ({"code": "A-01"},), {"success": True, "id": 11}),
    ("update_storage_location", "PUT", "/locations/10", {"status": "full"}, (10, {"status": "full"}), {"success": True, "data": {"id": 10}}),
    ("create_warehouse", "POST", "/warehouses", {"name": "主仓"}, ({"name": "主仓"},), {"success": True, "data": {"id": 3}}),
    ("update_warehouse", "PUT", "/warehouses/3", {"name": "副仓"}, (3, {"name": "副仓"}), {"success": True, "data": {"id": 3}}),
    ("delete_warehouse", "DELETE", "/warehouses/3", None, (3,), {"success": True}),
])
def test_inventory_structure_mutation_routes_execute_through_agent_orchestrator(
    tmp_path, monkeypatch, action, method, path, payload, expected, result,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    getattr(svc, action).return_value = result
    client = _client(svc, monkeypatch)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = client.request(method, "/api/inventory" + path, json=payload, headers={"X-User-Id": "tenant-a"})
    assert response.status_code == 200
    getattr(svc, action).assert_called_once_with(*expected)
    _assert_inventory_run(repo, response.json()["run_id"], action)


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
    assert "unit_price" not in svc.inventory_out.call_args.kwargs
    assert svc.inventory_transfer.call_args.kwargs["from_warehouse_id"] == 2
    assert svc.inventory_transfer.call_args.kwargs["quantity"] == 1.0

    _assert_inventory_run(repo, stock_in.json()["run_id"], "stock_in")
    _assert_inventory_run(repo, stock_out.json()["run_id"], "stock_out")
    _assert_inventory_run(repo, transfer.json()["run_id"], "transfer")
