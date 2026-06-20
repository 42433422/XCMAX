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


def _assert_shipment_order_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"shipment_orders_{action}"
    assert run.tool_calls[0].tool_id == "shipment_orders"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.shipment_orders.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_shipment_order_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    shipment_file = tmp_path / "shipment.xlsx"
    shipment_file.write_bytes(b"fake")
    svc = MagicMock()
    svc.generate_shipment_document.return_value = {
        "success": True,
        "file_path": str(shipment_file),
        "record_id": 7,
    }
    svc.mark_as_printed.return_value = {"success": True, "message": "已标记为已打印"}
    svc.clear_shipment_by_unit.return_value = {"success": True, "cleared_count": 2}
    svc.set_order_sequence.return_value = {"success": True, "sequence": 12}
    svc.reset_order_sequence.return_value = {"success": True, "sequence": 1}
    svc.clear_all_orders.return_value = {"success": True, "deleted_count": 5}
    svc.delete_shipment.return_value = {"success": True}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        generate = client.post(
            "/api/shipment/generate",
            json={
                "unit_name": "星光贸易",
                "products": [{"name": "5003", "qty": 2}],
                "date": "2026-06-19",
            },
            headers={"X-User-Id": "tenant-a"},
        )
        generate_batch = client.post(
            "/api/shipment/generate-batch",
            json={
                "shipments": [{"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]}]
            },
            headers={"X-User-Id": "tenant-a"},
        )
        print_order = client.post(
            "/api/shipment/print",
            json={"file_path": str(shipment_file), "order_id": 7, "printer_name": "HP"},
            headers={"X-User-Id": "tenant-a"},
        )
        clear_unit = client.post(
            "/api/shipment/orders/clear-shipment",
            json={"purchase_unit": "星光贸易"},
            headers={"X-User-Id": "tenant-a"},
        )
        set_sequence = client.post(
            "/api/orders/set-sequence",
            json={"sequence": 12},
            headers={"X-User-Id": "tenant-a"},
        )
        reset_sequence = client.post(
            "/api/shipment/orders/reset-sequence",
            headers={"X-User-Id": "tenant-a"},
        )
        clear_all = client.delete(
            "/api/orders/clear-all",
            headers={"X-User-Id": "tenant-a"},
        )
        delete_order = client.delete(
            "/api/shipment/orders/7",
            headers={"X-User-Id": "tenant-a"},
        )

    assert generate.status_code == 200
    assert generate_batch.status_code == 200
    assert print_order.status_code == 200
    assert clear_unit.status_code == 200
    assert set_sequence.status_code == 200
    assert reset_sequence.status_code == 200
    assert clear_all.status_code == 200
    assert delete_order.status_code == 200

    assert svc.generate_shipment_document.call_args_list[0].kwargs == {
        "unit_name": "星光贸易",
        "products": [{"name": "5003", "qty": 2}],
        "date": "2026-06-19",
    }
    assert svc.generate_shipment_document.call_args_list[1].kwargs == {
        "unit_name": "星光贸易",
        "products": [{"name": "5003", "qty": 2}],
        "date": None,
    }
    svc.mark_as_printed.assert_called_once_with(7, printer_name="HP")
    svc.clear_shipment_by_unit.assert_called_once_with("星光贸易")
    svc.set_order_sequence.assert_called_once_with(12)
    svc.reset_order_sequence.assert_called_once_with()
    svc.clear_all_orders.assert_called_once_with()
    svc.delete_shipment.assert_called_once_with(7)

    assert generate.json()["record_id"] == 7
    assert generate_batch.json()["data"]["processed"] == 1
    assert print_order.json()["updated"] is True
    assert clear_unit.json()["cleared_count"] == 2
    assert set_sequence.json()["sequence"] == 12
    assert reset_sequence.json()["sequence"] == 1
    assert clear_all.json()["deleted_count"] == 5
    assert delete_order.json()["deleted_id"] == 7

    _assert_shipment_order_run(repo, generate.json()["run_id"], "generate")
    _assert_shipment_order_run(repo, generate_batch.json()["run_id"], "generate_batch")
    _assert_shipment_order_run(repo, print_order.json()["run_id"], "print")
    _assert_shipment_order_run(repo, clear_unit.json()["run_id"], "clear_shipment")
    _assert_shipment_order_run(repo, set_sequence.json()["run_id"], "set_sequence")
    _assert_shipment_order_run(repo, reset_sequence.json()["run_id"], "reset_sequence")
    _assert_shipment_order_run(repo, clear_all.json()["run_id"], "clear_all")
    _assert_shipment_order_run(repo, delete_order.json()["run_id"], "delete")
