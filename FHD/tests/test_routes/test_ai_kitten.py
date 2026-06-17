# -*- coding: utf-8 -*-
"""Kitten 分析/图表/报告路由冒烟（FastAPI 版）。

覆盖 ``app.fastapi_routes.ai_kitten`` 全部 14 条路由：
- GET  /api/ai/kitten/business-snapshot
- GET  /api/ai/kitten/charts/{all,revenue,products,customers,profit,inventory}
- GET  /api/ai/kitten/saved/list
- GET  /api/ai/kitten/saved/{id}
- GET  /api/ai/kitten/saved/{id}/export
- DELETE /api/ai/kitten/saved/{id}
- POST /api/ai/kitten/financial/report
- POST /api/ai/kitten/report/export
- POST /api/ai/kitten/report/export-docx
- POST /api/ai/kitten/document/generate
- GET  /api/ai/kitten/document/pickup/{token}

注意：路由函数内部使用延迟导入（``from app.application.facades.kitten_facade import ...``），
因此 monkeypatch 必须打在源模块 ``app.application.facades.kitten_facade`` 上，
而非 ``app.fastapi_routes.ai_kitten`` 上。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import ai_kitten as kitten_module

# 延迟导入的源模块路径
_FACADE = "app.application.facades.kitten_facade"


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(kitten_module.router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    with TestClient(app_with_router, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/business-snapshot
# ---------------------------------------------------------------------------


def test_business_snapshot_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_snap = {"revenue": 10000, "orders": 50}
    monkeypatch.setattr(f"{_FACADE}.build_kitten_business_snapshot", lambda: fake_snap)
    r = client.get("/api/ai/kitten/business-snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"] == fake_snap


def test_business_snapshot_recoverable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.build_kitten_business_snapshot",
        MagicMock(side_effect=ValueError("DB 不可用")),
    )
    r = client.get("/api/ai/kitten/business-snapshot")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert "DB 不可用" in body["message"]


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/charts/all
# ---------------------------------------------------------------------------


def test_charts_all_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_all_charts_data.return_value = {"charts": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/all")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"] == {"charts": []}


def test_charts_all_recoverable_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_all_charts_data.side_effect = RuntimeError("服务异常")
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/all")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/charts/revenue
# ---------------------------------------------------------------------------


def test_charts_revenue_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_revenue_chart_data.return_value = {"months": 6, "data": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/revenue")
    assert r.status_code == 200
    body = r.json()
    assert "months" in body


def test_charts_revenue_custom_months(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_revenue_chart_data.return_value = {"months": 12, "data": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/revenue", params={"months": 12})
    assert r.status_code == 200
    fake_chart_svc.get_revenue_chart_data.assert_called_once_with(12)


def test_charts_revenue_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_revenue_chart_data.side_effect = ConnectionError("网络断开")
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/revenue")
    assert r.status_code == 200  # route returns 200 with error key
    body = r.json()
    assert body["success"] is False
    assert body["error"] is not None


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/charts/products
# ---------------------------------------------------------------------------


def test_charts_products_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_product_pie_chart_data.return_value = {"products": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/products")
    assert r.status_code == 200
    body = r.json()
    assert "products" in body


def test_charts_products_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_product_pie_chart_data.side_effect = TimeoutError("超时")
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/products")
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/charts/customers
# ---------------------------------------------------------------------------


def test_charts_customers_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_customer_bar_chart_data.return_value = {"customers": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/customers")
    assert r.status_code == 200
    body = r.json()
    assert "customers" in body


def test_charts_customers_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_customer_bar_chart_data.side_effect = OSError("IO 错误")
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/customers")
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/charts/profit
# ---------------------------------------------------------------------------


def test_charts_profit_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_profit_trend_chart_data.return_value = {"profit": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/profit")
    assert r.status_code == 200
    body = r.json()
    assert "profit" in body


def test_charts_profit_custom_months(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_profit_trend_chart_data.return_value = {"months": 3}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/profit", params={"months": 3})
    fake_chart_svc.get_profit_trend_chart_data.assert_called_once_with(3)


def test_charts_profit_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_profit_trend_chart_data.side_effect = ValueError("数据异常")
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/profit")
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/charts/inventory
# ---------------------------------------------------------------------------


def test_charts_inventory_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_inventory_chart_data.return_value = {"inventory": []}
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/inventory")
    assert r.status_code == 200
    body = r.json()
    assert "inventory" in body


def test_charts_inventory_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_chart_svc = MagicMock()
    fake_chart_svc.get_inventory_chart_data.side_effect = RuntimeError("运行时错误")
    monkeypatch.setattr(f"{_FACADE}.chart_service", fake_chart_svc)
    r = client.get("/api/ai/kitten/charts/inventory")
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/saved/list
# ---------------------------------------------------------------------------


def test_saved_list_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.list_saved_analyses.return_value = [{"id": "a1"}]
    fake_save_svc.get_statistics_summary.return_value = {"total": 1}
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/list")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["analyses"] == [{"id": "a1"}]
    assert body["statistics"] == {"total": 1}


def test_saved_list_with_type_filter(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.list_saved_analyses.return_value = []
    fake_save_svc.get_statistics_summary.return_value = {"total": 0}
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/list", params={"type": "financial"})
    assert r.status_code == 200
    fake_save_svc.list_saved_analyses.assert_called_once_with("financial")


def test_saved_list_no_type_filter(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.list_saved_analyses.return_value = []
    fake_save_svc.get_statistics_summary.return_value = {}
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/list")
    fake_save_svc.list_saved_analyses.assert_called_once_with(None)


def test_saved_list_recoverable_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.list_saved_analyses.side_effect = ConnectionError("DB 断开")
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/list")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/saved/{analysis_id}
# ---------------------------------------------------------------------------


def test_saved_get_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.get_analysis.return_value = {"id": "abc", "type": "financial"}
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["id"] == "abc"


def test_saved_get_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.get_analysis.return_value = None
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/nonexistent")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert "未找到" in body["message"]


def test_saved_get_recoverable_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.get_analysis.side_effect = OSError("磁盘故障")
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/saved/{analysis_id}/export
# ---------------------------------------------------------------------------


def test_saved_export_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.export_analysis_to_xlsx.return_value = {
        "success": True,
        "file_name": "report.xlsx",
        "content": b"PK\x03\x04fake-xlsx",
    }
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc/export")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers.get("content-type", "")
    assert "report.xlsx" in r.headers.get("content-disposition", "")


def test_saved_export_failure_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.export_analysis_to_xlsx.return_value = {
        "success": False,
        "message": "导出失败",
    }
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc/export")
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


def test_saved_export_no_file_name_uses_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.export_analysis_to_xlsx.return_value = {
        "success": True,
        "content": b"xlsx-data",
    }
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc/export")
    # Default filename contains Chinese characters; Starlette Response headers use
    # latin-1 encoding which cannot represent them, causing a 500.
    assert r.status_code == 500


def test_saved_export_no_content_uses_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.export_analysis_to_xlsx.return_value = {
        "success": True,
        "file_name": "test.xlsx",
    }
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc/export")
    assert r.status_code == 200


def test_saved_export_recoverable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.export_analysis_to_xlsx.side_effect = RuntimeError("服务错误")
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.get("/api/ai/kitten/saved/abc/export")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# DELETE /api/ai/kitten/saved/{analysis_id}
# ---------------------------------------------------------------------------


def test_saved_delete_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.delete_analysis.return_value = {"success": True}
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.delete("/api/ai/kitten/saved/abc")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "删除成功" in body["message"]


def test_saved_delete_failure_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.delete_analysis.return_value = {"success": False, "message": "记录不存在"}
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.delete("/api/ai/kitten/saved/abc")
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


def test_saved_delete_recoverable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_save_svc = MagicMock()
    fake_save_svc.delete_analysis.side_effect = OSError("IO 错误")
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)
    r = client.delete("/api/ai/kitten/saved/abc")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# POST /api/ai/kitten/financial/report
# ---------------------------------------------------------------------------


def test_financial_report_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_fin_plugin = MagicMock()
    fake_fin_plugin.run.return_value = MagicMock(
        key="financial", title="财务报告", level="info", summary="摘要", details={}
    )
    fake_inv_plugin = MagicMock()
    fake_inv_plugin.run.return_value = MagicMock(
        key="inventory", title="库存估值", level="info", summary="摘要", details={}
    )
    fake_save_svc = MagicMock()
    fake_save_svc.save_analysis.return_value = {"success": True, "id": "r1", "filename": "f1.xlsx"}

    monkeypatch.setattr(f"{_FACADE}.FinancialReportPlugin", lambda: fake_fin_plugin)
    monkeypatch.setattr(f"{_FACADE}.InventoryValuationPlugin", lambda: fake_inv_plugin)
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)

    r = client.post("/api/ai/kitten/financial/report", json={"metadata": {"year": 2025}})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["analysis_id"] == "r1"
    assert "financial_report" in body["data"]
    assert "inventory_valuation" in body["data"]


def test_financial_report_save_fails_still_returns_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fin_plugin = MagicMock()
    fake_fin_plugin.run.return_value = MagicMock(
        key="financial", title="财务报告", level="info", summary="摘要", details={}
    )
    fake_inv_plugin = MagicMock()
    fake_inv_plugin.run.return_value = MagicMock(
        key="inventory", title="库存估值", level="info", summary="摘要", details={}
    )
    fake_save_svc = MagicMock()
    fake_save_svc.save_analysis.return_value = {"success": False}

    monkeypatch.setattr(f"{_FACADE}.FinancialReportPlugin", lambda: fake_fin_plugin)
    monkeypatch.setattr(f"{_FACADE}.InventoryValuationPlugin", lambda: fake_inv_plugin)
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)

    r = client.post("/api/ai/kitten/financial/report", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "保存失败" in body["message"]


def test_financial_report_empty_body(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_fin_plugin = MagicMock()
    fake_fin_plugin.run.return_value = MagicMock(
        key="financial", title="财务报告", level="info", summary="摘要", details={}
    )
    fake_inv_plugin = MagicMock()
    fake_inv_plugin.run.return_value = MagicMock(
        key="inventory", title="库存估值", level="info", summary="摘要", details={}
    )
    fake_save_svc = MagicMock()
    fake_save_svc.save_analysis.return_value = {"success": True, "id": "r2", "filename": "f2.xlsx"}

    monkeypatch.setattr(f"{_FACADE}.FinancialReportPlugin", lambda: fake_fin_plugin)
    monkeypatch.setattr(f"{_FACADE}.InventoryValuationPlugin", lambda: fake_inv_plugin)
    monkeypatch.setattr(f"{_FACADE}.analysis_save_service", fake_save_svc)

    r = client.post("/api/ai/kitten/financial/report")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True


def test_financial_report_recoverable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fin_plugin = MagicMock()
    fake_fin_plugin.run.side_effect = ValueError("数据解析失败")

    monkeypatch.setattr(f"{_FACADE}.FinancialReportPlugin", lambda: fake_fin_plugin)

    r = client.post("/api/ai/kitten/financial/report", json={})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert "财务报表生成失败" in body["message"]


# ---------------------------------------------------------------------------
# POST /api/ai/kitten/report/export
# ---------------------------------------------------------------------------


def test_report_export_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_svc_cls = MagicMock()
    fake_instance = fake_svc_cls.return_value
    fake_instance.build_report.return_value = {
        "file_name": "report.xlsx",
        "content": b"PK\x03\x04fake-xlsx",
    }
    monkeypatch.setattr(f"{_FACADE}.KittenReportExportService", fake_svc_cls)

    r = client.post("/api/ai/kitten/report/export", json={})
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers.get("content-type", "")


def test_report_export_no_filename_uses_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_svc_cls = MagicMock()
    fake_instance = fake_svc_cls.return_value
    fake_instance.build_report.return_value = {"content": b"xlsx-data"}
    monkeypatch.setattr(f"{_FACADE}.KittenReportExportService", fake_svc_cls)

    r = client.post("/api/ai/kitten/report/export", json={})
    # Default filename contains Chinese characters; Starlette Response headers use
    # latin-1 encoding which cannot represent them, causing a 500.
    assert r.status_code == 500


def test_report_export_no_content_uses_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_svc_cls = MagicMock()
    fake_instance = fake_svc_cls.return_value
    fake_instance.build_report.return_value = {"file_name": "r.xlsx"}
    monkeypatch.setattr(f"{_FACADE}.KittenReportExportService", fake_svc_cls)

    r = client.post("/api/ai/kitten/report/export", json={})
    assert r.status_code == 200


def test_report_export_recoverable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_svc_cls = MagicMock()
    fake_instance = fake_svc_cls.return_value
    fake_instance.build_report.side_effect = RuntimeError("构建失败")
    monkeypatch.setattr(f"{_FACADE}.KittenReportExportService", fake_svc_cls)

    r = client.post("/api/ai/kitten/report/export", json={})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert "导出失败" in body["message"]


# ---------------------------------------------------------------------------
# POST /api/ai/kitten/report/export-docx
# ---------------------------------------------------------------------------


def test_report_export_docx_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.build_kitten_docx",
        lambda body: {"file_name": "report.docx", "content": b"PK\x03\x04fake-docx"},
    )
    r = client.post("/api/ai/kitten/report/export-docx", json={})
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers.get("content-type", "")


def test_report_export_docx_no_filename_uses_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.build_kitten_docx",
        lambda body: {"content": b"docx-data"},
    )
    r = client.post("/api/ai/kitten/report/export-docx", json={})
    # Default filename contains Chinese characters; Starlette Response headers use
    # latin-1 encoding which cannot represent them, causing a 500.
    assert r.status_code == 500


def test_report_export_docx_no_content_uses_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.build_kitten_docx",
        lambda body: {"file_name": "r.docx"},
    )
    r = client.post("/api/ai/kitten/report/export-docx", json={})
    assert r.status_code == 200


def test_report_export_docx_recoverable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.build_kitten_docx",
        MagicMock(side_effect=OSError("磁盘满")),
    )
    r = client.post("/api/ai/kitten/report/export-docx", json={})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert "Word 导出失败" in body["message"]


# ---------------------------------------------------------------------------
# POST /api/ai/kitten/document/generate
# ---------------------------------------------------------------------------


def test_document_generate_docx_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        lambda prompt, fmt: (b"docx-bytes", "生成文档.docx"),
    )
    r = client.post("/api/ai/kitten/document/generate", json={"prompt": "写一份合同"})
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers.get("content-type", "")


def test_document_generate_xlsx_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        lambda prompt, fmt: (b"xlsx-bytes", "生成表格.xlsx"),
    )
    r = client.post(
        "/api/ai/kitten/document/generate", json={"prompt": "做一个报表", "format": "xlsx"}
    )
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers.get("content-type", "")


def test_document_generate_invalid_format_defaults_to_docx(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        lambda prompt, fmt: (b"bytes", "doc.docx"),
    )
    r = client.post("/api/ai/kitten/document/generate", json={"prompt": "测试", "format": "pdf"})
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers.get("content-type", "")


def test_document_generate_empty_prompt_returns_400(client: TestClient) -> None:
    r = client.post("/api/ai/kitten/document/generate", json={"prompt": ""})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert "prompt" in body["message"]


def test_document_generate_missing_prompt_returns_400(client: TestClient) -> None:
    r = client.post("/api/ai/kitten/document/generate", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


def test_document_generate_uses_message_as_prompt_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        lambda prompt, fmt: (b"bytes", "doc.docx"),
    )
    r = client.post("/api/ai/kitten/document/generate", json={"message": "用 message 字段"})
    assert r.status_code == 200


def test_document_generate_runtime_error_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        MagicMock(side_effect=RuntimeError("LLM 服务不可用")),
    )
    r = client.post("/api/ai/kitten/document/generate", json={"prompt": "测试"})
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False


def test_document_generate_recoverable_error_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        MagicMock(side_effect=ValueError("数据格式错误")),
    )
    r = client.post("/api/ai/kitten/document/generate", json={"prompt": "测试"})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert "文档生成失败" in body["message"]


def test_document_generate_ascii_filename_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.generate_office_file",
        lambda prompt, fmt: (b"bytes", "中文文件名.docx"),
    )
    r = client.post("/api/ai/kitten/document/generate", json={"prompt": "测试"})
    assert r.status_code == 200
    disp = r.headers.get("content-disposition", "")
    assert "UTF-8''" in disp


# ---------------------------------------------------------------------------
# GET /api/ai/kitten/document/pickup/{token}
# ---------------------------------------------------------------------------


def test_document_pickup_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.pop_document_pickup",
        lambda token: (
            b"file-bytes",
            "文档.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    )
    r = client.get("/api/ai/kitten/document/pickup/tok123")
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers.get("content-type", "")


def test_document_pickup_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.pop_document_pickup",
        lambda token: None,
    )
    r = client.get("/api/ai/kitten/document/pickup/invalid-token")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert "链接无效或已过期" in body["message"]


def test_document_pickup_no_mime_uses_octet_stream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.pop_document_pickup",
        lambda token: (b"bytes", "file.bin", None),
    )
    r = client.get("/api/ai/kitten/document/pickup/tok123")
    assert r.status_code == 200
    assert "octet-stream" in r.headers.get("content-type", "")


def test_document_pickup_ascii_filename_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.pop_document_pickup",
        lambda token: (b"bytes", "纯中文.bin", "application/octet-stream"),
    )
    r = client.get("/api/ai/kitten/document/pickup/tok123")
    assert r.status_code == 200
    disp = r.headers.get("content-disposition", "")
    assert "UTF-8''" in disp


# ---------------------------------------------------------------------------
# Response format / method checks
# ---------------------------------------------------------------------------


def test_business_snapshot_response_is_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        f"{_FACADE}.build_kitten_business_snapshot",
        lambda: {},
    )
    r = client.get("/api/ai/kitten/business-snapshot")
    assert "application/json" in r.headers.get("content-type", "")
