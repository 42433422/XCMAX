"""Mounted Mod routes resolve canonical handlers, not incomplete typing facades."""

from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import shipment_orders as compatibility
from app.fastapi_routes.domains.shipment import shipment_orders
from app.infrastructure.mods.mod_manager import import_mod_backend_py
from app.infrastructure.tenant_scope import current_tenant_id
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_real_mod_handlers_preserve_validation_and_service_tenant(monkeypatch, trusted_actor):
    assert compatibility is shipment_orders
    actor = trusted_actor(tenant_id=23, permissions=["shipment.view", "shipment.edit"])
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    service = Mock()
    service.get_order.return_value = {"id": 74, "order_number": "74"}
    service.search_orders.return_value = [{"id": 74}]
    service.export_shipment_records.return_value = {"success": False, "message": "no export"}
    scopes = []

    def scoped_service():
        scopes.append(current_tenant_id())
        return service

    def execute(**kwargs):
        scopes.append(current_tenant_id())
        return {"success": True, "action": kwargs["action"]}

    monkeypatch.setattr(shipment_orders, "_svc", scoped_service)
    records = Mock(side_effect=execute)
    orders = Mock(side_effect=execute)
    monkeypatch.setattr(shipment_orders, "_run_shipment_records_agent", records)
    monkeypatch.setattr(shipment_orders, "_run_shipment_orders_agent", orders)
    mod = import_mod_backend_py(
        str(Path(__file__).resolve().parents[2] / "mods" / "xcagi-erp-domain-bridge"),
        "xcagi-erp-domain-bridge",
        "blueprints",
    )
    app = FastAPI()
    mod.register_fastapi_routes(app, "xcagi-erp-domain-bridge")
    base = "/api/mod/xcagi-erp-domain-bridge"
    with TestClient(app) as client:
        headers = {**actor.headers, "X-Tenant-ID": "999"}
        assert client.post(base + "/orders", headers=headers, json={}).status_code == 400
        records.assert_not_called()
        result = client.post(
            base + "/orders",
            headers=headers,
            json={
                "purchase_unit": "Synthetic",
                "products": [{"name": "P"}],
                "tenant_id": 999,
            },
        )
        assert result.status_code == 201
        assert client.get(base + "/orders/74", headers=headers).json()["data"]["id"] == 74
        assert (
            client.patch(base + "/orders/74", headers=headers, json={"status": "bad"}).status_code
            == 400
        )
        assert records.call_count == 1
        assert (
            client.patch(
                base + "/orders/74", headers=headers, json={"status": "completed"}
            ).status_code
            == 200
        )
        assert client.get(base + "/orders/search?q=Synthetic", headers=headers).json()["count"] == 1
        assert (
            client.get(base + "/orders/export?unit=Synthetic", headers=headers).status_code == 400
        )
        assert client.delete(base + "/orders/clear-all", headers=headers).status_code == 200
        assert client.delete(base + "/shipment/orders/74", headers=headers).status_code == 200
    assert scopes and set(scopes) == {23}
    assert [call.kwargs["action"] for call in records.call_args_list] == ["create", "update"]
    assert [call.kwargs["action"] for call in orders.call_args_list] == ["clear_all", "delete"]
    service.search_orders.assert_called_once_with("Synthetic")
    service.export_shipment_records.assert_called_once_with(
        unit_name="Synthetic",
        template_id=None,
        status_filter=None,
    )
