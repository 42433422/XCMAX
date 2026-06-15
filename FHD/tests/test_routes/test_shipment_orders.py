"""shipment_orders 路由测试 — 覆盖出货单 CRUD、搜索、批量生成、打印等。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import shipment_orders


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(shipment_orders.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _mock_svc():
    """默认 mock shipment application service。"""
    mock = MagicMock()
    with patch.object(shipment_orders, "_svc", return_value=mock):
        yield mock


# ---------------------------------------------------------------------------
# next_number
# ---------------------------------------------------------------------------


class TestOrdersNextNumber:
    def test_root_path(self, client: TestClient):
        with patch.object(shipment_orders, "query_service") as mock_q:
            mock_q.count.return_value = 5
            r = client.get("/orders/next_number")
            assert r.status_code == 200
            data = r.json()["data"]
            assert "order_number" in data
            assert data["sequence"] == 6

    def test_under_api(self, client: TestClient):
        with patch.object(shipment_orders, "query_service") as mock_q:
            mock_q.count.return_value = 0
            r = client.get("/api/orders/next_number")
            assert r.status_code == 200
            assert r.json()["data"]["sequence"] == 1

    def test_under_shipment_validates_suffix(self, client: TestClient):
        with patch.object(shipment_orders, "query_service") as mock_q:
            mock_q.count.return_value = 0
            r = client.get("/api/shipment/orders/next_number", params={"suffix": "B"})
            assert r.status_code == 200
            assert r.json()["data"]["order_number"].endswith("B")

    def test_under_shipment_invalid_suffix_fallback(self, client: TestClient):
        with patch.object(shipment_orders, "query_service") as mock_q:
            mock_q.count.return_value = 0
            r = client.get("/api/shipment/orders/next_number", params={"suffix": "12"})
            assert r.status_code == 200
            assert r.json()["data"]["order_number"].endswith("A")


# ---------------------------------------------------------------------------
# shipment generate
# ---------------------------------------------------------------------------


class TestShipmentGenerate:
    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.generate_shipment_document.return_value = {"success": True, "file_path": "/tmp/out.xlsx"}
        r = client.post("/api/shipment/generate", json={"unit_name": "测试单位", "products": [{"name": "A", "qty": 1}]})
        assert r.status_code == 200

    def test_empty_unit_name(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate", json={"unit_name": "", "products": []})
        assert r.status_code == 400

    def test_empty_products(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate", json={"unit_name": "单位", "products": []})
        assert r.status_code == 400

    def test_service_error(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.generate_shipment_document.side_effect = Exception("DB error")
        r = client.post("/api/shipment/generate", json={"unit_name": "单位", "products": [{"name": "A"}]})
        assert r.status_code == 500


class TestShipmentGenerateBatch:
    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.generate_shipment_document.return_value = {"success": True}
        r = client.post("/api/shipment/generate-batch", json={
            "shipments": [{"unit_name": "A", "products": [{"name": "X"}]}]
        })
        assert r.status_code == 200
        assert r.json()["data"]["processed"] == 1

    def test_empty_shipments(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": []})
        assert r.status_code == 400

    def test_invalid_entry(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": ["not_a_dict"]})
        assert r.status_code == 200
        assert len(r.json()["data"]["errors"]) > 0

    def test_missing_unit_name(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": [{"products": [{"name": "X"}]}]})
        assert r.status_code == 200
        assert len(r.json()["data"]["errors"]) > 0

    def test_missing_products(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": [{"unit_name": "A"}]})
        assert r.status_code == 200
        assert len(r.json()["data"]["errors"]) > 0


# ---------------------------------------------------------------------------
# shipment print
# ---------------------------------------------------------------------------


class TestShipmentPrint:
    def test_empty_file_path(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/print", json={})
        assert r.status_code == 400

    def test_file_not_found(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/print", json={"file_path": "/nonexistent/file.xlsx"})
        assert r.status_code == 404

    def test_with_order_id(self, client: TestClient, _mock_svc: MagicMock, tmp_path):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        _mock_svc.mark_as_printed.return_value = {"success": True}
        r = client.post("/api/shipment/print", json={"file_path": str(test_file), "order_id": 1})
        assert r.status_code == 200

    def test_without_order_id(self, client: TestClient, _mock_svc: MagicMock, tmp_path):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        r = client.post("/api/shipment/print", json={"file_path": str(test_file)})
        assert r.status_code == 200
        assert r.json()["updated"] is False

    def test_invalid_order_id(self, client: TestClient, _mock_svc: MagicMock, tmp_path):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        r = client.post("/api/shipment/print", json={"file_path": str(test_file), "order_id": "abc"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# shipment download
# ---------------------------------------------------------------------------


class TestShipmentDownload:
    def test_file_not_found(self, client: TestClient, _mock_svc: MagicMock, monkeypatch):
        monkeypatch.setenv("WORKSPACE_ROOT", "/nonexistent_xcmax_test")
        r = client.get("/api/shipment/download/nonexistent.xlsx")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# shipment orders list / search / latest
# ---------------------------------------------------------------------------


class TestShipmentOrdersList:
    def test_list(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_orders.return_value = [{"id": 1, "order_number": "25-06-00001A"}]
        r = client.get("/api/shipment/orders")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_search_empty(self, client: TestClient, _mock_svc: MagicMock):
        r = client.get("/api/shipment/orders/search")
        assert r.json()["data"] == []

    def test_search_with_query(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.search_orders.return_value = [{"id": 1}]
        r = client.get("/api/shipment/orders/search", params={"q": "测试"})
        assert r.json()["count"] == 1

    def test_latest(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_orders.return_value = [{"id": 1}]
        r = client.get("/api/shipment/orders/latest")
        assert r.json()["success"] is True


class TestShipmentOrdersGet:
    def test_found(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_order.return_value = {"id": 1, "order_number": "25-06-00001A"}
        r = client.get("/api/shipment/orders/25-06-00001A")
        assert r.status_code == 200

    def test_not_found(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_order.return_value = None
        r = client.get("/api/shipment/orders/999")
        assert r.status_code == 404


class TestShipmentOrdersDelete:
    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.delete_shipment.return_value = {"success": True}
        r = client.delete("/api/shipment/orders/1")
        assert r.status_code == 200

    def test_invalid_format(self, client: TestClient, _mock_svc: MagicMock):
        r = client.delete("/api/shipment/orders/abc")
        assert r.status_code == 400

    def test_delete_failure(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.delete_shipment.return_value = {"success": False, "message": "不存在"}
        r = client.delete("/api/shipment/orders/999")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# api/orders (mirror routes)
# ---------------------------------------------------------------------------


class TestApiOrdersList:
    def test_list(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_orders.return_value = [{"id": 1}]
        r = client.get("/api/orders")
        assert r.json()["success"] is True

    def test_latest(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_orders.return_value = []
        r = client.get("/api/orders/latest")
        assert r.json()["success"] is True

    def test_search(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.search_orders.return_value = [{"id": 1}]
        r = client.get("/api/orders/search", params={"q": "test"})
        assert r.json()["count"] == 1

    def test_search_empty(self, client: TestClient, _mock_svc: MagicMock):
        r = client.get("/api/orders/search")
        assert r.json()["data"] == []


class TestApiOrdersGet:
    def test_found(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_order.return_value = {"id": 1}
        r = client.get("/api/orders/1")
        assert r.status_code == 200

    def test_not_found(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_order.return_value = None
        r = client.get("/api/orders/999")
        assert r.status_code == 404

    def test_invalid_number(self, client: TestClient, _mock_svc: MagicMock):
        r = client.get("/api/orders/abc")
        assert r.status_code == 404


class TestApiOrdersDelete:
    def test_clear_all(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.clear_all_orders.return_value = {"success": True}
        r = client.delete("/api/orders")
        assert r.status_code == 200


class TestApiOrdersSetSequence:
    def test_set(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.set_order_sequence.return_value = {"success": True}
        r = client.post("/api/orders/set-sequence", json={"sequence": 10})
        assert r.status_code == 200


class TestApiOrdersResetSequence:
    def test_reset(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.reset_order_sequence.return_value = {"success": True}
        r = client.post("/api/orders/reset-sequence")
        assert r.status_code == 200


class TestApiOrdersPurchaseUnits:
    def test_list(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_purchase_units.return_value = ["单位A"]
        r = client.get("/api/orders/purchase-units")
        assert r.json()["count"] == 1


class TestApiOrdersClearShipment:
    def test_missing_unit(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/orders/clear-shipment", json={})
        assert r.status_code == 400

    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.clear_shipment_by_unit.return_value = {"success": True}
        r = client.post("/api/orders/clear-shipment", json={"purchase_unit": "单位A"})
        assert r.status_code == 200


class TestApiOrdersClearAll:
    def test_clear(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.clear_all_orders.return_value = {"success": True}
        r = client.delete("/api/orders/clear-all")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# shipment records
# ---------------------------------------------------------------------------


class TestShipmentRecordsDashboardAlias:
    def test_list(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_shipment_records.return_value = [{"id": 1}]
        r = client.get("/api/shipment/records")
        assert r.json()["success"] is True

    def test_with_unit_filter(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.get_shipment_records.return_value = []
        r = client.get("/api/shipment/records", params={"unit": "A"})
        assert r.json()["success"] is True


class TestShipmentRecordsCreate:
    def test_missing_unit_name(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/shipment-records/record", json={})
        assert r.status_code == 400

    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.create_shipment.return_value = {"success": True}
        r = client.post("/api/shipment/shipment-records/record", json={
            "unit_name": "A", "products": [{"name": "X"}]
        })
        assert r.status_code == 200


class TestShipmentRecordsPatch:
    def test_missing_id(self, client: TestClient, _mock_svc: MagicMock):
        r = client.patch("/api/shipment/shipment-records/record", json={})
        assert r.status_code == 400

    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.update_shipment_record.return_value = {"success": True}
        r = client.patch("/api/shipment/shipment-records/record", json={"id": 1})
        assert r.status_code == 200


class TestShipmentRecordsDelete:
    def test_missing_id(self, client: TestClient, _mock_svc: MagicMock):
        r = client.request("DELETE", "/api/shipment/shipment-records/record", json={})
        assert r.status_code == 400

    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.delete_shipment_record.return_value = {"success": True}
        r = client.request("DELETE", "/api/shipment/shipment-records/record", json={"id": 1})
        assert r.status_code == 200


class TestShipmentRecordsExport:
    def test_no_file(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.export_shipment_records.return_value = {"success": False, "message": "无数据"}
        r = client.get("/api/shipment/shipment-records/export")
        assert r.status_code == 500
