"""COVERAGE_RAMP Phase 6 round 7: backend low-coverage modules.

Targets:
- ``app/fastapi_routes/ai_assistant.py`` (~64% line coverage, 80 lines uncovered)
- ``app/infrastructure/skills/template_manager/template_manager.py``
  (~36.7% line coverage, 81 lines uncovered)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / app service /
external facade). The router functions themselves are exercised through real
FastAPI sub-apps via ``fastapi.testclient.TestClient`` so the route bodies are
truly covered (铁律 4: mock 最小化).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.fastapi_routes import ai_assistant
from app.infrastructure.skills.template_manager.template_manager import (
    create_template,
    decompose_template_file,
    get_default_template,
    get_template_file_path,
    get_template_info,
    list_all_templates,
    list_templates_by_type,
    resolve_template_path,
    save_template_file,
)

# ---------------------------------------------------------------------------
# Shared helpers — ai_assistant router sub-app
# ---------------------------------------------------------------------------


def _ai_assistant_client() -> TestClient:
    """Build an isolated FastAPI sub-app that only mounts the ai_assistant router.

    This avoids pulling in the full application factory (which would trigger
    heavy bootstrap side effects) while still exercising the real route
    function bodies.
    """
    app = FastAPI()
    app.include_router(ai_assistant.router)
    return TestClient(app)


def _parse_json_response(resp: JSONResponse) -> dict:
    """Decode a FastAPI ``JSONResponse`` body into a dict (for direct function calls)."""
    import json

    if hasattr(resp, "body"):
        return json.loads(resp.body.decode())
    return dict(resp)


# ---------------------------------------------------------------------------
# ai_assistant — /health & /api/health
# ---------------------------------------------------------------------------


def test_compat_health_returns_ok_status() -> None:
    client = _ai_assistant_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert "timestamp" in body["data"]


def test_compat_health_api_alias_returns_ok_status() -> None:
    client = _ai_assistant_client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


# ---------------------------------------------------------------------------
# ai_assistant — /api/generate
# ---------------------------------------------------------------------------


def test_compat_ai_generate_empty_order_text_returns_400() -> None:
    client = _ai_assistant_client()
    resp = client.post("/api/generate", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "订单" in body["message"]


def test_compat_ai_generate_whitespace_only_order_text_returns_400() -> None:
    client = _ai_assistant_client()
    resp = client.post("/api/generate", json={"order_text": "   "})
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_compat_ai_generate_parse_failure_returns_400() -> None:
    client = _ai_assistant_client()
    with patch("app.routes.tools._parse_order_text") as mock_parse:
        mock_parse.return_value = {"success": False, "message": "格式错误"}
        resp = client.post("/api/generate", json={"order_text": "乱七八糟"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "格式错误" in body["message"]


def test_compat_ai_generate_parse_success_but_empty_products_returns_400() -> None:
    client = _ai_assistant_client()
    with patch("app.routes.tools._parse_order_text") as mock_parse:
        mock_parse.return_value = {
            "success": True,
            "unit_name": "",
            "products": [],
        }
        resp = client.post("/api/generate", json={"order_text": "无单位无产品"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "空" in body["message"]


def test_compat_ai_generate_service_failure_returns_500() -> None:
    client = _ai_assistant_client()
    with (
        patch("app.routes.tools._parse_order_text") as mock_parse,
        patch.object(ai_assistant, "_shipment_svc") as mock_svc_get,
    ):
        mock_parse.return_value = {
            "success": True,
            "unit_name": "甲公司",
            "products": [{"name": "漆", "quantity": 1, "price": 10}],
        }
        mock_svc = MagicMock()
        mock_svc.generate_shipment_document.return_value = {
            "success": False,
            "message": "生成失败",
        }
        mock_svc_get.return_value = mock_svc
        resp = client.post(
            "/api/generate",
            json={"order_text": "甲公司 漆 1 10", "template_name": "default"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False


def test_compat_ai_generate_success_returns_doc_info() -> None:
    client = _ai_assistant_client()
    with (
        patch("app.routes.tools._parse_order_text") as mock_parse,
        patch.object(ai_assistant, "_shipment_svc") as mock_svc_get,
    ):
        mock_parse.return_value = {
            "success": True,
            "unit_name": "甲公司",
            "products": [{"name": "漆", "quantity": 1, "price": 10}],
        }
        mock_svc = MagicMock()
        mock_svc.generate_shipment_document.return_value = {
            "success": True,
            "file_path": "/tmp/shipment/foo.docx",
            "doc_name": "foo.docx",
            "order_number": "ORD-1",
            "total_amount": 10.0,
            "total_quantity": 1,
        }
        mock_svc_get.return_value = mock_svc
        resp = client.post(
            "/api/generate",
            json={"order_text": "甲公司 漆 1 10"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["doc_name"] == "foo.docx"
    assert body["data"]["download_url"] == "/api/shipment/download/foo.docx"
    assert body["data"]["order_number"] == "ORD-1"
    assert body["filename"] == "foo.docx"


def test_compat_ai_generate_recoverable_error_returns_500() -> None:
    client = _ai_assistant_client()
    with (
        patch("app.routes.tools._parse_order_text") as mock_parse,
        patch.object(ai_assistant, "_shipment_svc") as mock_svc_get,
    ):
        mock_parse.return_value = {
            "success": True,
            "unit_name": "甲公司",
            "products": [{"name": "漆", "quantity": 1, "price": 10}],
        }
        mock_svc_get.side_effect = RuntimeError("shipment service down")
        resp = client.post(
            "/api/generate",
            json={"order_text": "甲公司 漆 1 10"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert "shipment service down" in body["message"]


# ---------------------------------------------------------------------------
# ai_assistant — /api/shipment-records/units & /records
# ---------------------------------------------------------------------------


def test_compat_shipment_records_units_returns_list() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_shipment_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_purchase_units.return_value = ["甲公司", "乙公司"]
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/shipment-records/units")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == ["甲公司", "乙公司"]
    assert body["count"] == 2


def test_compat_shipment_records_units_empty_list() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_shipment_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_purchase_units.return_value = []
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/shipment-records/units")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["count"] == 0


def test_compat_shipment_records_records_returns_rows() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_shipment_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = [{"id": 1, "unit": "甲"}]
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/shipment-records/records", params={"unit": "甲"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    mock_svc.get_shipment_records.assert_called_once_with(unit_name="甲")


def test_compat_shipment_records_records_no_unit_filter() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_shipment_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/shipment-records/records")
    assert resp.status_code == 200
    mock_svc.get_shipment_records.assert_called_once_with(unit_name=None)


# ---------------------------------------------------------------------------
# ai_assistant — /api/units
# ---------------------------------------------------------------------------


def test_compat_units_alias_returns_data() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.get_purchase_units") as mock_units:
        mock_units.return_value = [{"id": 1, "unit_name": "甲"}]
        resp = client.get("/api/units")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["count"] == 1


def test_compat_units_alias_empty_list() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.get_purchase_units") as mock_units:
        mock_units.return_value = []
        resp = client.get("/api/units")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# ai_assistant — /api/purchase_units (POST/PUT/DELETE/by_name)
# ---------------------------------------------------------------------------


def test_compat_purchase_units_create_empty_name_returns_400() -> None:
    client = _ai_assistant_client()
    resp = client.post("/api/purchase_units", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "单位名称" in body["message"]


def test_compat_purchase_units_create_already_exists_returns_ok() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.find_purchase_unit") as mock_find:
        mock_find.return_value = {"id": 7, "unit_name": "甲公司"}
        resp = client.post(
            "/api/purchase_units",
            json={"unit_name": "甲公司", "contact_person": "x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == 7
    assert body["message"] == "已存在"


def test_compat_purchase_units_create_new_unit_success() -> None:
    client = _ai_assistant_client()
    mock_db = MagicMock()
    mock_unit = MagicMock()
    mock_unit.id = 99
    mock_unit.unit_name = "新公司"
    # PurchaseUnit(...) returns mock_unit
    with (
        patch(
            "app.application.facades.query_facade.find_purchase_unit",
            return_value=None,
        ),
        patch("app.db.session.get_db") as mock_get_db,
        patch("app.db.models.PurchaseUnit", return_value=mock_unit) as mock_model,
    ):
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        resp = client.post(
            "/api/purchase_units",
            json={
                "unit_name": "新公司",
                "contact_person": "p",
                "contact_phone": "123",
                "address": "addr",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == 99
    assert body["message"] == "添加成功"
    mock_db.add.assert_called_once_with(mock_unit)
    mock_db.commit.assert_called_once()
    # Verify the model was constructed with the right kwargs
    _, kwargs = mock_model.call_args
    assert kwargs["unit_name"] == "新公司"
    assert kwargs["contact_person"] == "p"
    assert kwargs["contact_phone"] == "123"
    assert kwargs["address"] == "addr"


def test_compat_purchase_units_update_not_found_returns_404() -> None:
    client = _ai_assistant_client()
    mock_db = MagicMock()
    # query(...).first() returns None
    mock_db.query.return_value.filter.return_value.first.return_value = None
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        resp = client.put("/api/purchase_units/1", json={"unit_name": "x"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert "不存在" in body["message"]


def test_compat_purchase_units_update_success_returns_200() -> None:
    client = _ai_assistant_client()
    mock_db = MagicMock()
    mock_unit = MagicMock()
    mock_unit.id = 5
    mock_unit.unit_name = "old"
    mock_db.query.return_value.filter.return_value.first.return_value = mock_unit
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        resp = client.put(
            "/api/purchase_units/5",
            json={
                "unit_name": "new",
                "contact_person": "p",
                "contact_phone": "123",
                "address": "addr",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "更新成功"
    assert mock_unit.unit_name == "new"
    assert mock_unit.contact_person == "p"
    assert mock_unit.contact_phone == "123"
    assert mock_unit.address == "addr"
    mock_db.commit.assert_called_once()


def test_compat_purchase_units_update_empty_unit_name_keeps_old() -> None:
    client = _ai_assistant_client()
    mock_db = MagicMock()
    mock_unit = MagicMock()
    mock_unit.id = 5
    mock_unit.unit_name = "oldname"
    mock_db.query.return_value.filter.return_value.first.return_value = mock_unit
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        resp = client.put(
            "/api/purchase_units/5",
            json={"unit_name": "   "},  # 空白 → 不更新
        )
    assert resp.status_code == 200
    # unit_name 应保持原值（未被 setattr）
    assert mock_unit.unit_name == "oldname"


def test_compat_purchase_units_delete_not_found_returns_404() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.query_service") as mock_qs:
        mock_qs.delete.return_value = 0
        resp = client.delete("/api/purchase_units/999")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert "不存在" in body["message"]


def test_compat_purchase_units_delete_success_returns_200() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.query_service") as mock_qs:
        mock_qs.delete.return_value = 1
        resp = client.delete("/api/purchase_units/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "删除成功"


def test_compat_purchase_units_by_name_not_found_returns_404() -> None:
    client = _ai_assistant_client()
    with patch(
        "app.application.facades.query_facade.find_purchase_unit",
        return_value=None,
    ):
        resp = client.get("/api/purchase_units/by_name/不存在")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_compat_purchase_units_by_name_found_returns_200() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.find_purchase_unit") as mock_find:
        mock_find.return_value = {"id": 3, "unit_name": "甲公司"}
        resp = client.get("/api/purchase_units/by_name/甲公司")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == 3
    # 应去除首尾空白
    mock_find.assert_called_once_with(unit_name="甲公司")


# ---------------------------------------------------------------------------
# ai_assistant — /api/product_names*
# ---------------------------------------------------------------------------


def test_compat_product_names_returns_list() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_distinct_product_names") as mock_names:
        mock_names.return_value = ["漆", "桶"]
        resp = client.get("/api/product_names")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == ["漆", "桶"]
    assert body["count"] == 2


def test_compat_product_names_search_with_keyword() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_distinct_product_names") as mock_names:
        mock_names.return_value = ["漆"]
        resp = client.get("/api/product_names/search", params={"keyword": "漆"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    mock_names.assert_called_once_with(keyword="漆")


def test_compat_product_names_search_empty_keyword_passes_none() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_distinct_product_names") as mock_names:
        mock_names.return_value = []
        resp = client.get("/api/product_names/search")
    assert resp.status_code == 200
    mock_names.assert_called_once_with(keyword=None)


def test_compat_product_names_by_unit_returns_list() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_distinct_product_names") as mock_names:
        mock_names.return_value = ["漆"]
        resp = client.get("/api/product_names/by_unit/5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["unit_id"] == 5


def test_compat_product_by_unit_and_name_missing_name_returns_400() -> None:
    client = _ai_assistant_client()
    resp = client.get("/api/product_names/by_unit_and_name")
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "name" in body["message"]


def test_compat_product_by_unit_and_name_not_found_returns_404() -> None:
    client = _ai_assistant_client()
    with patch(
        "app.application.facades.query_facade.find_product",
        return_value=None,
    ):
        resp = client.get("/api/product_names/by_unit_and_name", params={"name": "不存在"})
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_compat_product_by_unit_and_name_found_returns_200() -> None:
    client = _ai_assistant_client()
    with patch("app.application.facades.query_facade.find_product") as mock_find:
        mock_find.return_value = {"id": 1, "name": "漆"}
        resp = client.get("/api/product_names/by_unit_and_name", params={"name": "  漆  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == 1
    mock_find.assert_called_once_with(name="漆")


# ---------------------------------------------------------------------------
# ai_assistant — /api/printers & /api/print/diagnose
# ---------------------------------------------------------------------------


def test_compat_printers_returns_normalized_payload() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_printer_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {
            "success": True,
            "printers": ["p1"],
            "count": 1,
            "classified": {"a": []},
            "summary": {"total": 1},
            "selection": {"default": "p1"},
        }
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/printers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["printers"] == ["p1"]
    assert body["count"] == 1
    assert body["classified"] == {"a": []}
    assert body["summary"] == {"total": 1}
    assert body["selection"] == {"default": "p1"}


def test_compat_printers_missing_fields_default_to_empty() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_printer_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {}
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/printers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["printers"] == []
    assert body["count"] == 0
    assert body["classified"] == {}
    assert body["summary"] == {}
    assert body["selection"] == {}


def test_compat_print_diagnose_success_returns_diagnostic() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_printer_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {"printers": ["p1"]}
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/print/diagnose")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["diagnostic"]["printers"] == ["p1"]


def test_compat_print_diagnose_recoverable_error_returns_500() -> None:
    client = _ai_assistant_client()
    with patch.object(ai_assistant, "_printer_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.get_printers.side_effect = RuntimeError("printer driver crash")
        mock_svc_get.return_value = mock_svc
        resp = client.get("/api/print/diagnose")
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert "printer driver crash" in body["message"]


# ---------------------------------------------------------------------------
# ai_assistant — /api/print/{filename}, /api/print-last, /api/print/pdf_labels
# ---------------------------------------------------------------------------


def test_compat_print_last_returns_501() -> None:
    client = _ai_assistant_client()
    resp = client.post("/api/print-last")
    assert resp.status_code == 501
    body = resp.json()
    assert body["success"] is False
    assert "print-last" in body["message"]


def test_compat_print_pdf_labels_returns_501() -> None:
    # 注意：``/api/print/pdf_labels`` 路由被先注册的 ``/api/print/{filename:path}``
    # 路径参数路由遮蔽，无法通过 HTTP 触发；这里直接调用函数以覆盖其函数体。
    resp = ai_assistant.compat_print_pdf_labels()
    assert resp.status_code == 501
    body = resp.body.decode() if hasattr(resp, "body") else ""
    assert "pdf_labels" in body
    assert "false" in body.lower()


def test_compat_print_shipment_file_not_found_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _ai_assistant_client()
    monkeypatch.setattr("app.utils.path_utils.get_app_data_dir", lambda: str(tmp_path))
    resp = client.post("/api/print/missing.docx", json={})
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert "文件不存在" in body["message"]


def test_compat_print_shipment_file_success_returns_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _ai_assistant_client()
    output_dir = tmp_path / "shipment_outputs"
    output_dir.mkdir()
    file_path = output_dir / "foo.docx"
    file_path.write_bytes(b"fake doc")

    monkeypatch.setattr("app.utils.path_utils.get_app_data_dir", lambda: str(tmp_path))
    with patch.object(ai_assistant, "_printer_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.print_document.return_value = {"success": True, "printer": "p1"}
        mock_svc_get.return_value = mock_svc
        resp = client.post(
            "/api/print/foo.docx",
            json={"printer_name": "p1"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    mock_svc.print_document.assert_called_once()
    call_kwargs = mock_svc.print_document.call_args.kwargs
    assert call_kwargs["printer_name"] == "p1"


def test_compat_print_shipment_file_failure_returns_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _ai_assistant_client()
    output_dir = tmp_path / "shipment_outputs"
    output_dir.mkdir()
    file_path = output_dir / "bar.docx"
    file_path.write_bytes(b"fake doc")

    monkeypatch.setattr("app.utils.path_utils.get_app_data_dir", lambda: str(tmp_path))
    with patch.object(ai_assistant, "_printer_svc") as mock_svc_get:
        mock_svc = MagicMock()
        mock_svc.print_document.return_value = {
            "success": False,
            "message": "printer busy",
        }
        mock_svc_get.return_value = mock_svc
        resp = client.post("/api/print/bar.docx", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# ai_assistant — /api/print/single_label
# ---------------------------------------------------------------------------


def test_compat_print_single_label_no_model_number_uses_defaults() -> None:
    # 注意：``/api/print/single_label`` 路由被先注册的 ``/api/print/{filename:path}``
    # 路径参数路由遮蔽，无法通过 HTTP 触发；这里直接调用函数以覆盖其函数体。
    with patch("app.application.print_app_service.get_print_application_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.print_single_label.return_value = {
            "success": True,
            "message": "ok",
        }
        mock_get_svc.return_value = mock_svc
        resp = ai_assistant.compat_print_single_label({})
    assert resp.status_code == 200
    body = _parse_json_response(resp)
    assert body["success"] is True
    call_kwargs = mock_svc.print_single_label.call_args.kwargs
    assert call_kwargs["product_name"] == ""
    assert call_kwargs["model_number"] is None
    assert call_kwargs["unit"] == "个"
    assert call_kwargs["quantity"] == 1


def test_compat_print_single_label_invalid_quantity_defaults_to_1() -> None:
    with patch("app.application.print_app_service.get_print_application_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.print_single_label.return_value = {"success": True}
        mock_get_svc.return_value = mock_svc
        # quantity=0 → 1, quantity=200 → 1
        resp = ai_assistant.compat_print_single_label({"quantity": 0})
        assert resp.status_code == 200
        assert mock_svc.print_single_label.call_args.kwargs["quantity"] == 1

        resp = ai_assistant.compat_print_single_label({"quantity": 200})
        assert resp.status_code == 200
        assert mock_svc.print_single_label.call_args.kwargs["quantity"] == 1


def test_compat_print_single_label_with_model_number_lookup_success() -> None:
    with (
        patch("app.application.get_product_app_service") as mock_get_product,
        patch("app.application.print_app_service.get_print_application_service") as mock_get_print,
    ):
        mock_product_svc = MagicMock()
        mock_product_svc.search_products.return_value = [
            {"name": "高级漆", "specification": "20L", "unit": "桶"}
        ]
        mock_get_product.return_value = mock_product_svc

        mock_print_svc = MagicMock()
        mock_print_svc.print_single_label.return_value = {"success": True}
        mock_get_print.return_value = mock_print_svc

        resp = ai_assistant.compat_print_single_label({"model_number": "ABC", "quantity": 5})
    assert resp.status_code == 200
    call_kwargs = mock_print_svc.print_single_label.call_args.kwargs
    assert call_kwargs["product_name"] == "高级漆"
    assert call_kwargs["specification"] == "20L"
    assert call_kwargs["unit"] == "桶"
    assert call_kwargs["quantity"] == 5
    assert call_kwargs["model_number"] == "ABC"


def test_compat_print_single_label_product_lookup_failure_falls_back() -> None:
    with (
        patch("app.application.get_product_app_service") as mock_get_product,
        patch("app.application.print_app_service.get_print_application_service") as mock_get_print,
    ):
        mock_get_product.side_effect = RuntimeError("product db down")

        mock_print_svc = MagicMock()
        mock_print_svc.print_single_label.return_value = {"success": True}
        mock_get_print.return_value = mock_print_svc

        resp = ai_assistant.compat_print_single_label({"model_number": "ABC"})
    assert resp.status_code == 200
    # 查询失败时使用 model_number 作为 product_name
    call_kwargs = mock_print_svc.print_single_label.call_args.kwargs
    assert call_kwargs["product_name"] == "ABC"


def test_compat_print_single_label_print_failure_returns_400() -> None:
    with patch("app.application.print_app_service.get_print_application_service") as mock_get_print:
        mock_print_svc = MagicMock()
        mock_print_svc.print_single_label.return_value = {
            "success": False,
            "message": "no printer",
        }
        mock_get_print.return_value = mock_print_svc
        resp = ai_assistant.compat_print_single_label({})
    assert resp.status_code == 400
    body = _parse_json_response(resp)
    assert body["success"] is False


def test_compat_print_single_label_recoverable_error_returns_500() -> None:
    with patch("app.application.print_app_service.get_print_application_service") as mock_get_print:
        mock_get_print.side_effect = ValueError("print svc broken")
        resp = ai_assistant.compat_print_single_label({})
    assert resp.status_code == 500
    body = _parse_json_response(resp)
    assert body["success"] is False
    assert "print svc broken" in body["message"]


# ---------------------------------------------------------------------------
# ai_assistant — /api/tts
# ---------------------------------------------------------------------------


def test_compat_tts_empty_text_returns_400() -> None:
    client = _ai_assistant_client()
    resp = client.post("/api/tts", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "text" in body["message"]


def test_compat_tts_whitespace_text_returns_400() -> None:
    client = _ai_assistant_client()
    resp = client.post("/api/tts", json={"text": "   "})
    assert resp.status_code == 400


def test_compat_tts_success_returns_audio_payload() -> None:
    client = _ai_assistant_client()
    with (
        patch("app.application.facades.tts_facade.synthesize_to_data_uri") as mock_synth,
        patch("app.application.facades.tts_facade.trigger_common_tts_warmup") as mock_warmup,
    ):
        mock_warmup.return_value = None
        mock_synth.return_value = {
            "audioBase64": "AAA",
            "voice": "zh-CN-XiaoxiaoNeural",
            "lang": "zh",
        }
        resp = client.post(
            "/api/tts",
            json={
                "text": "你好",
                "speakerId": 1,
                "lang": "ZH",
                "voice": "v1",
                "rate": 1,
                "pitch": 0,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["audioBase64"] == "AAA"
    assert body["data"]["speakerId"] == 1
    assert body["data"]["lang"] == "zh"
    mock_synth.assert_called_once()
    call_kwargs = mock_synth.call_args.kwargs
    assert call_kwargs["text"] == "你好"
    assert call_kwargs["lang"] == "zh"  # 应被 lower()
    assert call_kwargs["voice"] == "v1"
    assert call_kwargs["speaker_id"] == 1


def test_compat_tts_recoverable_error_falls_back_to_browser_voice() -> None:
    client = _ai_assistant_client()
    with (
        patch("app.application.facades.tts_facade.synthesize_to_data_uri") as mock_synth,
        patch("app.application.facades.tts_facade.trigger_common_tts_warmup") as mock_warmup,
    ):
        mock_warmup.return_value = None
        mock_synth.side_effect = RuntimeError("edge tts offline")
        resp = client.post("/api/tts", json={"text": "你好"})
    # 注意：源码中 TTS 不可用时返回 200（让前端使用浏览器语音）
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "浏览器语音" in body["message"]
    assert body["data"] == {}


# ===========================================================================
# template_manager — module-level functions
# ===========================================================================


def _mock_template_svc() -> MagicMock:
    """Build a mock TemplateApplicationService for use as get_template_app_service."""
    svc = MagicMock()
    svc.list_templates.return_value = []
    svc.list_by_type.return_value = []
    svc.resolve_template_file.return_value = None
    svc.get_default_for_type.return_value = None
    svc.save_template_file.return_value = {"success": True}
    return svc


# ---------------------------------------------------------------------------
# list_all_templates / list_templates_by_type
# ---------------------------------------------------------------------------


def test_list_all_templates_returns_list() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.list_templates.return_value = [{"id": 1, "name": "T1"}]
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = list_all_templates()
    assert result == [{"id": 1, "name": "T1"}]
    mock_svc.list_templates.assert_called_once_with()


def test_list_all_templates_empty_list() -> None:
    mock_svc = _mock_template_svc()
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = list_all_templates()
    assert result == []


def test_list_templates_by_type_default_active_only_true() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.list_by_type.return_value = [{"id": 1}]
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = list_templates_by_type("发货单")
    assert result == [{"id": 1}]
    mock_svc.list_by_type.assert_called_once_with("发货单", True)


def test_list_templates_by_type_active_only_false() -> None:
    mock_svc = _mock_template_svc()
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = list_templates_by_type("标签", active_only=False)
    assert result == []
    mock_svc.list_by_type.assert_called_once_with("标签", False)


def test_list_templates_by_type_empty_type_returns_empty() -> None:
    mock_svc = _mock_template_svc()
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = list_templates_by_type("")
    assert result == []
    mock_svc.list_by_type.assert_called_once_with("", True)


# ---------------------------------------------------------------------------
# get_template_file_path / get_default_template
# ---------------------------------------------------------------------------


def test_get_template_file_path_returns_path() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.resolve_template_file.return_value = "/tmp/templates/foo.xlsx"
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = get_template_file_path("tpl-1")
    assert result == "/tmp/templates/foo.xlsx"
    mock_svc.resolve_template_file.assert_called_once_with("tpl-1")


def test_get_template_file_path_not_found_returns_none() -> None:
    mock_svc = _mock_template_svc()
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = get_template_file_path("missing")
    assert result is None


def test_get_default_template_default_type_returns_dict() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.get_default_for_type.return_value = {"id": 1, "name": "默认"}
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = get_default_template()
    assert result == {"id": 1, "name": "默认"}
    mock_svc.get_default_for_type.assert_called_once_with("发货单")


def test_get_default_template_custom_type_returns_dict() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.get_default_for_type.return_value = {"id": 2}
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = get_default_template("标签")
    assert result == {"id": 2}
    mock_svc.get_default_for_type.assert_called_once_with("标签")


def test_get_default_template_not_found_returns_none() -> None:
    mock_svc = _mock_template_svc()
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = get_default_template("不存在")
    assert result is None


# ---------------------------------------------------------------------------
# decompose_template_file / resolve_template_path
# ---------------------------------------------------------------------------


def test_decompose_template_file_returns_result_dict() -> None:
    with patch(
        "app.application.excel_template_http_app_service._decompose_template"
    ) as mock_decompose:
        mock_decompose.return_value = ({"success": True, "sheets": ["Sheet1"]}, 200)
        result = decompose_template_file("/tmp/foo.xlsx")
    assert result == {"success": True, "sheets": ["Sheet1"]}
    mock_decompose.assert_called_once_with("/tmp/foo.xlsx", None, 5)


def test_decompose_template_file_with_sheet_and_sample_rows() -> None:
    with patch(
        "app.application.excel_template_http_app_service._decompose_template"
    ) as mock_decompose:
        mock_decompose.return_value = ({"success": False, "message": "err"}, 500)
        result = decompose_template_file("/tmp/foo.xlsx", "Sheet2", 10)
    assert result == {"success": False, "message": "err"}
    mock_decompose.assert_called_once_with("/tmp/foo.xlsx", "Sheet2", 10)


def test_decompose_template_file_failure_dict_propagated() -> None:
    with patch(
        "app.application.excel_template_http_app_service._decompose_template"
    ) as mock_decompose:
        mock_decompose.return_value = (
            {"success": False, "message": "文件不存在", "error_code": "NOT_FOUND"},
            404,
        )
        result = decompose_template_file("/tmp/missing.xlsx")
    assert result["success"] is False
    assert result["error_code"] == "NOT_FOUND"


def test_resolve_template_path_returns_resolved_path() -> None:
    with patch(
        "app.application.excel_template_http_app_service._resolve_template_path"
    ) as mock_resolve:
        mock_resolve.return_value = "/abs/path/foo.xlsx"
        result = resolve_template_path("foo.xlsx")
    assert result == "/abs/path/foo.xlsx"
    mock_resolve.assert_called_once_with("foo.xlsx")


def test_resolve_template_path_not_found_returns_none() -> None:
    with patch(
        "app.application.excel_template_http_app_service._resolve_template_path"
    ) as mock_resolve:
        mock_resolve.return_value = None
        result = resolve_template_path("missing.xlsx")
    assert result is None


def test_resolve_template_path_empty_filename_returns_none() -> None:
    with patch(
        "app.application.excel_template_http_app_service._resolve_template_path"
    ) as mock_resolve:
        mock_resolve.return_value = None
        result = resolve_template_path("")
    assert result is None


# ---------------------------------------------------------------------------
# save_template_file
# ---------------------------------------------------------------------------


def test_save_template_file_success_returns_dict() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.save_template_file.return_value = {
        "success": True,
        "path": "/tmp/foo.xlsx",
    }
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = save_template_file("src.xlsx", "tgt.xlsx")
    assert result == {"success": True, "path": "/tmp/foo.xlsx"}
    mock_svc.save_template_file.assert_called_once_with("src.xlsx", "tgt.xlsx", False)


def test_save_template_file_overwrite_true() -> None:
    mock_svc = _mock_template_svc()
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        save_template_file("src.xlsx", "tgt.xlsx", overwrite=True)
    mock_svc.save_template_file.assert_called_once_with("src.xlsx", "tgt.xlsx", True)


def test_save_template_file_failure_dict_propagated() -> None:
    mock_svc = _mock_template_svc()
    mock_svc.save_template_file.return_value = {
        "success": False,
        "message": "目标已存在",
    }
    with patch(
        "app.infrastructure.skills.template_manager.template_manager.get_template_app_service",
        return_value=mock_svc,
    ):
        result = save_template_file("src.xlsx", "tgt.xlsx")
    assert result["success"] is False
    assert "目标已存在" in result["message"]


# ---------------------------------------------------------------------------
# get_template_info
# ---------------------------------------------------------------------------


def _make_mock_row(
    *,
    analyzed_data: str | None = None,
    editable_config: str | None = None,
    zone_config: str | None = None,
    merged_cells_config: str | None = None,
    style_config: str | None = None,
    business_rules: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> MagicMock:
    """Build a mock DB row mimicking the templates table."""
    row = MagicMock()
    row.id = 1
    row.template_key = "TPL_KEY"
    row.template_name = "默认模板"
    row.template_type = "发货单"
    row.original_file_path = "/tmp/foo.xlsx"
    row.analyzed_data = analyzed_data
    row.editable_config = editable_config
    row.zone_config = zone_config
    row.merged_cells_config = merged_cells_config
    row.style_config = style_config
    row.business_rules = business_rules
    row.created_at = created_at
    row.updated_at = updated_at
    return row


def test_get_template_info_not_found_returns_none() -> None:
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db.execute.return_value = mock_result
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        result = get_template_info(999)
    assert result is None


def test_get_template_info_found_with_all_configs() -> None:
    import json

    mock_db = MagicMock()
    mock_row = _make_mock_row(
        analyzed_data=json.dumps({"a": 1}),
        editable_config=json.dumps({"b": 2}),
        zone_config=json.dumps({"c": 3}),
        merged_cells_config=json.dumps({"d": 4}),
        style_config=json.dumps({"e": 5}),
        business_rules=json.dumps({"f": 6}),
        created_at="2026-01-01",
        updated_at="2026-02-01",
    )
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute.return_value = mock_result
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        result = get_template_info(1)
    assert result is not None
    assert result["id"] == 1
    assert result["template_key"] == "TPL_KEY"
    assert result["template_name"] == "默认模板"
    assert result["template_type"] == "发货单"
    assert result["original_file_path"] == "/tmp/foo.xlsx"
    assert result["analyzed_data"] == {"a": 1}
    assert result["editable_config"] == {"b": 2}
    assert result["zone_config"] == {"c": 3}
    assert result["merged_cells_config"] == {"d": 4}
    assert result["style_config"] == {"e": 5}
    assert result["business_rules"] == {"f": 6}
    assert result["created_at"] == "2026-01-01"
    assert result["updated_at"] == "2026-02-01"


def test_get_template_info_found_with_null_configs() -> None:
    mock_db = MagicMock()
    mock_row = _make_mock_row(
        analyzed_data=None,
        editable_config=None,
        zone_config=None,
        merged_cells_config=None,
        style_config=None,
        business_rules=None,
        created_at=None,
        updated_at=None,
    )
    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db.execute.return_value = mock_result
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        result = get_template_info(1)
    assert result is not None
    assert result["analyzed_data"] is None
    assert result["editable_config"] is None
    assert result["zone_config"] is None
    assert result["merged_cells_config"] is None
    assert result["style_config"] is None
    assert result["business_rules"] is None
    assert result["created_at"] is None
    assert result["updated_at"] is None


# ---------------------------------------------------------------------------
# create_template
# ---------------------------------------------------------------------------


def test_create_template_success_returns_dict() -> None:
    mock_db = MagicMock()
    # First execute (INSERT templates) returns a result with lastrowid
    insert_result = MagicMock()
    insert_result.lastrowid = 42
    # Second execute (INSERT template_usage_log) returns a generic result
    mock_db.execute.side_effect = [insert_result, MagicMock()]
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        result = create_template(
            "新模板",
            template_type="发货单",
            original_file_path="/tmp/foo.xlsx",
            analyzed_data={"a": 1},
            editable_config={"b": 2},
        )
    assert result["success"] is True
    assert result["template_id"] == 42
    assert "TPL_" in result["template_key"]
    assert result["message"] == "模板创建成功"
    # Should have committed twice (once after insert, once after usage log)
    assert mock_db.commit.call_count == 2
    # First execute should be the INSERT INTO templates
    first_call = mock_db.execute.call_args_list[0]
    # The SQL text should contain INSERT INTO templates
    sql_text = str(first_call.args[0])
    assert "INSERT INTO templates" in sql_text
    params = first_call.args[1]
    assert params["template_name"] == "新模板"
    assert params["template_type"] == "发货单"
    assert params["original_file_path"] == "/tmp/foo.xlsx"
    # dict kwargs should be JSON-serialized
    import json as _json

    assert _json.loads(params["analyzed_data"]) == {"a": 1}
    assert _json.loads(params["editable_config"]) == {"b": 2}


def test_create_template_default_type_is_general() -> None:
    mock_db = MagicMock()
    insert_result = MagicMock()
    insert_result.lastrowid = 1
    mock_db.execute.side_effect = [insert_result, MagicMock()]
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        result = create_template("T")
    assert result["success"] is True
    params = mock_db.execute.call_args_list[0].args[1]
    assert params["template_type"] == "通用"


def test_create_template_empty_kwargs_uses_empty_dicts() -> None:
    mock_db = MagicMock()
    insert_result = MagicMock()
    insert_result.lastrowid = 1
    mock_db.execute.side_effect = [insert_result, MagicMock()]
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        result = create_template("T")
    assert result["success"] is True
    params = mock_db.execute.call_args_list[0].args[1]
    import json as _json

    # All config fields should default to "{}"
    assert _json.loads(params["analyzed_data"]) == {}
    assert _json.loads(params["editable_config"]) == {}
    assert _json.loads(params["zone_config"]) == {}
    assert _json.loads(params["merged_cells_config"]) == {}
    assert _json.loads(params["style_config"]) == {}
    assert _json.loads(params["business_rules"]) == {}
    assert params["original_file_path"] is None


def test_create_template_usage_log_inserted_with_template_id() -> None:
    mock_db = MagicMock()
    insert_result = MagicMock()
    insert_result.lastrowid = 77
    mock_db.execute.side_effect = [insert_result, MagicMock()]
    with patch("app.db.session.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        mock_get_db.return_value.__exit__.return_value = False
        create_template("日志模板")
    # Second execute should be the INSERT INTO template_usage_log
    second_call = mock_db.execute.call_args_list[1]
    sql_text = str(second_call.args[0])
    assert "INSERT INTO template_usage_log" in sql_text
    params = second_call.args[1]
    assert params["template_id"] == 77
    assert "日志模板" in params["result"]
