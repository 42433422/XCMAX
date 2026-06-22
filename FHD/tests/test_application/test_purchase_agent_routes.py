from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import purchase as purchase_routes


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(purchase_routes, "_svc", lambda: fake_service)
    app = FastAPI()
    app.include_router(purchase_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_purchase_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"purchase_{action}"
    assert run.tool_calls[0].tool_id == "purchase"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.purchase.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_purchase_supplier_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_supplier.return_value = {"success": True, "data": {"id": 7}}
    svc.update_supplier.return_value = {"success": True, "data": {"id": 7}}
    svc.delete_supplier.return_value = {"success": True}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        create_supplier = client.post(
            "/api/purchase/suppliers",
            json={"name": "星光供应商"},
            headers={"X-User-Id": "tenant-a"},
        )
        update_supplier = client.put(
            "/api/purchase/suppliers/7",
            json={"status": "active"},
            headers={"X-User-Id": "tenant-a"},
        )
        delete_supplier = client.delete(
            "/api/purchase/suppliers/7",
            headers={"X-User-Id": "tenant-a"},
        )

    assert create_supplier.status_code == 200
    assert update_supplier.status_code == 200
    assert delete_supplier.status_code == 200

    svc.create_supplier.assert_called_once_with({"name": "星光供应商"})
    svc.update_supplier.assert_called_once_with(7, {"status": "active"})
    svc.delete_supplier.assert_called_once_with(7)

    _assert_purchase_run(repo, create_supplier.json()["run_id"], "create_supplier")
    _assert_purchase_run(repo, update_supplier.json()["run_id"], "update_supplier")
    _assert_purchase_run(repo, delete_supplier.json()["run_id"], "delete_supplier")


def test_purchase_order_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_purchase_order.return_value = {"success": True, "data": {"id": 9}}
    svc.update_purchase_order.return_value = {"success": True, "data": {"id": 9}}
    svc.approve_purchase_order.return_value = {"success": True, "data": {"status": "approved"}}
    svc.cancel_purchase_order.return_value = {"success": True, "data": {"status": "cancelled"}}
    svc.create_purchase_inbound.return_value = {"success": True, "data": {"id": 5}}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        create_order = client.post(
            "/api/purchase/orders",
            json={"supplier_id": 7},
            headers={"X-User-Id": "tenant-a"},
        )
        update_order = client.put(
            "/api/purchase/orders/9",
            json={"remark": "调整交期"},
            headers={"X-User-Id": "tenant-a"},
        )
        approve_order = client.post(
            "/api/purchase/orders/9/approve",
            params={"approver": "manager-p54"},
            headers={"X-User-Id": "tenant-a"},
        )
        cancel_order = client.post(
            "/api/purchase/orders/9/cancel",
            headers={"X-User-Id": "tenant-a"},
        )
        create_inbound = client.post(
            "/api/purchase/inbounds",
            json={"order_id": 9},
            headers={"X-User-Id": "tenant-a"},
        )

    assert create_order.status_code == 200
    assert update_order.status_code == 200
    assert approve_order.status_code == 200
    assert cancel_order.status_code == 200
    assert create_inbound.status_code == 200

    svc.create_purchase_order.assert_called_once_with({"supplier_id": 7})
    svc.update_purchase_order.assert_called_once_with(9, {"remark": "调整交期"})
    svc.approve_purchase_order.assert_called_once_with(9, "manager-p54")
    svc.cancel_purchase_order.assert_called_once_with(9)
    svc.create_purchase_inbound.assert_called_once_with({"order_id": 9})

    _assert_purchase_run(repo, create_order.json()["run_id"], "create_order")
    _assert_purchase_run(repo, update_order.json()["run_id"], "update_order")
    _assert_purchase_run(repo, approve_order.json()["run_id"], "approve_order")
    _assert_purchase_run(repo, cancel_order.json()["run_id"], "cancel_order")
    _assert_purchase_run(repo, create_inbound.json()["run_id"], "create_inbound")
