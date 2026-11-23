"""COVERAGE_RAMP Phase 54: inventory, materials, customer, purchase,
operations, reports, ai_assistant route gaps (mocked TestClient)."""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import ai_assistant as ai_routes_mod
from app.fastapi_routes import inventory as inventory_routes
from app.fastapi_routes import materials as materials_routes
from app.fastapi_routes import operations_line_api as ops_routes
from app.fastapi_routes import purchase as purchase_routes
from app.fastapi_routes import reports as report_routes
from app.fastapi_routes.domains.customer import routes as customer_compat_router
from app.fastapi_routes.domains.customer import routes as customer_routes
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

# ---------------------------------------------------------------------------
# Global intent mocks (avoid Bert / unified recognizer hangs on import paths)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_intent_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_clf = MagicMock()
    mock_clf.is_available.return_value = False
    mock_clf.predict.return_value = {"intent": "unknown", "text": ""}
    mock_clf.predict_batch.return_value = []
    monkeypatch.setattr(
        "app.application.facades.intent_facade.BertIntentClassifier",
        lambda *a, **k: mock_clf,
    )
    mock_rec = MagicMock()
    mock_rec.recognize.return_value = []
    monkeypatch.setattr(
        "app.domain.shared_services.unified_intent_recognizer.get_unified_intent_recognizer",
        lambda: mock_rec,
    )


# ---------------------------------------------------------------------------
# Shared mock services (import-site patching)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_inventory_svc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    svc.get_inventory.return_value = {"success": True, "data": [], "total": 0}
    svc.get_inventory_summary.return_value = {"success": True, "total_qty": 100}
    svc.get_inventory_transactions.return_value = {"success": True, "data": []}
    svc.get_inventory_alert.return_value = {"success": True, "data": [{"id": 1}]}
    svc.get_storage_locations.return_value = {"success": True, "data": [{"id": 10}]}
    svc.create_storage_location.return_value = {"success": True, "id": 11}
    svc.update_storage_location.return_value = {"success": True}
    svc.get_warehouses.return_value = {"success": True, "data": []}
    svc.get_warehouse.return_value = {"success": True, "data": {"id": 3}}
    svc.create_warehouse.return_value = {"success": True}
    svc.update_warehouse.return_value = {"success": True}
    svc.delete_warehouse.return_value = {"success": True}
    svc.inventory_in.return_value = {"success": True}
    svc.inventory_out.return_value = {"success": True}
    svc.inventory_transfer.return_value = {"success": True}
    svc.parse_optional_datetime = lambda v: v

    def _inventory_svc():
        from app.application.inventory_app_service import InventoryAppService

        inst = InventoryAppService.__new__(InventoryAppService)
        inst._facade = svc
        return inst

    monkeypatch.setattr(
        "app.application.facades.inventory_facade.InventoryService",
        MagicMock(return_value=svc),
    )
    monkeypatch.setattr(inventory_routes, "_svc", _inventory_svc)
    return svc


@pytest.fixture
def mock_purchase_svc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    svc.get_suppliers.return_value = {"success": True, "data": []}
    svc.get_supplier_summary.return_value = {"success": True}
    svc.get_supplier.return_value = {"success": True, "data": {"id": 1}}
    svc.create_supplier.return_value = {"success": True}
    svc.update_supplier.return_value = {"success": True}
    svc.delete_supplier.return_value = {"success": True}
    svc.get_purchase_orders.return_value = {"success": True, "data": []}
    svc.get_purchase_order.return_value = {"success": True, "data": {"id": 9}}
    svc.create_purchase_order.return_value = {"success": True}
    svc.update_purchase_order.return_value = {"success": True}
    svc.approve_purchase_order.return_value = {"success": True}
    svc.cancel_purchase_order.return_value = {"success": True}
    svc.get_purchase_inbounds.return_value = {"success": True, "data": []}
    svc.create_purchase_inbound.return_value = {"success": True}
    svc.get_purchase_summary.return_value = {"success": True, "total": 0}
    monkeypatch.setattr(
        "app.application.facades.inventory_facade.PurchaseService",
        MagicMock(return_value=svc),
    )
    return svc


@pytest.fixture
def mock_report_svc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    svc.get_sales_report.return_value = {"success": True, "rows": []}
    svc.get_inventory_report.return_value = {"success": True, "data": []}
    svc.get_inventory_transaction_report.return_value = {"success": True, "data": []}
    svc.get_purchase_report.return_value = {"success": True, "data": []}
    svc.get_dashboard_summary.return_value = {"success": True, "revenue": 0}
    svc.export_to_excel.return_value = {"success": True, "file_path": "/tmp/r54.xlsx"}
    monkeypatch.setattr(
        "app.application.facades.inventory_facade.ReportService",
        MagicMock(return_value=svc),
    )
    return svc


@pytest.fixture
def mock_material_svc() -> MagicMock:
    svc = MagicMock()
    svc.create_material.return_value = {
        "success": True,
        "data": {"id": 54, "name": "铜线"},
    }
    svc.get_all_materials.return_value = {
        "success": True,
        "data": [{"id": 54, "name": "铜线"}],
    }
    svc.update_material.return_value = {"success": True, "data": {"id": 54}}
    svc.delete_material.return_value = None
    svc.batch_delete_materials.return_value = None
    svc.get_low_stock_materials.return_value = {"success": True, "data": [], "count": 0}
    svc.export_to_excel.return_value = {"success": False, "message": "empty"}
    return svc


@pytest.fixture
def capability_runs(monkeypatch):
    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repository,
    )
    return repository


@pytest.fixture
def inventory_client(
    mock_inventory_svc: MagicMock, trusted_actor, request, capability_runs
) -> TestClient:
    app = FastAPI()
    app.include_router(inventory_routes.router)
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={
            **trusted_actor(role="admin").headers,
            "Idempotency-Key": request.node.name,
        },
    )


@pytest.fixture
def materials_client(mock_material_svc: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        materials_routes,
        "get_material_application_service",
        lambda: mock_material_svc,
    )
    app = FastAPI()
    app.include_router(materials_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def purchase_client(
    mock_purchase_svc: MagicMock, trusted_actor, request, capability_runs
) -> TestClient:
    app = FastAPI()
    app.include_router(purchase_routes.router)
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={
            **trusted_actor(role="admin").headers,
            "Idempotency-Key": request.node.name,
        },
    )


@pytest.fixture
def report_client(mock_report_svc: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(report_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def ops_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.domain.shared_services.operations_line_bridge.compute_operations_health",
        lambda: {"status": "ok", "checks": []},
    )
    monkeypatch.setattr(
        "app.domain.shared_services.contract_lifecycle.run_contract_expiry_scan",
        lambda **kwargs: {"scanned": 2, "expiring": 0, **kwargs},
    )
    monkeypatch.setattr(
        "app.domain.shared_services.user_cs_delivery_signoff.signoff_backend_info",
        lambda: {"enabled": True},
    )
    monkeypatch.setattr(
        "app.domain.shared_services.reconciliation_scheduler.get_reconciliation_status",
        lambda: {"last_run": "2026-06-01", "success": True},
    )
    app = FastAPI()
    app.include_router(ops_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def customer_client(monkeypatch: pytest.MonkeyPatch, request, capability_runs) -> TestClient:
    actor = None
    if any(action in request.node.name for action in ("create", "update", "delete")):
        actor = request.getfixturevalue("trusted_actor")(tenant_id=7, role="admin")
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setattr(
        customer_routes,
        "_load_customers_rows",
        lambda: [
            {"id": 1, "unit_name": "七彩乐园", "contact_phone": "13800001111"},
            {"id": 2, "unit_name": "蓝天工厂", "address": "杭州"},
        ],
    )
    monkeypatch.setattr(customer_routes, "_business_mod_json_block", lambda: False)
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda _req: None,
    )
    monkeypatch.setattr(
        "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.try_invoke_client_mod_customers_list",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
        lambda *a, **k: None,
    )
    app = FastAPI()
    app.include_router(customer_compat_router.router)
    return TestClient(
        app,
        headers={
            **(actor.headers if actor else {}),
            "Idempotency-Key": request.node.name,
        },
        raise_server_exceptions=False,
    )


@pytest.fixture
def ai_client() -> TestClient:
    app = FastAPI()
    from app.fastapi_routes.mounts.health import register_health_routes

    register_health_routes(app)
    app.include_router(ai_routes_mod.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# inventory.py — combined-alert, alias paths, validation
# ---------------------------------------------------------------------------


def test_inventory_summary_with_warehouse(
    inventory_client: TestClient, mock_inventory_svc: MagicMock
) -> None:
    r = inventory_client.get("/api/inventory/summary", params={"warehouse_id": 2})
    assert r.status_code == 200
    mock_inventory_svc.get_inventory_summary.assert_called_once_with(warehouse_id=2)


def test_inventory_transactions_with_iso_dates(
    inventory_client: TestClient, mock_inventory_svc: MagicMock
) -> None:
    r = inventory_client.get(
        "/api/inventory/transactions",
        params={
            "start_date": "2026-05-01",
            "end_date": "2026-06-01",
            "transaction_type": "in",
            "product_id": 5,
        },
    )
    assert r.status_code == 200
    kwargs = mock_inventory_svc.get_inventory_transactions.call_args.kwargs
    assert kwargs["transaction_type"] == "in"
    assert kwargs["product_id"] == 5


def test_inventory_alert_primary_and_alias(
    inventory_client: TestClient, mock_inventory_svc: MagicMock
) -> None:
    assert inventory_client.get("/api/inventory/inventory/alert").status_code == 200
    assert inventory_client.get("/api/inventory/alert").status_code == 200
    assert mock_inventory_svc.get_inventory_alert.call_count == 2


def test_inventory_combined_alert_merges_materials(
    inventory_client: TestClient,
    mock_inventory_svc: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_inventory_svc.get_inventory_alert.return_value = {
        "success": True,
        "alerts": [{"sku": "A1"}],
    }
    mat_svc = MagicMock()
    mat_svc.get_low_stock_materials.return_value = {
        "success": True,
        "data": [{"id": 3, "name": "树脂"}],
    }
    monkeypatch.setattr(
        "app.application.get_material_application_service",
        lambda: mat_svc,
    )
    body = inventory_client.get("/api/inventory/combined-alert", params={"threshold": 10}).json()
    assert body["success"] is True
    assert len(body["inventory_alerts"]) == 1
    assert len(body["material_low_stock"]) == 1
    assert body["total_alerts"] == 2


def test_inventory_combined_alert_materials_exception(
    inventory_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.application.get_material_application_service",
        lambda: (_ for _ in ()).throw(RuntimeError("materials down")),
    )
    body = inventory_client.get("/api/inventory/combined-alert").json()
    assert body["success"] is True
    assert body["material_low_stock"] == []


def test_inventory_locations_missing_warehouse(inventory_client: TestClient) -> None:
    r = inventory_client.get("/api/inventory/locations")
    assert r.status_code == 200
    assert r.json()["success"] is False


def test_inventory_locations_crud(
    inventory_client: TestClient, mock_inventory_svc: MagicMock
) -> None:
    listed = inventory_client.get(
        "/api/inventory/locations",
        params={"warehouse_id": 1, "status": "active"},
    )
    assert listed.status_code == 200
    for method, path, data in (
        ("POST", "/api/inventory/locations", {"code": "A-01"}),
        ("PUT", "/api/inventory/locations/10", {"status": "full"}),
    ):
        response = inventory_client.request(
            method, path, json=data, headers={"Idempotency-Key": f"locations-{method}"}
        )
        assert response.status_code == 202, response.text
        assert response.json()["success"] is False and response.json()["approval_request_id"]
    mock_inventory_svc.create_storage_location.assert_not_called()
    mock_inventory_svc.update_storage_location.assert_not_called()
    mock_inventory_svc.get_storage_locations.assert_called_once_with(
        warehouse_id=1, status="active"
    )


def test_inventory_warehouses_lifecycle(
    inventory_client: TestClient, mock_inventory_svc: MagicMock
) -> None:
    assert (
        inventory_client.get("/api/inventory/warehouses", params={"status": "active"}).status_code
        == 200
    )
    assert inventory_client.get("/api/inventory/warehouses/3").status_code == 200
    for method, path, data in (
        ("POST", "/api/inventory/warehouses", {"name": "主仓"}),
        ("PUT", "/api/inventory/warehouses/3", {"name": "副仓"}),
        ("DELETE", "/api/inventory/warehouses/3", None),
    ):
        response = inventory_client.request(
            method, path, json=data, headers={"Idempotency-Key": f"warehouses-{method}"}
        )
        assert response.status_code == 202, response.text
        assert response.json()["success"] is False and response.json()["approval_request_id"]
    mock_inventory_svc.create_warehouse.assert_not_called()
    mock_inventory_svc.update_warehouse.assert_not_called()
    mock_inventory_svc.delete_warehouse.assert_not_called()


def test_inventory_in_without_unit_price(
    inventory_client: TestClient,
    mock_inventory_svc: MagicMock,
    local_tools,
    capability_runs,
) -> None:
    r = inventory_client.post(
        "/api/inventory/in",
        json={"product_id": 1, "warehouse_id": 2, "quantity": 3},
    )
    assert r.status_code == 202, r.text
    assert r.json()["success"] is False and r.json()["approval_request_id"]
    assert capability_runs.get(r.json()["run_id"]).steps[0].params["unit_price"] is None
    mock_inventory_svc.inventory_in.assert_not_called()


# ---------------------------------------------------------------------------
# materials.py — validation, export, batch-delete edge cases
# ---------------------------------------------------------------------------


def test_materials_create_missing_name_400(materials_client: TestClient) -> None:
    assert materials_client.post("/api/materials", json={}).status_code == 400
    assert materials_client.post("/api/materials", json={"name": ""}).status_code == 400


def test_materials_create_maps_min_quantity(
    materials_client: TestClient, mock_material_svc: MagicMock, monkeypatch
) -> None:
    admission = MagicMock(
        return_value=({"success": False, "execution_state": "waiting_approval"}, 202)
    )
    monkeypatch.setattr(materials_routes, "_run_materials_agent", admission)
    r = materials_client.post(
        "/api/materials",
        json={"name": "树脂", "min_quantity": 12, "material_code": "R-54"},
    )
    assert r.status_code == 202
    payload = admission.call_args.kwargs["params"]
    assert payload["min_stock"] == 12
    mock_material_svc.create_material.assert_not_called()


def test_materials_create_requires_session_before_service_failure(
    materials_client: TestClient, mock_material_svc: MagicMock, local_tools
) -> None:
    mock_material_svc.create_material.return_value = {
        "success": False,
        "message": "duplicate",
    }
    r = materials_client.post("/api/materials", json={"name": "重复项"})
    assert r.status_code == 401
    mock_material_svc.create_material.assert_not_called()


def test_materials_create_requires_session_before_service_exception(
    materials_client: TestClient, mock_material_svc: MagicMock, local_tools
) -> None:
    mock_material_svc.create_material.side_effect = RuntimeError("db locked")
    r = materials_client.post("/api/materials", json={"name": "异常项"})
    assert r.status_code == 401
    mock_material_svc.create_material.assert_not_called()


def test_materials_list_injects_count(
    materials_client: TestClient, mock_material_svc: MagicMock
) -> None:
    mock_material_svc.get_all_materials.return_value = {
        "success": True,
        "data": [{"id": 1}, {"id": 2}],
    }
    body = materials_client.get(
        "/api/materials", params={"search": "铜", "category": "金属"}
    ).json()
    assert body["count"] == 2


def test_materials_batch_delete_non_dict_400(materials_client: TestClient) -> None:
    r = materials_client.post("/api/materials/batch-delete", content=b"not-json")
    assert r.status_code == 422 or r.status_code == 400


def test_materials_batch_delete_adapter_never_reports_partial_exception_as_success(
    monkeypatch, mock_material_svc: MagicMock
) -> None:
    from app.domain.shared_services.tools_workflow_erp_master import (
        _registered_router_materials,
    )

    monkeypatch.setattr(
        "app.application.get_material_application_service", lambda: mock_material_svc
    )
    mock_material_svc.batch_delete_materials.side_effect = RuntimeError("partial fail")
    result = _registered_router_materials("batch_delete", {"ids": [1, 2]}, {}, "test", "")
    assert result["success"] is False and result["execution_state"] == "unknown"
    assert result["outcome"] == "unknown"
    assert result["error_code"] == "material_delete_outcome_unknown"
    assert result["retryable"] is False and result["reconciliation_required"] is True
    assert "deleted_count" not in result
    mock_material_svc.batch_delete_materials.assert_called_once_with([1, 2])


def test_materials_export_file_success(
    materials_client: TestClient, mock_material_svc: MagicMock
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(b"xlsx-bytes")
        tmp_path = tmp.name
    try:
        mock_material_svc.export_to_excel.return_value = {
            "success": True,
            "file_path": tmp_path,
            "filename": "materials-p54.xlsx",
        }
        r = materials_client.get("/api/materials/export", params={"search": "铜"})
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers.get("content-type", "")
    finally:
        os.unlink(tmp_path)


def test_materials_low_stock_threshold(
    materials_client: TestClient, mock_material_svc: MagicMock
) -> None:
    r = materials_client.get("/api/materials/low-stock", params={"threshold": 8})
    assert r.status_code == 200
    mock_material_svc.get_low_stock_materials.assert_called_once_with(threshold=8.0)


# ---------------------------------------------------------------------------
# xcagi_compat_customer.py — list, match, CRUD gaps
# ---------------------------------------------------------------------------


def test_customers_list_keyword_filter(customer_client: TestClient) -> None:
    body = customer_client.get(
        "/customers/list",
        params={"keyword": "七彩", "page": 1, "per_page": 10},
    ).json()
    assert body["success"] is True
    assert body["total"] == 1
    assert body["data"][0]["unit_name"] == "七彩乐园"


def test_customers_list_schema_hint_when_empty(
    customer_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(customer_routes, "_load_customers_rows", lambda: [])
    monkeypatch.setattr(
        customer_routes,
        "_customers_schema_hint_if_empty",
        lambda: "当前库缺少 customers 表",
    )
    body = customer_client.get("/customers/list", params={"keyword": "none"}).json()
    assert body["total"] == 0
    assert "customers" in body["schema_hint"]


def test_customers_match_field_only(
    customer_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.products.customer_matching.extract_customer_name",
        lambda s: None,
    )
    monkeypatch.setattr(
        "app.infrastructure.products.customer_matching.find_matching_customer",
        lambda s: "蓝天工厂" if "蓝天" in s else "",
    )
    body = customer_client.get("/customers/match", params={"customer_name": "蓝天"}).json()
    assert body["matched"] == "蓝天工厂"
    assert body["extracted"] is None


def test_customers_create_empty_name_400(customer_client: TestClient) -> None:
    with (
        patch.object(
            customer_routes,
            "_customer_body_name_contact",
            return_value=("", "", "", ""),
        ),
    ):
        r = customer_client.post("/customers", json={"unit_name": ""})
    assert r.status_code == 400


def test_customers_update_normalizes_fields_for_the_shared_entry(monkeypatch) -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "method": "PUT", "path": "/customers/1", "headers": []})
    entry = MagicMock(return_value=({"success": False, "state": "waiting_approval"}, 202))
    monkeypatch.setattr(customer_routes, "_run_customers_agent", entry)
    response = customer_routes.customers_update(
        request,
        1,
        {
            "unit_name": "新名称",
            "contact_person": "张三",
            "contact_phone": "",
            "address": "上海",
        },
    )
    assert response.status_code == 202
    entry.assert_called_once_with(
        request=request,
        action="update",
        route_path="/customers/{customer_id}",
        params={
            "id": 1,
            "customer_name": "新名称",
            "unit_name": "新名称",
            "contact_person": "张三",
            "contact_phone": "",
            "contact_address": "上海",
        },
    )


@pytest.fixture
def approved_owned_customers(monkeypatch, tmp_path, trusted_actor, capability_runs, local_tools):
    """Use real owned rows and grants across the HTTP/canonical capability boundary."""
    actor = trusted_actor(tenant_id=7, role="admin")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "customer-claims.sqlite"))
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", actor.factory)
    app = FastAPI()
    app.state.agent_runs = capability_runs
    app.include_router(customer_routes.router)
    raw_client = TestClient(app, raise_server_exceptions=False)
    return (
        ApprovedCapabilityClient(raw_client, capability_runs, actor),
        actor,
        capability_runs,
    )


def test_customers_create_owned_row_after_approval_and_read_original_receipt(
    approved_owned_customers,
) -> None:
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    client, actor, repository = approved_owned_customers
    body = {"unit_name": "Owned customer", "contact_phone": "13900000000"}
    headers = {"Idempotency-Key": "owned-customer-create"}
    response = client.post("/customers", json=body, headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["success"] is True
    run = repository.get(receipt["run_id"])
    assert run.status == "completed" and len(run.tool_calls) == 1
    assert run.tool_calls[0].metadata["verification"]["accepted"] is True
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        row = db.query(PurchaseUnit).filter_by(unit_name="Owned customer").one()
        assert row.tenant_id == actor.tenant_id
        assert row.contact_phone == body["contact_phone"]
        customer_id = row.id
    repeated = client.post("/customers", json=body, headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["run_id"] == run.run_id
    assert len(repository.get(run.run_id).tool_calls) == 1
    conflict = client.post("/customers", json={**body, "contact_phone": "changed"}, headers=headers)
    assert conflict.status_code == 409, conflict.text
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(PurchaseUnit).filter_by(unit_name="Owned customer").count() == 1
        assert db.get(PurchaseUnit, customer_id).contact_phone == body["contact_phone"]


def test_customers_update_owned_row_preserves_version_and_foreign_rows(
    approved_owned_customers,
) -> None:
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    client, actor, repository = approved_owned_customers
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        owned = PurchaseUnit(tenant_id=actor.tenant_id, unit_name="Owned before")
        db.add(owned)
        db.flush()
        owned_id, original_version = owned.id, owned.version
    with tenant_scope(actor.tenant_id + 1), actor.factory.begin() as db:
        foreign = PurchaseUnit(tenant_id=actor.tenant_id + 1, unit_name="Foreign before")
        db.add(foreign)
        db.flush()
        foreign_id = foreign.id
    body = {"unit_name": "Owned after", "expected_version": original_version}
    headers = {"Idempotency-Key": "owned-customer-update"}
    response = client.put(f"/customers/{owned_id}", json=body, headers=headers)
    assert response.status_code == 200, response.text
    run = repository.get(response.json()["run_id"])
    assert run.steps[0].params["expected_version"] == original_version
    assert run.status == "completed" and len(run.tool_calls) == 1
    assert run.tool_calls[0].metadata["verification"]["accepted"] is True
    repeated = client.put(f"/customers/{owned_id}", json=body, headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["run_id"] == run.run_id
    stale = client.put(
        f"/customers/{owned_id}",
        json={"unit_name": "Stale overwrite", "expected_version": original_version},
        headers={"Idempotency-Key": "owned-stale-update"},
    )
    assert stale.status_code == 202, stale.text
    assert stale.json()["success"] is False
    assert stale.json()["error_code"] == "version_conflict"
    assert stale.json()["retryable"] is False
    foreign_response = client.put(
        f"/customers/{foreign_id}",
        json={"unit_name": "Foreign overwrite", "expected_version": original_version},
        headers={"Idempotency-Key": "owned-foreign-update"},
    )
    assert foreign_response.status_code == 202, foreign_response.text
    assert foreign_response.json()["success"] is False
    assert foreign_response.json()["retryable"] is False
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        saved = db.get(PurchaseUnit, owned_id)
        assert saved.unit_name == "Owned after" and saved.version == original_version + 1
    with tenant_scope(actor.tenant_id + 1), actor.factory() as db:
        assert db.get(PurchaseUnit, foreign_id).unit_name == "Foreign before"
    assert len(repository.get(run.run_id).tool_calls) == 1


def test_customers_delete_default_path(
    customer_client: TestClient, local_tools, trusted_actor
) -> None:
    actor = trusted_actor(tenant_id=7, role="admin")
    customer_client.headers.update(actor.headers)
    service = MagicMock()
    service.batch_delete.return_value = {
        "success": True,
        "deleted_count": 1,
        "message": "已删除",
    }
    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=False,
        ),
        patch("app.application.get_customer_app_service", return_value=service),
    ):
        r = customer_client.delete("/customers/2")
    assert r.status_code == 202, r.text
    assert r.json()["success"] is False and r.json()["approval_request_id"]
    service.batch_delete.assert_not_called()


def test_customers_batch_delete_rejects_invalid_atomically(
    customer_client: TestClient, local_tools, trusted_actor
) -> None:
    actor = trusted_actor(tenant_id=7, role="admin")
    customer_client.headers.update(actor.headers)
    service = MagicMock()
    with (
        patch("app.application.get_customer_app_service", return_value=service),
    ):
        body = customer_client.post(
            "/customers/batch-delete",
            json={"ids": [1, "bad", 2]},
        ).json()
    assert body["success"] is False
    assert body.get("deleted_count", 0) == 0
    service.batch_delete.assert_not_called()


def test_customers_batch_delete_empty_ids_400(customer_client: TestClient) -> None:
    r = customer_client.post("/customers/batch-delete", json={"ids": []})
    assert r.status_code == 400


def test_customers_get_via_service_enabled(customer_client: TestClient) -> None:
    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=True,
        ),
        patch(
            "app.mod_sdk.erp_customers_facade.customers_get",
            return_value={"success": True, "data": {"id": 9, "unit_name": "服务客户"}},
        ) as get_via,
    ):
        r = customer_client.get("/customers/9")
    assert r.status_code == 200
    assert r.json()["data"]["unit_name"] == "服务客户"
    get_via.assert_called_once()


# ---------------------------------------------------------------------------
# purchase.py — filter params
# ---------------------------------------------------------------------------


def test_purchase_orders_supplier_and_status_filters(
    purchase_client: TestClient, mock_purchase_svc: MagicMock
) -> None:
    r = purchase_client.get(
        "/api/purchase/orders",
        params={
            "supplier_id": 4,
            "status": "approved",
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "page": 2,
            "per_page": 10,
        },
    )
    assert r.status_code == 200
    kwargs = mock_purchase_svc.get_purchase_orders.call_args.kwargs
    assert kwargs["supplier_id"] == 4
    assert kwargs["status"] == "approved"


def test_purchase_inbounds_order_filter(
    purchase_client: TestClient, mock_purchase_svc: MagicMock
) -> None:
    r = purchase_client.get(
        "/api/purchase/inbounds",
        params={"order_id": 7, "supplier_id": 2},
    )
    assert r.status_code == 200
    kwargs = mock_purchase_svc.get_purchase_inbounds.call_args.kwargs
    assert kwargs["order_id"] == 7
    assert kwargs["supplier_id"] == 2


def test_purchase_approve_custom_approver(
    purchase_client: TestClient,
    mock_purchase_svc: MagicMock,
    local_tools,
    capability_runs,
    trusted_actor,
) -> None:
    actor = trusted_actor(role="admin")
    purchase_client.headers.update(actor.headers)
    r = purchase_client.post(
        "/api/purchase/orders/5/approve",
        params={"approver": "manager-p54"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["success"] is False and r.json()["approval_request_id"]
    assert capability_runs.get(r.json()["run_id"]).steps[0].params["approver"] == "manager-p54"
    mock_purchase_svc.approve_purchase_order.assert_not_called()


# ---------------------------------------------------------------------------
# operations_line_api.py — reconciliation branches
# ---------------------------------------------------------------------------


def test_operations_health_payload(ops_client: TestClient) -> None:
    body = ops_client.get("/api/operations-line/health").json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


def test_operations_contract_scan_expiry_params(ops_client: TestClient) -> None:
    body = ops_client.post(
        "/api/operations-line/contracts/scan-expiry",
        params={"days_ahead": 7, "dry_run": False},
    ).json()
    assert body["success"] is True
    assert body["data"]["dry_run"] is False


def test_operations_reconciliation_run_preview(
    ops_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.domain.shared_services.reconciliation_scheduler.run_reconciliation_preview_cycle",
        lambda: {"success": True, "mode": "preview"},
    )
    body = ops_client.post(
        "/api/operations-line/reconciliation/run",
        params={"dry_run": True},
    ).json()
    assert body["success"] is True
    assert body["data"]["mode"] == "preview"


def test_operations_reconciliation_run_failure(
    ops_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.domain.shared_services.reconciliation_scheduler.run_reconciliation_full_cycle",
        lambda: {"success": False, "error": "ledger mismatch"},
    )
    body = ops_client.post(
        "/api/operations-line/reconciliation/run",
        params={"dry_run": False},
    ).json()
    assert body["success"] is False
    assert body["data"]["error"] == "ledger mismatch"


# ---------------------------------------------------------------------------
# reports.py — filter params
# ---------------------------------------------------------------------------


def test_report_sales_customer_filter(
    report_client: TestClient, mock_report_svc: MagicMock
) -> None:
    r = report_client.get(
        "/api/report/sales",
        params={"customer_id": 12, "group_by": "customer"},
    )
    assert r.status_code == 200
    kwargs = mock_report_svc.get_sales_report.call_args.kwargs
    assert kwargs["customer_id"] == 12
    assert kwargs["group_by"] == "customer"


def test_report_inventory_category(report_client: TestClient, mock_report_svc: MagicMock) -> None:
    r = report_client.get(
        "/api/report/inventory",
        params={"warehouse_id": 1, "category": "raw"},
    )
    assert r.status_code == 200
    mock_report_svc.get_inventory_report.assert_called_once_with(warehouse_id=1, category="raw")


def test_report_inventory_transactions_filters(
    report_client: TestClient, mock_report_svc: MagicMock
) -> None:
    r = report_client.get(
        "/api/report/inventory/transactions",
        params={
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
            "transaction_type": "out",
            "product_id": 8,
        },
    )
    assert r.status_code == 200
    kwargs = mock_report_svc.get_inventory_transaction_report.call_args.kwargs
    assert kwargs["transaction_type"] == "out"
    assert kwargs["product_id"] == 8


def test_report_purchase_date_range(report_client: TestClient, mock_report_svc: MagicMock) -> None:
    r = report_client.get(
        "/api/report/purchase",
        params={
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "group_by": "month",
        },
    )
    assert r.status_code == 200
    assert mock_report_svc.get_purchase_report.call_args.kwargs["group_by"] == "month"


def test_report_export_defaults(report_client: TestClient, mock_report_svc: MagicMock) -> None:
    r = report_client.post("/api/report/export", json={})
    assert r.status_code == 200
    mock_report_svc.export_to_excel.assert_called_once_with(
        report_type="report",
        data=[],
        filename="report",
    )


def test_report_export_returns_xlsx_download(
    report_client: TestClient, mock_report_svc: MagicMock
) -> None:
    mock_report_svc.export_to_excel.return_value = {
        "success": True,
        "data": b"xlsx-bytes",
        "filename": "probe.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    r = report_client.post("/api/report/export", json={"filename": "probe"})

    assert r.status_code == 200
    assert r.content == b"xlsx-bytes"
    assert (
        r.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert r.headers["content-disposition"] == 'attachment; filename="probe.xlsx"'


# ---------------------------------------------------------------------------
# ai_assistant.py — remaining branches
# ---------------------------------------------------------------------------


def test_ai_compat_health_root_and_api(ai_client: TestClient) -> None:
    compat = ai_client.get("/health")
    assert compat.status_code == 200
    body = compat.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["build"] == body["data"]["build"]
    canonical = ai_client.get("/api/health?lite=true")
    assert canonical.status_code == 200
    health = canonical.json()
    assert health["service"] == "xcagi-fastapi"
    assert health["status"] == health["runtime"]["status"]
    assert health["git_sha"] == health["build"]["git_sha"]
    assert health["release_id"] == health["build"]["release_id"]
    assert "no-store" in canonical.headers["cache-control"]
    from app.legacy.routes.openapi_route_compat import iter_effective_routes

    paths = [r.path for r in iter_effective_routes(ai_client.app.routes)]
    assert paths.count("/api/health") == 1
    assert paths.count("/health") == 1


def test_ai_generate_with_template_name(
    ai_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = MagicMock()
    svc.generate_shipment_document.return_value = {
        "success": True,
        "file_path": "/tmp/p54.docx",
        "doc_name": "p54.docx",
    }
    monkeypatch.setattr(ai_routes_mod, "_shipment_svc", lambda: svc)
    monkeypatch.setattr(
        "app.application.facades.tools_facade._parse_order_text",
        lambda _t: {
            "success": True,
            "unit_name": "七彩乐园",
            "products": [{"model_number": "9803", "quantity": 1}],
        },
    )
    r = ai_client.post(
        "/api/generate",
        json={"order_text": "七彩乐园 9803", "template_name": "default.docx"},
    )
    assert r.status_code == 200
    svc.generate_shipment_document.assert_called_once()
    assert svc.generate_shipment_document.call_args.kwargs["template_name"] == "default.docx"


def test_ai_single_label_success(ai_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    product_svc = MagicMock()
    product_svc.search_products.return_value = [
        {"name": "底漆", "specification": "25kg", "unit": "桶"},
    ]
    print_app = MagicMock()
    print_app.print_single_label.return_value = {"success": True, "message": "printed"}
    monkeypatch.setattr("app.application.get_product_app_service", lambda: product_svc)
    monkeypatch.setattr(
        "app.application.print_app_service.get_print_application_service",
        lambda: print_app,
    )
    r = ai_client.post("/api/print/single_label", json={"model_number": "9803", "quantity": 2})
    assert r.status_code == 200
    print_app.print_single_label.assert_called_once()


def test_ai_single_label_product_lookup_fail(
    ai_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.application.get_product_app_service",
        lambda: (_ for _ in ()).throw(RuntimeError("product svc down")),
    )
    print_app = MagicMock()
    print_app.print_single_label.return_value = {"success": True}
    monkeypatch.setattr(
        "app.application.print_app_service.get_print_application_service",
        lambda: print_app,
    )
    r = ai_client.post("/api/print/single_label", json={"model_number": "X99", "quantity": 0})
    assert r.status_code == 200
    assert print_app.print_single_label.call_args.kwargs["quantity"] == 1


def test_ai_print_file_failure(
    ai_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    out_dir = tmp_path / "shipment_outputs"
    out_dir.mkdir()
    (out_dir / "fail.docx").write_bytes(b"doc")
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    printer = MagicMock()
    printer.print_document.return_value = {"success": False, "message": "offline"}
    monkeypatch.setattr(ai_routes_mod, "_printer_svc", lambda: printer)
    r = ai_client.post("/api/print/fail.docx", json={"printer_name": "HP"})
    assert r.status_code == 400
    assert r.json()["message"] == "打印服务暂时不可用，请稍后重试"
    assert "offline" not in r.text


def test_ai_print_pdf_labels_501(ai_client: TestClient) -> None:
    r = ai_client.post("/api/print/pdf_labels")
    assert r.status_code == 501


def test_ai_tts_success(ai_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_TTS_PLATFORM_ONLY", "0")
    monkeypatch.setattr(
        "app.application.facades.tts_facade.synthesize_to_data_uri",
        lambda **kwargs: {
            "audioBase64": "data:audio/mpeg;base64,UDU0",
            "voice": "zh-CN-female",
            "lang": "zh",
        },
    )
    monkeypatch.setattr(
        "app.application.facades.tts_facade.trigger_common_tts_warmup",
        lambda: None,
    )
    r = ai_client.post(
        "/api/tts",
        json={"text": "测试语音", "speakerId": "1", "rate": "+0%", "pitch": "+0Hz"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["audioBase64"] == "data:audio/mpeg;base64,UDU0"


def test_ai_tts_fallback_on_error(ai_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_TTS_PLATFORM_ONLY", "0")
    monkeypatch.setattr(
        "app.application.facades.tts_facade.trigger_common_tts_warmup",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.application.facades.tts_facade.synthesize_to_data_uri",
        lambda **kwargs: (_ for _ in ()).throw(ConnectionError("edge offline")),
    )
    r = ai_client.post("/api/tts", json={"text": "回退测试"})
    assert r.status_code == 502
    assert r.json()["success"] is False
    assert "MiMo" in r.json()["message"] or "Edge" in r.json()["message"]


def test_ai_purchase_units_create_name_alias(
    ai_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit_row = SimpleNamespace(
        id=54,
        unit_name="别名单位",
        contact_person="",
        contact_phone="",
        address="",
    )
    monkeypatch.setattr(
        "app.application.facades.query_facade.find_purchase_unit",
        lambda **kwargs: None,
    )
    db = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=db)
    cm.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("app.db.session.get_db", lambda: cm)

    def _add(unit):
        unit.id = 54

    db.add.side_effect = _add
    db.commit.return_value = None

    r = ai_client.post("/api/purchase_units", json={"name": "别名单位"})
    assert r.status_code == 200
    assert r.json()["message"] == "添加成功"
