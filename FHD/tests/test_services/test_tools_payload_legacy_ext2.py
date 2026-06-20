"""Tests for app.services.tools_payload_legacy — deep coverage for remaining uncovered branches.

Focus: customers tool (delete, supplement, create), shipment_generate, print,
printer_list, materials, wechat, excel_decompose, excel_analyzer, and other
branches not covered by existing tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.tools_payload_legacy import dispatch_legacy_tool_payload


def _json_fn(data, status=200):
    """Pass-through: returns data as-is for testing (ignores status code)."""
    return data


def _hdr_getter(key, default=None):
    return "default_user" if key == "X-User-ID" else default


def _parse_order_text(text):
    return {"success": True, "unit_name": "公司A", "products": []}


def _unwrap(result):
    """Unwrap tuple returns (response, status_code) from dispatch_legacy_tool_payload."""
    if isinstance(result, tuple):
        return result[0]
    return result


# ========================= customers tool - delete ========================


class TestCustomersToolDelete:
    def test_delete_by_id(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 1
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "delete",
                    {"customer_id": "1"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_delete_by_name(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 1
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "delete",
                    {"unit_name": "公司A"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_delete_not_found(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 0
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ):
                result = _unwrap(
                    dispatch_legacy_tool_payload(
                        "customers",
                        "delete",
                        {"unit_name": "不存在公司"},
                        json_response_fn=_json_fn,
                        hdr_getter=_hdr_getter,
                        parse_order_text_fn=_parse_order_text,
                    )
                )
        assert result["success"] is True
        assert result["deleted_count"] == 0

    def test_delete_with_resolve_fallback(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.side_effect = [0, 1]  # First try fails, resolved try succeeds
            mock_resolved = Mock()
            mock_resolved.unit_name = "公司A全称"
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=mock_resolved,
            ):
                result = _unwrap(
                    dispatch_legacy_tool_payload(
                        "customers",
                        "delete",
                        {"unit_name": "公司A"},
                        json_response_fn=_json_fn,
                        hdr_getter=_hdr_getter,
                        parse_order_text_fn=_parse_order_text,
                    )
                )
        assert result["success"] is True

    def test_delete_with_order_text_name_extraction(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 1
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "delete",
                    {"order_text": "删除客户某某公司"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_delete_resolve_error(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 0
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                side_effect=RuntimeError("fail"),
            ):
                result = _unwrap(
                    dispatch_legacy_tool_payload(
                        "customers",
                        "delete",
                        {"unit_name": "公司A"},
                        json_response_fn=_json_fn,
                        hdr_getter=_hdr_getter,
                        parse_order_text_fn=_parse_order_text,
                    )
                )
        assert result["success"] is True


# ========================= customers tool - supplement ====================


class TestCustomersToolSupplement:
    def test_supplement_contact_person(self):
        mock_customer = Mock()
        mock_customer.id = 1
        mock_customer.unit_name = "公司A"
        mock_customer.contact_person = None
        mock_customer.contact_phone = None
        mock_customer.address = None
        with (
            patch("app.services.unified_query_service.query_service") as mock_qs,
            patch("app.db.session.get_db"),
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_qs.get_first.return_value = mock_customer
            mock_ctx_inst = Mock()
            mock_ctx_inst.get_last_customer.return_value = {"customer_name": "公司A"}
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "supplement",
                    {
                        "field_name": "contact_person",
                        "field_value": "张三",
                    },
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_supplement_no_last_customer_no_field(self):
        with patch("app.services.get_task_context_service") as mock_ctx:
            mock_ctx_inst = Mock()
            mock_ctx_inst.get_last_customer.return_value = None
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "supplement",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is False

    def test_supplement_customer_not_found(self):
        with (
            patch("app.services.unified_query_service.query_service") as mock_qs,
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_qs.get_first.return_value = None
            mock_ctx_inst = Mock()
            mock_ctx_inst.get_last_customer.return_value = {"customer_name": "不存在公司"}
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "supplement",
                    {"field_name": "contact_person", "field_value": "张三"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is False


# ========================= customers tool - create ========================


class TestCustomersToolCreate:
    def test_create_with_unit_name_from_params(self):
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "添加",
                    {"unit_name": "新公司"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_create_missing_unit_name(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "customers",
                "添加",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is False

    def test_create_already_exists(self):
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": False, "message": "客户名称已存在"}
        mock_exists = {"id": 1, "contact_person": None, "contact_phone": None, "address": None}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch(
                "app.services.unified_query_service.find_purchase_unit", return_value=mock_exists
            ),
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "添加",
                    {"unit_name": "已存在公司"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_create_with_contact_info_in_unit_name(self):
        """unit_name like '七彩乐园联系人向总' should be truncated."""
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "添加",
                    {"unit_name": "七彩乐园联系人向总"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        # Should truncate at "联系人"
        assert result["success"] is True

    def test_create_with_order_text_extraction(self):
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "添加",
                    {
                        "order_text": "添加客户叫测试公司，联系人是张三，电话13800138000",
                    },
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_create_failed(self):
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": False, "message": "创建失败"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "添加",
                    {"unit_name": "公司A"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is False

    def test_customers_fallback_view(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "customers",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True


# ========================= shipment_generate tool =========================


class TestShipmentGenerateToolDeep:
    def test_generate_with_order_text(self):
        mock_svc = Mock()
        mock_svc.execute.return_value = ({"success": True}, 200)
        with patch(
            "app.services.shipment_number_mode_service.ShipmentNumberModeService",
            return_value=mock_svc,
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_generate",
                    "generate",
                    {"order_text": "给公司A发10桶涂料"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_generate_view(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "shipment_generate",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_generate_exception(self):
        with patch(
            "app.services.shipment_number_mode_service.ShipmentNumberModeService",
            side_effect=RuntimeError("fail"),
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_generate",
                    "generate",
                    {"order_text": "test"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is False


# ========================= print tool ====================================


class TestPrintToolDeep:
    def test_view(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "print",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_list_printers(self):
        mock_svc = Mock()
        mock_svc.get_printers.return_value = {"success": True, "printers": []}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "print",
                    "list",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_print_label(self):
        mock_svc = Mock()
        mock_svc.print_label.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "print",
                    "print_label",
                    {"file_path": "/label.pdf"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_print_document(self):
        mock_svc = Mock()
        mock_svc.print_document.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "print",
                    "print_document",
                    {"file_path": "/doc.pdf"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_test_printer(self):
        mock_svc = Mock()
        mock_svc.test_printer.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "print",
                    "test",
                    {"printer_name": "HP"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_fallback(self):
        mock_svc = Mock()
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "print",
                    "unknown",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True


# ========================= printer_list tool =============================


class TestPrinterListToolDeep:
    def test_list(self):
        mock_svc = Mock()
        mock_svc.get_printer_config.return_value = {"success": True, "printers": []}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "printer_list",
                    "list",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_set_default(self):
        mock_svc = Mock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "printer_list",
                    "set_default",
                    {"printer_name": "HP"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_fallback(self):
        mock_svc = Mock()
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "printer_list",
                    "other",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True


# ========================= materials tool ================================


class TestMaterialsToolDeep:
    def test_view(self):
        mock_svc = Mock()
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "view",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_create(self):
        mock_svc = Mock()
        mock_svc.create_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "create",
                    {"name": "涂料A"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_update(self):
        mock_svc = Mock()
        mock_svc.update_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "update",
                    {"id": "1", "name": "涂料B"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_delete(self):
        mock_svc = Mock()
        mock_svc.delete_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "delete",
                    {"id": "1"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_batch_delete(self):
        mock_svc = Mock()
        mock_svc.batch_delete_materials.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "batch_delete",
                    {"ids": [1, 2, 3]},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_export(self):
        mock_svc = Mock()
        mock_svc.export_to_excel.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "export",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_fallback(self):
        mock_svc = Mock()
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "materials",
                    "unknown",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True


# ========================= ocr tool ======================================


class TestOcrTool:
    def test_view(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "ocr",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_other(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "ocr",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True


# ========================= wechat tool ===================================


class TestWechatToolDeep:
    def test_view(self):
        mock_svc = Mock()
        with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "wechat",
                    "view",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_list(self):
        mock_svc = Mock()
        mock_svc.get_contacts.return_value = []
        with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "wechat",
                    "list",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_refresh_cache(self):
        with patch(
            "app.services.wechat_contact_cache_import.ensure_decrypted_wechat_dbs",
            return_value={"success": True},
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "wechat",
                    "refresh_contact_cache",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_fallback(self):
        mock_svc = Mock()
        with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "wechat",
                    "unknown",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True


# ========================= excel_decompose tool ==========================


class TestExcelDecomposeToolDeep:
    def test_view(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "excel_decompose",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_other(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "excel_decompose",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True


# ========================= excel_analyzer tool ===========================


class TestExcelAnalyzerToolDeep:
    def test_missing_file_path(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "excel_analyzer",
                "analyze",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is False

    def test_with_file_path(self):
        mock_skill = Mock()
        mock_skill.execute.return_value = {"success": True, "fields": []}
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_skill,
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "excel_analyzer",
                    "analyze",
                    {"file_path": "/test.xlsx"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True


# ========================= orders tool ===================================


class TestOrdersTool:
    def test_view(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "orders",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_other(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "orders",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True


# ========================= shipment_records tool - extended ===============


class TestShipmentRecordsToolDeep:
    def test_update(self):
        mock_svc = Mock()
        mock_svc.update_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_records",
                    "update",
                    {"id": "1", "status": "shipped"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_delete(self):
        mock_svc = Mock()
        mock_svc.delete_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_records",
                    "delete",
                    {"id": "1"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_export(self):
        mock_svc = Mock()
        mock_svc.export_shipment_records.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_records",
                    "export",
                    {"unit": "公司A"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_fallback(self):
        mock_svc = Mock()
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_records",
                    "unknown",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True


# ========================= business_docking tool =========================


class TestBusinessDockingToolDeep:
    def test_missing_file_path(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "business_docking",
                "extract",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is False

    def test_file_not_exists(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "business_docking",
                "extract",
                {"file_path": "/nonexistent.xlsx"},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is False

    def test_fallback(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "business_docking",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True


# ========================= products tool - extended =======================


class TestProductsToolDeep:
    def test_no_keyword_no_search(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "products",
                "执行",
                {"action": "view"},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_fallback_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "products",
                "unknown",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True
