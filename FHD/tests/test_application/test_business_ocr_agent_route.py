from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.business_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_business_ocr_route_publishes_event_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = True
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
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
        response = _client().post(
            "/api/business/ocr/recognize",
            json={
                "request_id": "ocr-req-1",
                "image_url": "https://example.invalid/label.png",
                "ocr_type": "invoice",
                "user_id": "tenant-a",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["request_id"] == "ocr-req-1"
    assert payload["event"] == "ocr.requested"
    assert payload["published"] is True
    assert payload["agent_run_id"] == payload["run_id"]

    ocr_domain.emit_ocr_requested.assert_called_once_with(
        request_id="ocr-req-1",
        image_url="https://example.invalid/label.png",
        ocr_type="invoice",
        user_id="tenant-a",
    )
    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "business_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"
    assert run.tool_calls[0].permission == "tool.ocr.request"
    assert run.tool_calls[0].cost_units == 1


def test_business_print_label_route_runs_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    print_domain = Mock()
    print_domain.emit_job_submitted.return_value = True
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.neuro_bus.domains.print_domain.get_print_domain", return_value=print_domain),
    ):
        response = _client().post(
            "/api/business/print/label",
            json={
                "job_id": "print-job-1",
                "document_name": "发货标签.pdf",
                "printer_id": "default",
                "copies": 2,
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["job_id"] == "print-job-1"
    assert payload["event"] == "print.job.submitted"
    assert payload["agent_run_id"] == payload["run_id"]
    print_domain.emit_job_submitted.assert_called_once_with(
        job_id="print-job-1",
        document_name="发货标签.pdf",
        printer_id="default",
        copies=2,
    )

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "business_event_print_label"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "business_event"
    assert run.tool_calls[0].action == "print_label"
    assert run.tool_calls[0].permission == "tool.business_event.print_label"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed"} <= {
        event.event_type for event in run.events
    }


def test_business_inventory_update_route_runs_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    inventory_domain = Mock()
    inventory_domain.emit_stock_changed.return_value = True
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.neuro_bus.domains.inventory_domain.get_inventory_domain",
            return_value=inventory_domain,
        ),
    ):
        response = _client().post(
            "/api/business/inventory/update",
            json={
                "product_id": "sku-1",
                "warehouse_id": "main",
                "delta": -2,
                "reason": "shipment",
                "new_quantity": 18,
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["event"] == "inventory.changed"
    inventory_domain.emit_stock_changed.assert_called_once_with(
        product_id="sku-1",
        warehouse_id="main",
        delta=-2,
        reason="shipment",
        new_quantity=18,
    )

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "business_event_inventory_update"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "business_event"
    assert run.tool_calls[0].action == "inventory_update"
    assert run.tool_calls[0].permission == "tool.business_event.inventory_update"
    assert run.tool_calls[0].cost_units == 2


def test_business_shipment_create_route_runs_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event", return_value=True
        ) as publish,
    ):
        response = _client().post(
            "/api/business/shipment/create",
            json={
                "unit_name": "ACME Trading",
                "items": [{"sku": "sku-1", "qty": 2}],
                "contact_person": "Lee",
                "contact_phone": "13800000000",
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["event"] == "shipment.created"
    assert payload["published"] is True
    publish.assert_called_once_with(
        "shipment.created",
        {
            "unit_name": "ACME Trading",
            "items": [{"sku": "sku-1", "qty": 2}],
            "contact_person": "Lee",
            "contact_phone": "13800000000",
        },
        "shipment",
    )

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.intent == "business_event_shipment_create"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "business_event"
    assert run.tool_calls[0].action == "shipment_create"
    assert run.tool_calls[0].permission == "tool.business_event.shipment_create"
    assert run.tool_calls[0].cost_units == 2
