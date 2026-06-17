"""Tests for app.services.tools_payload_legacy — uncovered branches (ext3).

Focus: template_extract tool, excel_toolkit tool, shipment_template tool,
template_preview tool, settings tool, tools_table tool, other_tools tool,
database tool, system tool, upload_file tool, unknown tool, customers search
with keyword from params, customers view with add/del verbs, ai_ecosystem tool,
materials_list tool, business_docking with valid file, and shipment_records list.
"""

from __future__ import annotations

import os
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


# ========================= template_extract tool ==========================


class TestTemplateExtractTool:
    def test_view_action(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "template_extract", "view", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_none_action(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "template_extract", None, {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_empty_action(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "template_extract", "", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_missing_file_path(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "template_extract", "extract", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is False

    def test_file_not_exists(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "template_extract", "extract", {"file_path": "/nonexistent.xlsx"},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is False

    def test_recoverable_error(self, tmp_path):
        xlsx_path = str(tmp_path / "test.xlsx")
        with open(xlsx_path, "w") as f:
            f.write("fake")

        with (
            patch("os.path.exists", return_value=True),
            patch("app.services.document_templates_service._list_excel_sheet_names", side_effect=RuntimeError("fail")),
        ):
            result = _unwrap(dispatch_legacy_tool_payload(
                "template_extract", "extract", {"file_path": xlsx_path},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False


# ========================= excel_toolkit tool ==============================


class TestExcelToolkitTool:
    def test_missing_file_path(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "excel_toolkit", "view", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is False

    def test_import_error(self):
        with patch.dict("sys.modules", {"app.infrastructure.skills.excel_toolkit.excel_toolkit": None}):
            result = _unwrap(dispatch_legacy_tool_payload(
                "excel_toolkit", "view", {"file_path": "/test.xlsx"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False

    def test_recoverable_error(self):
        with (
            patch("app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill", side_effect=RuntimeError("fail")),
        ):
            result = _unwrap(dispatch_legacy_tool_payload(
                "excel_toolkit", "view", {"file_path": "/test.xlsx"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False

    def test_success(self):
        mock_skill = Mock()
        mock_skill.execute.return_value = {"success": True}
        with patch("app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill", return_value=mock_skill):
            result = _unwrap(dispatch_legacy_tool_payload(
                "excel_toolkit", "view", {"file_path": "/test.xlsx"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True


# ========================= shipment_template tool ==========================


class TestShipmentTemplateTool:
    def test_view(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "shipment_template", "view", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_other(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "shipment_template", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= template_preview tool ===========================


class TestTemplatePreviewTool:
    def test_list(self):
        mock_svc = Mock()
        mock_svc.get_templates.return_value = [{"id": 1, "name": "test"}]
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "template_preview", "list", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_query(self):
        mock_svc = Mock()
        mock_svc.get_templates.return_value = [{"id": 1}]
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "template_preview", "query", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_fallback(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "template_preview", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= settings tool ==================================


class TestSettingsTool:
    def test_query(self):
        mock_svc = Mock()
        mock_svc.get_system_info.return_value = {"version": "1.0"}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "settings", "query", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_get_system_info(self):
        mock_svc = Mock()
        mock_svc.get_system_info.return_value = {"version": "1.0"}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "settings", "get_system_info", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_get_startup_config(self):
        mock_svc = Mock()
        mock_svc.get_startup_config.return_value = {"auto_start": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "settings", "get_startup_config", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_enable_startup(self):
        mock_svc = Mock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "settings", "enable_startup", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_disable_startup(self):
        mock_svc = Mock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "settings", "disable_startup", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_fallback(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "settings", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= tools_table tool ================================


class TestToolsTableTool:
    def test_list(self):
        with patch("app.services.tools_execution_service.get_workflow_tool_registry", return_value={"products": {}, "customers": {}}):
            result = _unwrap(dispatch_legacy_tool_payload(
                "tools_table", "list", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True
        assert "tool_ids" in result

    def test_query(self):
        with patch("app.services.tools_execution_service.get_workflow_tool_registry", return_value={"products": {}}):
            result = _unwrap(dispatch_legacy_tool_payload(
                "tools_table", "query", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_fallback(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "tools_table", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= other_tools tool ================================


class TestOtherToolsTool:
    def test_list(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "other_tools", "list", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True
        assert "tools" in result

    def test_query(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "other_tools", "query", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_fallback(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "other_tools", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= database tool ==================================


class TestDatabaseTool:
    def test_view(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "view", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_none_action(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", None, {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_empty_action(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_backup(self):
        mock_svc = Mock()
        mock_svc.backup_database.return_value = {"success": True}
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "backup", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_restore_missing_file(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "restore", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False

    def test_restore_with_file(self):
        mock_svc = Mock()
        mock_svc.restore_database.return_value = {"success": True}
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "restore", {"backup_file": "backup_2024.db"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_list_backups(self):
        mock_svc = Mock()
        mock_svc.list_backups.return_value = {"success": True, "backups": []}
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "list", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_delete_missing_file(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "delete", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False

    def test_unknown_action(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "database", "unknown_action", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False


# ========================= system tool ====================================


class TestSystemTool:
    def test_view(self):
        mock_svc = Mock()
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "view", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_none_action(self):
        mock_svc = Mock()
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", None, {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_get_startup_config(self):
        mock_svc = Mock()
        mock_svc.get_startup_config.return_value = {"auto_start": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "get_startup_config", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_enable_startup(self):
        mock_svc = Mock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "enable_startup", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_disable_startup(self):
        mock_svc = Mock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "disable_startup", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_get_system_info(self):
        mock_svc = Mock()
        mock_svc.get_system_info.return_value = {"version": "1.0"}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "get_system_info", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_get_printer_config(self):
        mock_svc = Mock()
        mock_svc.get_printer_config.return_value = {"printers": []}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "get_printer_config", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        # get_printer_config returns the raw result from the service
        assert "printers" in result

    def test_set_default_printer(self):
        mock_svc = Mock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "set_default_printer", {"printer_name": "HP"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_set_default_printer_missing_name(self):
        mock_svc = Mock()
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "set_default_printer", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False

    def test_unknown_action(self):
        mock_svc = Mock()
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "system", "unknown_action", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is False


# ========================= upload_file tool ================================


class TestUploadFileTool:
    def test_returns_upload_prompt(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "upload_file", "view", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True
        assert "上传" in result["message"]


# ========================= unknown tool ===================================


class TestUnknownTool:
    def test_returns_error(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "nonexistent_tool", "view", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is False
        assert "未知" in result.get("message", "")


# ========================= ai_ecosystem tool ===============================


class TestAiEcosystemTool:
    def test_list(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "ai_ecosystem", "list", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True
        assert "views" in result.get("data", {})

    def test_query(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "ai_ecosystem", "query", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_fallback(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "ai_ecosystem", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= materials_list tool =============================


class TestMaterialsListTool:
    def test_query(self):
        mock_svc = Mock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "materials_list", "query", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_list(self):
        mock_svc = Mock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "materials_list", "list", {},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_fallback(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "materials_list", "other", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= customers search with keyword from params =======


class TestCustomersSearchKeywordFromParams:
    def test_search_with_unit_name_as_keyword(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "customers", "search", {"unit_name": "公司A"},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True
        assert "公司A" in result.get("redirect", "")

    def test_search_with_name_as_keyword(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "customers", "search", {"name": "公司B"},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_search_with_customer_name_as_keyword(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "customers", "search", {"customer_name": "公司C"},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True

    def test_view_with_add_verb_not_redirected(self):
        # When order_text contains "添加", it tries to create but needs unit_name
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1, "customer_name": "公司A"}}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(dispatch_legacy_tool_payload(
                "customers", "view", {"order_text": "添加客户", "unit_name": "公司A"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_search_with_add_verb_not_redirected(self):
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
            patch("app.services.unified_query_service.query_service"),
            patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit", return_value=None),
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(dispatch_legacy_tool_payload(
                "customers", "search", {"keyword": "公司A", "unit_name": "公司A", "order_text": "添加客户"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_search_with_del_verb_not_redirected(self):
        with patch("app.services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 0
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit", return_value=None):
                result = _unwrap(dispatch_legacy_tool_payload(
                    "customers", "search", {"keyword": "公司A", "order_text": "删除客户"},
                    json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                ))
        assert result["success"] is True

    def test_fallback_message(self):
        result = _unwrap(dispatch_legacy_tool_payload(
            "customers", "unknown", {},
            json_response_fn=_json_fn, hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        ))
        assert result["success"] is True


# ========================= shipment_records list ===========================


class TestShipmentRecordsListTool:
    def test_list_with_unit(self):
        mock_svc = Mock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "shipment_records", "list", {"unit": "公司A"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True

    def test_query_with_unit_name(self):
        mock_svc = Mock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _unwrap(dispatch_legacy_tool_payload(
                "shipment_records", "query", {"unit_name": "公司A"},
                json_response_fn=_json_fn, hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            ))
        assert result["success"] is True
