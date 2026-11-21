"""Business transports share real principal, durable approval and request identity."""

from __future__ import annotations

import importlib
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes.tools_execute import router as tools_router
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

_CASES = [
    ("inventory", "POST", "/api/inventory/setup/warehouse", None, "setup_warehouse"),
    ("inventory", "POST", "/api/inventory/locations", {"code": "A-01"}, "create_storage_location"),
    (
        "inventory",
        "PUT",
        "/api/inventory/locations/10",
        {"status": "full"},
        "update_storage_location",
    ),
    ("inventory", "POST", "/api/inventory/warehouses", {"name": "主仓"}, "create_warehouse"),
    ("inventory", "PUT", "/api/inventory/warehouses/3", {"name": "副仓"}, "update_warehouse"),
    ("inventory", "DELETE", "/api/inventory/warehouses/3", None, "delete_warehouse"),
    (
        "inventory",
        "POST",
        "/api/inventory/in",
        {"product_id": 1, "warehouse_id": 2, "quantity": 3},
        "stock_in",
    ),
    (
        "inventory",
        "POST",
        "/api/inventory/out",
        {"product_id": 1, "warehouse_id": 2, "quantity": 1},
        "stock_out",
    ),
    (
        "inventory",
        "POST",
        "/api/inventory/transfer",
        {"product_id": 1, "from_warehouse_id": 2, "to_warehouse_id": 3, "quantity": 1},
        "transfer",
    ),
    (
        "purchase",
        "POST",
        "/api/purchase/suppliers",
        {"name": "供应商", "tenant_id": 999},
        "create_supplier",
    ),
    ("purchase", "PUT", "/api/purchase/suppliers/7", {"status": "active"}, "update_supplier"),
    ("purchase", "DELETE", "/api/purchase/suppliers/7", None, "delete_supplier"),
    ("purchase", "POST", "/api/purchase/orders", {"supplier_id": 7}, "create_order"),
    ("purchase", "PUT", "/api/purchase/orders/9", {"remarks": "updated"}, "update_order"),
    ("purchase", "POST", "/api/purchase/orders/9/approve", None, "approve_order"),
    ("purchase", "POST", "/api/purchase/orders/9/cancel", None, "cancel_order"),
    ("purchase", "POST", "/api/purchase/inbounds", {"order_id": 9}, "create_inbound"),
    (
        "finance",
        "POST",
        "/api/finance/transactions",
        {"transaction_type": "expense", "amount": 128.5},
        "create_transaction",
    ),
    ("finance", "PUT", "/api/finance/transactions/31", {"status": "paid"}, "update_transaction"),
    ("finance", "DELETE", "/api/finance/transactions/31", None, "delete_transaction"),
    ("materials", "POST", "/api/materials", {"name": "树脂", "min_quantity": 12}, "create"),
    ("materials", "PUT", "/api/materials/1", {"name": "树脂 v2"}, "update"),
    ("materials", "DELETE", "/api/materials/1", None, "delete"),
    ("materials", "POST", "/api/materials/batch-delete", {"material_ids": [1, 2]}, "batch_delete"),
    (
        "print_routes",
        "PUT",
        "/api/print/printer-selection",
        {"document_printer": "DocPrinter"},
        "save_printer_selection",
    ),
    ("print_routes", "POST", "/api/print/document", {"file_path": "$file"}, "print_document"),
    (
        "print_routes",
        "POST",
        "/api/print/label",
        {"file_path": "$file", "copies": 2},
        "print_label",
    ),
    ("print_routes", "POST", "/api/print/test", {"printer_name": "DocPrinter"}, "test"),
    (
        "print_routes",
        "POST",
        "/api/print/workflow/label-print/dispatch",
        {"model_number": "M-1", "quantity": 2},
        "workflow_label_dispatch",
    ),
    ("excel_vector", "DELETE", "/api/excel/vector/indexes/index-1", None, "delete"),
    (
        "business_api",
        "POST",
        "/api/business/print/label",
        {"document_name": "document"},
        "print_label",
    ),
    (
        "business_api",
        "POST",
        "/api/business/inventory/update",
        {"product_id": "1", "delta": 2},
        "inventory_update",
    ),
    (
        "business_api",
        "POST",
        "/api/business/shipment/create",
        {"unit_name": "客户"},
        "shipment_create",
    ),
    (
        "knowledge_v1",
        "POST",
        "/api/knowledge/v1/datasets/docs/documents",
        {"source": "policy.txt", "text": "Policy"},
        "ingest_document",
    ),
    (
        "knowledge_v1",
        "POST",
        "/api/knowledge/v1/datasets/docs/versions/rollback",
        {"source": "policy.txt", "target_version": "v1"},
        "rollback_version",
    ),
    (
        "knowledge_v1",
        "POST",
        "/api/knowledge/v1/datasets/docs/index/rebuild",
        {"background": True},
        "rebuild_index",
    ),
    (
        "knowledge_v1",
        "POST",
        "/api/knowledge/v1/datasets/docs/index/rebuild/job-1/cancel",
        None,
        "cancel_rebuild",
    ),
    (
        "knowledge_v1",
        "DELETE",
        "/api/knowledge/v1/datasets/docs/documents/doc-1",
        None,
        "delete_document",
    ),
    (
        "knowledge_v1",
        "POST",
        "/api/knowledge/v1/datasets/docs/documents/doc-1/refresh",
        None,
        "refresh_document",
    ),
    (
        "knowledge_v1",
        "POST",
        "/api/knowledge/v1/datasets/docs/documents/refresh?limit=500",
        None,
        "refresh_documents",
    ),
]


@pytest.mark.parametrize("module,method,path,body,action", _CASES)
def test_business_transports_share_approval_and_replay(
    tmp_path, monkeypatch, trusted_actor, module, method, path, body, action
):
    route = importlib.import_module(f"app.fastapi_routes.{module}")
    tool_id = {
        "print_routes": "print",
        "business_api": "business_event",
        "knowledge_v1": "dataset_rag",
        "excel_vector": "excel_vector_index",
    }.get(module, module)
    global_store = module in {"materials", "excel_vector"} or (
        module == "print_routes"
        and action in {"print_label", "print_document", "workflow_label_dispatch"}
    )
    actor = trusted_actor(
        user_id=7,
        role="admin",
        tenant_id=None if global_store else 7,
        tier="admin" if global_store else "enterprise",
    )
    denied_actor = trusted_actor(user_id=8, role="no-tools", permissions=[])
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
    effects = Mock(side_effect=AssertionError("A pending or denied request must not execute"))
    monkeypatch.setattr(
        "app.domain.shared_services.tools_workflow_dispatch.execute_registered_workflow_tool",
        effects,
    )
    if hasattr(route, "_svc"):
        monkeypatch.setattr(route, "_svc", effects)
    if body and body.get("file_path") == "$file":
        source = tmp_path / "label.pdf"
        source.write_bytes(b"%PDF-1.4")
        body = {**body, "file_path": str(source)}
    app = FastAPI()
    app.include_router(route.router)
    app.include_router(tools_router)
    headers = {**actor.headers, "Idempotency-Key": "business-command", "X-User-Id": "999"}
    with (
        tenant_scope(None),
        TestClient(app, headers=headers, raise_server_exceptions=False) as client,
    ):
        response = client.request(method, path, json=body)
        receipt = response.json()
        if actor.tenant_id is None:
            # Existing approval storage requires a real enterprise owner. Global
            # legacy stores must not invent one or execute without approval.
            assert response.status_code == 403, response.text
            assert receipt["error_code"] == "approval_scope_required"
            assert receipt["execution_status"] == "not_started"
            assert not receipt.get("pending_approval") and not receipt.get("run_id")
            replay = client.request(method, path, json=body)
            assert replay.status_code == 403 and replay.json() == receipt
        else:
            assert response.status_code == 202, response.text
            assert receipt["success"] is False and receipt["pending_approval"] is True
            assert receipt["execution_state"] == "waiting_approval"
            run = repo.get(receipt["run_id"])
            assert run.user_id == "7" and run.status == "waiting_user"
            assert str(run.metadata["runtime_context"].get("tenant_id") or "") == str(
                actor.tenant_id or ""
            )
            assert run.steps[0].tool_id == tool_id and run.steps[0].action == action
            assert not run.tool_calls
            assert "step.approved" not in {event.event_type for event in run.events}
            replay = client.request(method, path, json=body)
            assert replay.status_code == 202, replay.text
            assert replay.json()["deduplicated"] is True
            for key in ("task_id", "run_id", "approval_request_id"):
                assert replay.json()[key] == receipt[key]
            canonical = client.post(
                "/api/tools/execute",
                json={"tool_id": tool_id, "action": action, "params": run.steps[0].params},
            )
            assert canonical.status_code == 202, canonical.text
            assert canonical.json()["run_id"] == receipt["run_id"]
        client.headers.pop("Idempotency-Key")
        missing = client.request(method, path, json=body)
        assert missing.status_code == 400, missing.text
        assert missing.json()["execution_status"] == "not_started"
        client.headers.update({**denied_actor.headers, "Idempotency-Key": "denied"})
        denied = client.request(method, path, json=body)
        assert denied.status_code == 403, denied.text
        client.headers.pop("X-Session-ID")
        anonymous = client.request(method, path, json=body)
        assert anonymous.status_code == 401, anonymous.text
    effects.assert_not_called()


def test_business_api_gateway_key_cannot_supply_actor(monkeypatch):
    from app.fastapi_routes.business_api import router

    monkeypatch.setenv("FHD_BUSINESS_API_KEY", "gateway-only")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/business/ocr/recognize",
            headers={"X-FHD-Business-Key": "gateway-only", "X-User-Id": "1"},
            json={"request_id": "ocr-1", "image_url": "file.png", "user_id": "1"},
        )
    assert response.status_code == 401


def test_material_batch_failure_never_claims_deleted_records(monkeypatch):
    from app.domain.shared_services.tools_workflow_erp_master import _registered_router_materials

    service = Mock()
    service.batch_delete_materials.side_effect = RuntimeError("partial write; private details")
    monkeypatch.setattr("app.application.get_material_application_service", lambda: service)
    result = _registered_router_materials("batch_delete", {"ids": [1, 2]}, {}, "", "")
    assert result["success"] is False
    assert result["execution_state"] == "unknown"
    assert result["retryable"] is False and result["reconciliation_required"] is True
    assert "deleted_count" not in result and "warning" not in result
    service.batch_delete_materials.assert_called_once_with([1, 2])
