from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import shipment_orders


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(shipment_orders, "_svc", lambda: fake_service)
    app = FastAPI()
    app.include_router(shipment_orders.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_shipment_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"shipment_records_{action}"
    assert run.tool_calls[0].tool_id == "shipment_records"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.shipment_records.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_shipment_record_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_shipment.return_value = {"success": True, "data": {"id": 7}}
    svc.update_shipment_record.return_value = {"success": True, "data": {"id": 7}}
    svc.delete_shipment_record.return_value = {"success": True, "deleted_count": 1}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        create_record = client.post(
            "/api/shipment/shipment-records/record",
            json={
                "unit_name": "星光贸易",
                "products": [{"name": "5003", "qty": 2}],
                "contact_person": "张三",
            },
            headers={"X-User-Id": "tenant-a"},
        )
        update_record = client.patch(
            "/api/shipment/shipment-records/record",
            json={"id": 7, "unit_name": "星光贸易二部", "status": "printed"},
            headers={"X-User-Id": "tenant-a"},
        )
        delete_record = client.request(
            "DELETE",
            "/api/shipment/shipment-records/record",
            json={"id": 7},
            headers={"X-User-Id": "tenant-a"},
        )

    assert create_record.status_code == 200
    assert update_record.status_code == 200
    assert delete_record.status_code == 200

    svc.create_shipment.assert_called_once_with(
        unit_name="星光贸易",
        items_data=[{"name": "5003", "qty": 2}],
        contact_person="张三",
        contact_phone=None,
    )
    svc.update_shipment_record.assert_called_once_with(
        record_id=7,
        unit_name="星光贸易二部",
        products=None,
        date=None,
        status="printed",
    )
    svc.delete_shipment_record.assert_called_once_with(7)

    _assert_shipment_run(repo, create_record.json()["run_id"], "create")
    _assert_shipment_run(repo, update_record.json()["run_id"], "update")
    _assert_shipment_run(repo, delete_record.json()["run_id"], "delete")
