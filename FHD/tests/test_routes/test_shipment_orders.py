"""shipment_orders 路由测试 — 覆盖出货单 CRUD、搜索、批量生成、打印等。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.print_authorization import (
    _clear_print_authorizations_for_tests,
    finish_document_print_capability,
    issue_document_print_capability,
    reserve_document_print_capability,
)
from app.fastapi_routes import shipment_orders


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _authenticated_owner(request, call_next):
        request.state.user_id = 41
        return await call_next(request)

    app.include_router(shipment_orders.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _mock_svc():
    """默认 mock shipment application service。"""
    mock = MagicMock()
    with patch.object(shipment_orders, "_svc", return_value=mock):
        yield mock


@pytest.fixture(autouse=True)
def _clear_print_authorizations():
    _clear_print_authorizations_for_tests()
    yield
    _clear_print_authorizations_for_tests()


def _post_print_receipt(path, *, owner_user_id: int = 41, order_id: int | None = None) -> str:
    capability = issue_document_print_capability(
        file_path=path,
        owner_user_id=owner_user_id,
        order_id=order_id,
    )
    assert capability is not None
    reservation = reserve_document_print_capability(
        capability["document_token"],
        owner_user_id=owner_user_id,
        file_path=path,
        order_id=order_id,
    )
    assert reservation["success"] is True
    receipt = finish_document_print_capability(reservation, print_succeeded=True)
    assert receipt
    return receipt


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
        r = client.post(
            "/api/shipment/generate",
            json={
                "unit_name": "测试单位",
                "products": [{"name": "A", "qty": 1}],
                # A legacy caller cannot grant access to another user's
                # personal delivery layout through this preview endpoint.
                "owner_user_id": 999,
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["success"] is True
        assert payload["confirmation_required"] is True
        assert payload["task"]["type"] == "shipment_generate"
        assert payload["task"]["api_url"] == "/api/tools/execute"
        assert payload["task"]["payload"]["params"]["unit_name"] == "测试单位"
        assert payload["task"]["payload"]["params"]["products"] == [{"name": "A", "qty": 1}]
        assert "owner_user_id" not in payload["task"]["payload"]["params"]
        _mock_svc.generate_shipment_document.assert_not_called()

    def test_empty_unit_name(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate", json={"unit_name": "", "products": []})
        assert r.status_code == 400

    def test_empty_products(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate", json={"unit_name": "单位", "products": []})
        assert r.status_code == 400

    def test_preview_never_calls_generate_service(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.generate_shipment_document.side_effect = Exception("DB error")
        r = client.post(
            "/api/shipment/generate", json={"unit_name": "单位", "products": [{"name": "A"}]}
        )
        assert r.status_code == 200
        assert r.json()["confirmation_required"] is True
        _mock_svc.generate_shipment_document.assert_not_called()


class TestShipmentGenerateBatch:
    def test_success(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post(
            "/api/shipment/generate-batch",
            json={"shipments": [{"unit_name": "A", "products": [{"name": "X"}]}]},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["success"] is True
        assert payload["confirmation_required"] is True
        assert len(payload["tasks"]) == 1
        assert payload["tasks"][0]["api_url"] == "/api/tools/execute"
        assert payload["tasks"][0]["payload"]["tool_id"] == "shipment_generate"
        _mock_svc.generate_shipment_document.assert_not_called()

    def test_empty_shipments(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": []})
        assert r.status_code == 400

    def test_invalid_entry(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": ["not_a_dict"]})
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert r.json()["data"]["errors"][0]["error_code"] == "invalid_shipment_item"
        _mock_svc.generate_shipment_document.assert_not_called()

    def test_missing_unit_name(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post(
            "/api/shipment/generate-batch", json={"shipments": [{"products": [{"name": "X"}]}]}
        )
        assert r.status_code == 200
        assert r.json()["data"]["errors"][0]["error_code"] == "shipment_unit_required"
        _mock_svc.generate_shipment_document.assert_not_called()

    def test_missing_products(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/generate-batch", json={"shipments": [{"unit_name": "A"}]})
        assert r.status_code == 200
        assert r.json()["data"]["errors"][0]["error_code"] == "shipment_products_required"
        _mock_svc.generate_shipment_document.assert_not_called()


# ---------------------------------------------------------------------------
# shipment print
# ---------------------------------------------------------------------------


class TestShipmentPrint:
    def test_empty_file_path(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/print", json={})
        assert r.status_code == 400

    def test_file_not_found(self, client: TestClient, _mock_svc: MagicMock):
        r = client.post("/api/shipment/print", json={"file_path": "/nonexistent/file.xlsx"})
        assert r.status_code == 409
        assert r.json()["error_code"] == "PRINT_RECEIPT_REQUIRED"
        _mock_svc.mark_as_printed.assert_not_called()

    def test_with_order_id(self, client: TestClient, _mock_svc: MagicMock, tmp_path):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        _mock_svc.mark_as_printed.return_value = {"success": True}
        r = client.post(
            "/api/shipment/print",
            json={
                "file_path": str(test_file),
                "order_id": 1,
                "post_print_receipt": _post_print_receipt(test_file, order_id=1),
            },
        )
        assert r.status_code == 200
        assert r.json()["updated"] is True
        _mock_svc.mark_as_printed.assert_called_once_with(1, printer_name="")

    def test_without_order_id(self, client: TestClient, _mock_svc: MagicMock, tmp_path):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        r = client.post(
            "/api/shipment/print",
            json={
                "file_path": str(test_file),
                "post_print_receipt": _post_print_receipt(test_file),
            },
        )
        assert r.status_code == 200
        assert r.json()["updated"] is False
        _mock_svc.mark_as_printed.assert_not_called()

    def test_post_print_receipt_is_single_use(
        self, client: TestClient, _mock_svc: MagicMock, tmp_path
    ):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        _mock_svc.mark_as_printed.return_value = {"success": True}
        receipt = _post_print_receipt(test_file, order_id=1)
        body = {
            "file_path": str(test_file),
            "order_id": 1,
            "post_print_receipt": receipt,
        }

        first = client.post("/api/shipment/print", json=body)
        repeated = client.post("/api/shipment/print", json=body)

        assert first.status_code == 200
        assert repeated.status_code == 409
        assert repeated.json()["error_code"] == "PRINT_RECEIPT_INVALID"
        _mock_svc.mark_as_printed.assert_called_once_with(1, printer_name="")

    def test_post_print_receipt_rejects_another_existing_file(
        self, client: TestClient, _mock_svc: MagicMock, tmp_path
    ):
        issued_file = tmp_path / "issued.xlsx"
        other_file = tmp_path / "other.xlsx"
        issued_file.write_bytes(b"issued")
        other_file.write_bytes(b"other")

        r = client.post(
            "/api/shipment/print",
            json={
                "file_path": str(other_file),
                "order_id": 1,
                "post_print_receipt": _post_print_receipt(issued_file, order_id=1),
            },
        )

        assert r.status_code == 409
        assert r.json()["error_code"] == "PRINT_RECEIPT_ARTIFACT_MISMATCH"
        _mock_svc.mark_as_printed.assert_not_called()

    def test_invalid_order_id(self, client: TestClient, _mock_svc: MagicMock, tmp_path):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        r = client.post(
            "/api/shipment/print",
            json={
                "file_path": str(test_file),
                "order_id": "abc",
                "post_print_receipt": "irrelevant-but-present",
            },
        )
        assert r.status_code == 400

    def test_rejects_forged_header_or_body_user_without_authenticated_owner(
        self, _mock_svc: MagicMock, tmp_path
    ):
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"fake")
        receipt = _post_print_receipt(test_file, owner_user_id=41, order_id=1)

        app = FastAPI()
        app.include_router(shipment_orders.router)
        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        r = unauthenticated_client.post(
            "/api/shipment/print",
            json={
                "file_path": str(test_file),
                "order_id": 1,
                "post_print_receipt": receipt,
                "user_id": 41,
            },
            headers={"X-User-Id": "41"},
        )

        assert r.status_code == 403
        assert r.json()["error_code"] == "PRINT_RECEIPT_OWNER_MISMATCH"
        _mock_svc.mark_as_printed.assert_not_called()


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

    def test_create(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.create_shipment.return_value = {
            "success": True,
            "shipment": {"id": 1, "purchase_unit": "单位A"},
        }
        r = client.post(
            "/api/orders",
            json={"purchase_unit": "单位A", "products": [{"product_name": "产品A"}]},
        )
        assert r.status_code == 201
        assert r.json()["success"] is True

    def test_create_requires_products(self, client: TestClient):
        r = client.post("/api/orders", json={"purchase_unit": "单位A", "products": []})
        assert r.status_code == 400


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

    def test_update(self, client: TestClient, _mock_svc: MagicMock):
        _mock_svc.update_shipment_record.return_value = {"success": True}
        _mock_svc.get_order.return_value = {
            "id": 1,
            "purchase_unit": "单位B",
            "status": "completed",
        }
        r = client.patch(
            "/api/orders/1",
            json={"purchase_unit": "单位B", "status": "completed"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["purchase_unit"] == "单位B"

    def test_update_rejects_unknown_status(self, client: TestClient):
        r = client.patch("/api/orders/1", json={"status": "shipped"})
        assert r.status_code == 400


class TestApiOrdersExport:
    def test_export_xlsx(self, client: TestClient, _mock_svc: MagicMock, tmp_path, monkeypatch):
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        export_file = export_dir / "shipment_records_all_20260714_000000.xlsx"
        export_file.write_bytes(b"xlsx-test")
        monkeypatch.setattr("app.utils.path_utils.get_data_dir", lambda: str(tmp_path))
        _mock_svc.export_shipment_records.return_value = {
            "success": True,
            "file_path": str(export_file),
            "filename": export_file.name,
        }
        r = client.get("/api/orders/export")
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]


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
        r = client.post(
            "/api/shipment/shipment-records/record",
            json={"unit_name": "A", "products": [{"name": "X"}]},
        )
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
