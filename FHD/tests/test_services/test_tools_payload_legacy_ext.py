"""Tests for app.domain.shared_services.tools_payload_legacy — coverage ramp for uncovered branches."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.domain.shared_services.tools_payload_legacy import dispatch_legacy_tool_payload


def _assert_shared_view_action_0(self, _shared_literal_0, _shared_literal_1, _shared_literal_2):
    result = _unwrap(
        dispatch_legacy_tool_payload(
            _shared_literal_1,
            _shared_literal_2,
            {},
            json_response_fn=_json_fn,
            hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        )
    )
    assert result["_response"]["success"] is _shared_literal_0


def _json_fn(data, status=200):
    return {"_response": data, "_status": status}


def _hdr_getter(key):
    return None


def _parse_order_text(text):
    return {"order_text": text}


def _unwrap(result):
    """Handle both _j(...) and (_j(...), status) return patterns."""
    if isinstance(result, tuple):
        return {"_response": result[0], "_status": result[1]}
    return result


# ========================= products tool =================================


class TestProductsTool:
    def test_search_with_keyword(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "products",
                "search",
                {"keyword": "涂料"},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True
        assert "涂料" in result["_response"]["redirect"]

    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "products", "view")

    def test_exec_action_with_view_sub(self):
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
        assert result["_response"]["success"] is True


# ========================= chat tool =====================================


class TestChatTool:
    def test_chat_action(self):
        return _assert_shared_view_action_0(self, True, "chat", "open")


# ========================= ai_ecosystem tool ==============================


class TestAiEcosystemTool:
    def test_list_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "ai_ecosystem",
                "list",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True
        assert "data" in result["_response"]

    def test_other_action(self):
        return _assert_shared_view_action_0(self, True, "ai_ecosystem", "other")


# ========================= materials_list tool ===========================


class TestMaterialsListTool:
    def test_other_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "materials_list",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True
        assert "redirect" in result["_response"]


# ========================= shipment_records tool =========================


class TestShipmentRecordsTool:
    def test_view_action(self):
        mock_svc = Mock()
        mock_svc.get_shipment_records.return_value = []
        with patch(
            "app.bootstrap.get_shipment_app_service",
            return_value=mock_svc,
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_records",
                    "view",
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["_response"]["success"] is True


# ========================= shipment_generate tool ========================


class TestShipmentGenerateTool:
    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "shipment_generate", "view")

    def test_generate_action_with_mock(self):
        mock_svc = Mock()
        mock_svc.execute.return_value = ({"success": True}, 200)
        with patch(
            "app.domain.shared_services.shipment_number_mode_service.ShipmentNumberModeService",
            return_value=mock_svc,
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "shipment_generate",
                    "generate",
                    {"unit_name": "公司A"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["_response"]["success"] is True


# ========================= orders tool ===================================


class TestOrdersTool:
    def test_query_action(self):
        return _assert_shared_view_action_0(self, True, "orders", "query")

    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "orders", "view")


# ========================= print tool ====================================


class TestPrintTool:
    def test_print_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "print",
                "print",
                {"template_id": 1},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True

    def test_other_action(self):
        return _assert_shared_view_action_0(self, True, "print", "other")


# ========================= printer_list tool =============================


class TestPrinterListTool:
    def test_other_action(self):
        return _assert_shared_view_action_0(self, True, "printer_list", "other")


# ========================= materials tool ================================


class TestMaterialsTool:
    def test_other_action(self):
        return _assert_shared_view_action_0(self, True, "materials", "other")


# ========================= ocr tool ======================================


class TestOcrTool:
    def test_scan_action(self):
        return _assert_shared_view_action_0(self, True, "ocr", "scan")

    def test_other_action(self):
        return _assert_shared_view_action_0(self, True, "ocr", "other")


# ========================= excel_decompose tool ==========================


class TestExcelDecomposeTool:
    def test_decompose_action(self):
        return _assert_shared_view_action_0(self, True, "excel_decompose", "decompose")


# ========================= excel_analyzer tool ===========================


class TestExcelAnalyzerTool:
    def test_analyze_no_file_path(self):
        return _assert_shared_view_action_0(self, False, "excel_analyzer", "analyze")


# ========================= template_extract tool =========================


class TestTemplateExtractTool:
    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "template_extract", "view")

    def test_no_file_path(self):
        return _assert_shared_view_action_0(self, False, "template_extract", "extract")


# ========================= excel_toolkit tool ============================


class TestExcelToolkitTool:
    def test_no_file_path(self):
        return _assert_shared_view_action_0(self, False, "excel_toolkit", "toolkit")


# ========================= shipment_template tool ========================


class TestShipmentTemplateTool:
    def test_template_action(self):
        return _assert_shared_view_action_0(self, True, "shipment_template", "template")


# ========================= template_preview tool =========================


class TestTemplatePreviewTool:
    def test_preview_action(self):
        return _assert_shared_view_action_0(self, True, "template_preview", "preview")


# ========================= settings tool =================================


class TestSettingsTool:
    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "settings", "view")


# ========================= tools_table tool ==============================


class TestToolsTableTool:
    def test_list_action(self):
        return _assert_shared_view_action_0(self, True, "tools_table", "list")


# ========================= other_tools tool ==============================


class TestOtherToolsTool:
    def test_list_action(self):
        return _assert_shared_view_action_0(self, True, "other_tools", "list")


# ========================= database tool =================================


class TestDatabaseTool:
    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "database", "view")


# ========================= system tool ===================================


class TestSystemTool:
    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "system", "view")


# ========================= upload_file tool ==============================


class TestUploadFileTool:
    def test_upload_action(self):
        return _assert_shared_view_action_0(self, True, "upload_file", "upload")


# ========================= customers - extended ==========================


class TestCustomersToolExtended:
    def test_search_with_keyword(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "customers",
                "search",
                {"keyword": "公司A"},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True
        assert "公司A" in result["_response"].get("redirect", "")

    def test_view_action(self):
        return _assert_shared_view_action_0(self, True, "customers", "view")

    def test_add_action_missing_unit_name(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "customers",
                "add",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        # Should fail because no unit_name
        assert result["_response"]["success"] is False or result["_status"] == 400


# ========================= unknown tool ==================================


class TestUnknownTool:
    def test_unknown_tool_id(self):
        return _assert_shared_view_action_0(self, False, "completely_unknown_tool", "any")
