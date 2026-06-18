"""Tests for app.services.tools_payload_legacy — coverage ramp for uncovered branches."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.tools_payload_legacy import dispatch_legacy_tool_payload


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
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "products",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True

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
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "chat",
                "open",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


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
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "ai_ecosystem",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


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
        assert result["_response"]["success"] is True

    def test_generate_action_with_mock(self):
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
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "orders",
                "query",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True

    def test_view_action(self):
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
        assert result["_response"]["success"] is True


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
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "print",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= printer_list tool =============================


class TestPrinterListTool:
    def test_other_action(self):
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
        assert result["_response"]["success"] is True


# ========================= materials tool ================================


class TestMaterialsTool:
    def test_other_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "materials",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= ocr tool ======================================


class TestOcrTool:
    def test_scan_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "ocr",
                "scan",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True

    def test_other_action(self):
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
        assert result["_response"]["success"] is True


# ========================= wechat tool ===================================


class TestWechatTool:
    def test_contacts_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "wechat",
                "contacts",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True

    def test_other_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "wechat",
                "other",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= excel_decompose tool ==========================


class TestExcelDecomposeTool:
    def test_decompose_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "excel_decompose",
                "decompose",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= excel_analyzer tool ===========================


class TestExcelAnalyzerTool:
    def test_analyze_no_file_path(self):
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
        assert result["_response"]["success"] is False


# ========================= template_extract tool =========================


class TestTemplateExtractTool:
    def test_view_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "template_extract",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True

    def test_no_file_path(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "template_extract",
                "extract",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is False


# ========================= excel_toolkit tool ============================


class TestExcelToolkitTool:
    def test_no_file_path(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "excel_toolkit",
                "toolkit",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is False


# ========================= shipment_template tool ========================


class TestShipmentTemplateTool:
    def test_template_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "shipment_template",
                "template",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= template_preview tool =========================


class TestTemplatePreviewTool:
    def test_preview_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "template_preview",
                "preview",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= settings tool =================================


class TestSettingsTool:
    def test_view_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "settings",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= tools_table tool ==============================


class TestToolsTableTool:
    def test_list_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "tools_table",
                "list",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= other_tools tool ==============================


class TestOtherToolsTool:
    def test_list_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "other_tools",
                "list",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= database tool =================================


class TestDatabaseTool:
    def test_view_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "database",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= system tool ===================================


class TestSystemTool:
    def test_view_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "system",
                "view",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


# ========================= upload_file tool ==============================


class TestUploadFileTool:
    def test_upload_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "upload_file",
                "upload",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["_response"]["success"] is True


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
        assert result["_response"]["success"] is True

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
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "completely_unknown_tool",
                "any",
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        # Unknown tools return 400
        assert result["_response"]["success"] is False
