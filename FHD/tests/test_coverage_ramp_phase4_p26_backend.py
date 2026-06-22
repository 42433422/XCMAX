"""COVERAGE_RAMP Phase 4 round 26: tools_workflow_registered 深路径 + execute dispatcher."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.tools_workflow_registered import (
    _registered_router_business_docking_family,
    _registered_router_customers,
    _registered_router_excel_analysis,
    _registered_router_excel_import,
    _registered_router_materials,
    _registered_router_normal_slot_dispatch,
    _registered_router_print,
    _registered_router_printer_list,
    _registered_router_products,
    _registered_router_settings,
    _registered_router_shipment_records,
    _registered_router_template_preview,
    _registered_router_wechat,
    execute_registered_workflow_tool,
)

# ---------------------------------------------------------------------------
# execute_registered_workflow_tool
# ---------------------------------------------------------------------------


def test_execute_registered_unknown_tool() -> None:
    out = execute_registered_workflow_tool("not_a_tool", "view", {})
    assert out["success"] is False
    assert "未注册" in out["message"]


@patch("app.application.normal_chat_dispatch.run_normal_slot_shipment_preview")
def test_execute_registered_normal_slot_via_dispatcher(mock_run: MagicMock) -> None:
    mock_run.return_value = {"success": True}
    out = execute_registered_workflow_tool(
        "normal_slot_dispatch",
        "shipment_preview",
        {"_runtime_context": {"message": "订单预览"}},
    )
    assert out["success"] is True


# ---------------------------------------------------------------------------
# normal_slot_dispatch
# ---------------------------------------------------------------------------


def test_normal_slot_unknown_action() -> None:
    out = _registered_router_normal_slot_dispatch("unknown", {}, {}, "normal", "")
    assert out["success"] is False


@patch("app.application.normal_chat_dispatch.run_normal_slot_shipment_preview")
def test_normal_slot_shipment_preview(mock_run: MagicMock) -> None:
    mock_run.return_value = {"success": True, "preview": True}
    out = _registered_router_normal_slot_dispatch(
        "shipment_preview", {"order_text": "单号1"}, {}, "pro", ""
    )
    assert out["success"] is True
    mock_run.assert_called_once_with("单号1")


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------


@patch("app.application.get_customer_app_service")
def test_customers_ensure_exists_already_matched(mock_get: MagicMock) -> None:
    matched = SimpleNamespace(unit_name="七彩乐园")
    mock_get.return_value.match_purchase_unit.return_value = matched
    out = _registered_router_customers("ensure_exists", {"unit_name": "七彩"}, {}, "pro", "")
    assert out["success"] is True
    assert out["exists"] is True


@patch("app.application.get_customer_app_service")
def test_customers_ensure_exists_creates(mock_get: MagicMock) -> None:
    svc = mock_get.return_value
    svc.match_purchase_unit.return_value = None
    svc.create.return_value = {"success": True}
    out = _registered_router_customers("ensure_exists", {"unit_name": "新单位"}, {}, "pro", "")
    assert out["success"] is True
    assert out.get("created") is True


@patch("app.application.get_customer_app_service")
def test_customers_ensure_exists_duplicate_message(mock_get: MagicMock) -> None:
    svc = mock_get.return_value
    svc.match_purchase_unit.return_value = None
    svc.create.return_value = {"success": False, "message": "客户已存在"}
    out = _registered_router_customers("ensure_exists", {"unit_name": "重复"}, {}, "pro", "")
    assert out["success"] is True
    assert out["exists"] is True


def test_customers_ensure_exists_missing_name() -> None:
    out = _registered_router_customers("ensure_exists", {}, {}, "pro", "")
    assert out["success"] is False


@patch("app.application.get_customer_app_service")
def test_customers_create_failure(mock_get: MagicMock) -> None:
    mock_get.return_value.create.return_value = {"success": False, "message": "失败"}
    out = _registered_router_customers("create", {"unit_name": "甲"}, {}, "pro", "")
    assert out["success"] is False


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


@patch("app.services.get_products_service")
def test_products_exists_by_model(mock_get: MagicMock) -> None:
    mock_get.return_value.get_products.return_value = {
        "success": True,
        "data": [{"model_number": "9803", "name": "产品A"}],
    }
    out = _registered_router_products(
        "exists",
        {"unit_name": "甲", "model_number": "9803"},
        {},
        "pro",
        "",
    )
    assert out["success"] is True
    assert out["exists"] is True


@patch("app.services.get_products_service")
def test_products_create_missing_fields(mock_get: MagicMock) -> None:
    out = _registered_router_products("create", {}, {}, "pro", "")
    assert out["success"] is False
    mock_get.return_value.create_product.assert_not_called()


@patch("app.services.get_products_service")
def test_products_create_success(mock_get: MagicMock) -> None:
    mock_get.return_value.create_product.return_value = {"success": True}
    out = _registered_router_products(
        "create",
        {"unit_name": "甲", "model_number": "9803", "unit_price": "12.5"},
        {},
        "pro",
        "",
    )
    assert out["success"] is True
    assert out.get("created") is True


# ---------------------------------------------------------------------------
# materials / shipment / business_docking / template_preview
# ---------------------------------------------------------------------------


@patch("app.application.get_material_application_service")
def test_materials_list_query(mock_get: MagicMock) -> None:
    mock_get.return_value.get_all_materials.return_value = {"success": True, "data": []}
    out = _registered_router_materials("query", {"keyword": "铜"}, {}, "pro", "")
    assert out["success"] is True


@patch("app.application.get_material_application_service")
def test_materials_batch_delete(mock_get: MagicMock) -> None:
    mock_get.return_value.batch_delete_materials.return_value = {"success": True}
    out = _registered_router_materials("batch_delete", {"ids": [1, 2]}, {}, "pro", "")
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
def test_shipment_records_update(mock_get: MagicMock) -> None:
    mock_get.return_value.update_shipment_record.return_value = {"success": True}
    out = _registered_router_shipment_records("update", {"id": 5, "status": "done"}, {}, "pro", "")
    assert out["success"] is True


@patch("app.bootstrap.get_shipment_app_service")
def test_shipment_records_export(mock_get: MagicMock) -> None:
    mock_get.return_value.export_shipment_records.return_value = {"success": True}
    out = _registered_router_shipment_records("export", {"unit_name": "甲"}, {}, "pro", "")
    assert out["success"] is True


def test_business_docking_view_redirect() -> None:
    out = _registered_router_business_docking_family("view", {}, {}, "pro", "")
    assert "business-docking" in out["redirect"]


def test_business_docking_missing_file() -> None:
    out = _registered_router_business_docking_family("extract", {"file_path": ""}, {}, "pro", "")
    assert out["success"] is False


def test_template_preview_view() -> None:
    out = _registered_router_template_preview("view", {}, {}, "pro", "")
    assert "template-preview" in out["redirect"]


@patch("app.application.get_template_app_service")
def test_template_preview_list(mock_get: MagicMock) -> None:
    mock_get.return_value.get_templates.return_value = [{"id": 1}]
    out = _registered_router_template_preview("list", {}, {}, "pro", "")
    assert out["success"] is True


# ---------------------------------------------------------------------------
# wechat / print / printer_list / settings
# ---------------------------------------------------------------------------


@patch("app.application.get_wechat_contact_app_service")
def test_wechat_view_redirect(mock_get: MagicMock) -> None:
    out = _registered_router_wechat("view", {}, {}, "pro", "")
    assert "wechat-contacts" in out["redirect"]


@patch("app.services.get_printer_service")
def test_print_list_printers(mock_get: MagicMock) -> None:
    mock_get.return_value.get_printers.return_value = {"success": True, "data": []}
    out = _registered_router_print("list", {}, {}, "pro", "")
    assert out["success"] is True


@patch("app.services.get_printer_service")
def test_print_document(mock_get: MagicMock) -> None:
    mock_get.return_value.print_document.return_value = {"success": True}
    out = _registered_router_print(
        "print_document",
        {"file_path": "/tmp/a.pdf", "printer_name": "HP"},
        {},
        "pro",
        "",
    )
    assert out["success"] is True


@patch("app.services.get_system_service")
def test_printer_list_set_default(mock_get: MagicMock) -> None:
    mock_get.return_value.set_default_printer.return_value = {"success": True}
    out = _registered_router_printer_list("set_default", {"printer_name": "HP"}, {}, "pro", "")
    assert out["success"] is True


@patch("app.services.get_system_service")
def test_settings_enable_startup(mock_get: MagicMock) -> None:
    mock_get.return_value.enable_startup.return_value = {"success": True}
    out = _registered_router_settings("enable_startup", {}, {}, "pro", "")
    assert out["success"] is True


# ---------------------------------------------------------------------------
# excel_analysis / excel_import
# ---------------------------------------------------------------------------


def test_excel_analysis_missing_file_path() -> None:
    out = _registered_router_excel_analysis("analyze", {}, {}, "pro", "")
    assert out["success"] is False


def test_excel_analysis_read_from_runtime_context() -> None:
    mock_skill = MagicMock()
    mock_skill.execute.return_value = {"success": True, "content": []}
    with (
        patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_skill,
        ),
        patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=MagicMock(),
        ),
    ):
        out = _registered_router_excel_analysis(
            "read",
            {},
            {"excel_analysis": {"file_path": "/tmp/x.xlsx"}},
            "pro",
            "",
        )
    assert out["success"] is True


def test_excel_analysis_statistics() -> None:
    mock_tk = MagicMock()
    mock_tk.execute.return_value = {
        "success": True,
        "content": [{"cells": [{"value": "1"}, {"value": "2"}]}],
        "row_count": 1,
    }
    with (
        patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_tk,
        ),
        patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=MagicMock(),
        ),
    ):
        out = _registered_router_excel_analysis(
            "statistics", {"file_path": "/tmp/x.xlsx"}, {}, "pro", ""
        )
    assert out["success"] is True
    assert out["statistics"]["sum"] == 3.0


def test_excel_import_missing_pending_id() -> None:
    out = _registered_router_excel_import("execute_import", {}, {}, "pro", "")
    assert out["success"] is False


@patch("app.application.get_ai_chat_app_service")
def test_excel_import_no_pending_data(mock_ai: MagicMock) -> None:
    mock_ai.return_value._pending_excel_imports = {}
    out = _registered_router_excel_import(
        "execute_import", {"pending_import_id": "missing"}, {}, "pro", ""
    )
    assert out["success"] is False


@patch("app.bootstrap.get_products_service")
@patch("app.bootstrap.get_customer_app_service")
@patch("app.application.get_ai_chat_app_service")
def test_excel_import_success(
    mock_ai: MagicMock, mock_cust: MagicMock, mock_prod: MagicMock
) -> None:
    pending = {
        "p1": {
            "records": [
                {
                    "unit_name": "甲",
                    "product_name": "产品",
                    "model_number": "9803",
                    "unit_price": 10,
                }
            ]
        }
    }
    ai_svc = mock_ai.return_value
    ai_svc._pending_excel_imports = dict(pending)
    cust = mock_cust.return_value
    cust.match_purchase_unit.return_value = None
    cust.create.return_value = {"success": True}
    prod = mock_prod.return_value
    prod.get_products.return_value = {"success": True, "data": []}
    prod.create_product.return_value = {"success": True}
    out = _registered_router_excel_import(
        "execute_import", {"pending_import_id": "p1"}, {}, "pro", ""
    )
    assert out["success"] is True
    assert ai_svc._pending_excel_imports == {}


# ---------------------------------------------------------------------------
# legacy_chat_adapter pure helpers
# ---------------------------------------------------------------------------


def test_resolve_chat_model_for_client_modstore() -> None:
    from app.legacy.chat.legacy_chat_adapter import _resolve_chat_model_for_client

    client = SimpleNamespace(
        is_modstore_openai_compatible=True,
        default_model="deepseek-chat",
        default_provider="deepseek",
    )
    assert _resolve_chat_model_for_client(client, None) == "deepseek/deepseek-chat"
    assert _resolve_chat_model_for_client(None, "explicit") == "explicit"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
