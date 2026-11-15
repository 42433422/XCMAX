"""Tests for app.domain.shared_services.tools_payload_legacy — uncovered branches (ext3).

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

from app.domain.shared_services.tools_payload_legacy import dispatch_legacy_tool_payload


def _shared_setup_case_0(case_value_1, case_value_2):
    result = _unwrap(
        dispatch_legacy_tool_payload(
            case_value_1,
            case_value_2,
            {},
            json_response_fn=_json_fn,
            hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        )
    )
    return result


def _shared_setup_case_1(case_value_1, case_value_2, case_value_3, case_value_4):
    result = _unwrap(
        dispatch_legacy_tool_payload(
            case_value_1,
            case_value_2,
            {case_value_3: case_value_4},
            json_response_fn=_json_fn,
            hdr_getter=_hdr_getter,
            parse_order_text_fn=_parse_order_text,
        )
    )
    return result


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
    assert result["success"] is _shared_literal_0


def _assert_shared_view_1(
    self, _shared_literal_0, _shared_literal_1, _shared_literal_2, _shared_literal_3
):
    mock_svc = Mock()
    with patch(_shared_literal_1, return_value=mock_svc):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                _shared_literal_2,
                _shared_literal_3,
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
    assert result["success"] is _shared_literal_0


def _assert_shared_query_2(self, _shared_literal_0, _shared_literal_1):
    mock_svc = Mock()
    mock_svc.get_system_info.return_value = {"version": "1.0"}
    with patch("app.services.get_system_service", return_value=mock_svc):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                _shared_literal_0,
                _shared_literal_1,
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
    assert result["success"] is True


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
        return _assert_shared_view_action_0(self, True, "template_extract", "view")

    def test_none_action(self):
        result = _unwrap(
            dispatch_legacy_tool_payload(
                "template_extract",
                None,
                {},
                json_response_fn=_json_fn,
                hdr_getter=_hdr_getter,
                parse_order_text_fn=_parse_order_text,
            )
        )
        assert result["success"] is True

    def test_empty_action(self):
        return _assert_shared_view_action_0(self, True, "template_extract", "")

    def test_missing_file_path(self):
        return _assert_shared_view_action_0(self, False, "template_extract", "extract")

    def test_file_not_exists(self):
        result = _shared_setup_case_1(
            case_value_1="template_extract",
            case_value_2="extract",
            case_value_3="file_path",
            case_value_4="/nonexistent.xlsx",
        )
        assert result["success"] is False

    def test_recoverable_error(self, tmp_path):
        xlsx_path = str(tmp_path / "test.xlsx")
        with open(xlsx_path, "w") as f:
            f.write("fake")

        with (
            patch("os.path.exists", return_value=True),
            patch(
                "app.domain.shared_services.document_templates_service._list_excel_sheet_names",
                side_effect=RuntimeError("fail"),
            ),
        ):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "template_extract",
                    "extract",
                    {"file_path": xlsx_path},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is False


# ========================= excel_toolkit tool ==============================


class TestExcelToolkitTool:
    def test_missing_file_path(self):
        return _assert_shared_view_action_0(self, False, "excel_toolkit", "view")

    def test_import_error(self):
        with patch.dict(
            "sys.modules", {"app.infrastructure.skills.excel_toolkit.excel_toolkit": None}
        ):
            result = _shared_setup_case_1(
                case_value_1="excel_toolkit",
                case_value_2="view",
                case_value_3="file_path",
                case_value_4="/test.xlsx",
            )
        assert result["success"] is False

    def test_recoverable_error(self):
        with (
            patch(
                "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
                side_effect=RuntimeError("fail"),
            ),
        ):
            result = _shared_setup_case_1(
                case_value_1="excel_toolkit",
                case_value_2="view",
                case_value_3="file_path",
                case_value_4="/test.xlsx",
            )
        assert result["success"] is False

    def test_success(self):
        mock_skill = Mock()
        mock_skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_skill,
        ):
            result = _shared_setup_case_1(
                case_value_1="excel_toolkit",
                case_value_2="view",
                case_value_3="file_path",
                case_value_4="/test.xlsx",
            )
        assert result["success"] is True


# ========================= shipment_template tool ==========================


class TestShipmentTemplateTool:
    def test_view(self):
        return _assert_shared_view_action_0(self, True, "shipment_template", "view")

    def test_other(self):
        return _assert_shared_view_action_0(self, True, "shipment_template", "other")


# ========================= template_preview tool ===========================


class TestTemplatePreviewTool:
    def test_list(self):
        mock_svc = Mock()
        mock_svc.get_templates.return_value = [{"id": 1, "name": "test"}]
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="template_preview", case_value_2="list")
        assert result["success"] is True

    def test_query(self):
        mock_svc = Mock()
        mock_svc.get_templates.return_value = [{"id": 1}]
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="template_preview", case_value_2="query")
        assert result["success"] is True

    def test_fallback(self):
        return _assert_shared_view_action_0(self, True, "template_preview", "other")


# ========================= settings tool ==================================


class TestSettingsTool:
    def test_query(self):
        return _assert_shared_query_2(self, "settings", "query")

    def test_get_system_info(self):
        return _assert_shared_query_2(self, "settings", "get_system_info")

    def test_get_startup_config(self):
        mock_svc = Mock()
        mock_svc.get_startup_config.return_value = {"auto_start": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(
                case_value_1="settings", case_value_2="get_startup_config"
            )
        assert result["success"] is True

    def test_enable_startup(self):
        mock_svc = Mock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="settings", case_value_2="enable_startup")
        assert result["success"] is True

    def test_disable_startup(self):
        mock_svc = Mock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="settings", case_value_2="disable_startup")
        assert result["success"] is True

    def test_fallback(self):
        return _assert_shared_view_action_0(self, True, "settings", "other")


# ========================= tools_table tool ================================


class TestToolsTableTool:
    def test_list(self):
        with patch(
            "app.domain.shared_services.tools_execution_service.get_workflow_tool_registry",
            return_value={"products": {}, "customers": {}},
        ):
            result = _shared_setup_case_0(case_value_1="tools_table", case_value_2="list")
        assert result["success"] is True
        assert "tool_ids" in result

    def test_query(self):
        with patch(
            "app.domain.shared_services.tools_execution_service.get_workflow_tool_registry",
            return_value={"products": {}},
        ):
            result = _shared_setup_case_0(case_value_1="tools_table", case_value_2="query")
        assert result["success"] is True

    def test_fallback(self):
        return _assert_shared_view_action_0(self, True, "tools_table", "other")


# ========================= other_tools tool ================================


class TestOtherToolsTool:
    def test_list(self):
        result = _shared_setup_case_0(case_value_1="other_tools", case_value_2="list")
        assert result["success"] is True
        assert "tools" in result

    def test_query(self):
        return _assert_shared_view_action_0(self, True, "other_tools", "query")

    def test_fallback(self):
        return _assert_shared_view_action_0(self, True, "other_tools", "other")


# ========================= database tool ==================================


class TestDatabaseTool:
    def test_view(self):
        return _assert_shared_view_1(
            self, True, "app.services.get_database_service", "database", "view"
        )

    def test_none_action(self):
        mock_svc = Mock()
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "database",
                    None,
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_empty_action(self):
        return _assert_shared_view_1(
            self, True, "app.services.get_database_service", "database", ""
        )

    def test_backup(self):
        mock_svc = Mock()
        mock_svc.backup_database.return_value = {"success": True}
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="database", case_value_2="backup")
        assert result["success"] is True

    def test_restore_missing_file(self):
        return _assert_shared_view_1(
            self, False, "app.services.get_database_service", "database", "restore"
        )

    def test_restore_with_file(self):
        mock_svc = Mock()
        mock_svc.restore_database.return_value = {"success": True}
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _shared_setup_case_1(
                case_value_1="database",
                case_value_2="restore",
                case_value_3="backup_file",
                case_value_4="backup_2024.db",
            )
        assert result["success"] is True

    def test_list_backups(self):
        mock_svc = Mock()
        mock_svc.list_backups.return_value = {"success": True, "backups": []}
        with patch("app.services.get_database_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="database", case_value_2="list")
        assert result["success"] is True

    def test_delete_missing_file(self):
        return _assert_shared_view_1(
            self, False, "app.services.get_database_service", "database", "delete"
        )

    def test_unknown_action(self):
        return _assert_shared_view_1(
            self, False, "app.services.get_database_service", "database", "unknown_action"
        )


# ========================= system tool ====================================


class TestSystemTool:
    def test_view(self):
        return _assert_shared_view_1(
            self, True, "app.services.get_system_service", "system", "view"
        )

    def test_none_action(self):
        mock_svc = Mock()
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "system",
                    None,
                    {},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_get_startup_config(self):
        mock_svc = Mock()
        mock_svc.get_startup_config.return_value = {"auto_start": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="system", case_value_2="get_startup_config")
        assert result["success"] is True

    def test_enable_startup(self):
        mock_svc = Mock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="system", case_value_2="enable_startup")
        assert result["success"] is True

    def test_disable_startup(self):
        mock_svc = Mock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="system", case_value_2="disable_startup")
        assert result["success"] is True

    def test_get_system_info(self):
        return _assert_shared_query_2(self, "system", "get_system_info")

    def test_get_printer_config(self):
        mock_svc = Mock()
        mock_svc.get_printer_config.return_value = {"printers": []}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="system", case_value_2="get_printer_config")
        # get_printer_config returns the raw result from the service
        assert "printers" in result

    def test_set_default_printer(self):
        mock_svc = Mock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _shared_setup_case_1(
                case_value_1="system",
                case_value_2="set_default_printer",
                case_value_3="printer_name",
                case_value_4="HP",
            )
        assert result["success"] is True

    def test_set_default_printer_missing_name(self):
        return _assert_shared_view_1(
            self, False, "app.services.get_system_service", "system", "set_default_printer"
        )

    def test_unknown_action(self):
        return _assert_shared_view_1(
            self, False, "app.services.get_system_service", "system", "unknown_action"
        )


# ========================= upload_file tool ================================


class TestUploadFileTool:
    def test_returns_upload_prompt(self):
        result = _shared_setup_case_0(case_value_1="upload_file", case_value_2="view")
        assert result["success"] is True
        assert "上传" in result["message"]


# ========================= unknown tool ===================================


class TestUnknownTool:
    def test_returns_error(self):
        result = _shared_setup_case_0(case_value_1="nonexistent_tool", case_value_2="view")
        assert result["success"] is False
        assert "未知" in result.get("message", "")


# ========================= ai_ecosystem tool ===============================


class TestAiEcosystemTool:
    def test_list(self):
        result = _shared_setup_case_0(case_value_1="ai_ecosystem", case_value_2="list")
        assert result["success"] is True
        assert "views" in result.get("data", {})

    def test_query(self):
        return _assert_shared_view_action_0(self, True, "ai_ecosystem", "query")

    def test_fallback(self):
        return _assert_shared_view_action_0(self, True, "ai_ecosystem", "other")


# ========================= materials_list tool =============================


class TestMaterialsListTool:
    def test_query(self):
        mock_svc = Mock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="materials_list", case_value_2="query")
        assert result["success"] is True

    def test_list(self):
        mock_svc = Mock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _shared_setup_case_0(case_value_1="materials_list", case_value_2="list")
        assert result["success"] is True

    def test_fallback(self):
        return _assert_shared_view_action_0(self, True, "materials_list", "other")


# ========================= customers search with keyword from params =======


class TestCustomersSearchKeywordFromParams:
    def test_search_with_unit_name_as_keyword(self):
        result = _shared_setup_case_1(
            case_value_1="customers",
            case_value_2="search",
            case_value_3="unit_name",
            case_value_4="公司A",
        )
        assert result["success"] is True
        assert "公司A" in result.get("redirect", "")

    def test_search_with_name_as_keyword(self):
        result = _shared_setup_case_1(
            case_value_1="customers",
            case_value_2="search",
            case_value_3="name",
            case_value_4="公司B",
        )
        assert result["success"] is True

    def test_search_with_customer_name_as_keyword(self):
        result = _shared_setup_case_1(
            case_value_1="customers",
            case_value_2="search",
            case_value_3="customer_name",
            case_value_4="公司C",
        )
        assert result["success"] is True

    def test_view_with_add_verb_not_redirected(self):
        # When order_text contains "添加", it tries to create but needs unit_name
        mock_svc = Mock()
        mock_svc.create.return_value = {
            "success": True,
            "data": {"id": 1, "customer_name": "公司A"},
        }
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "view",
                    {"order_text": "添加客户", "unit_name": "公司A"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_search_with_add_verb_not_redirected(self):
        mock_svc = Mock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with (
            patch("app.application.get_customer_app_service", return_value=mock_svc),
            patch("app.services.get_task_context_service") as mock_ctx,
            patch("app.domain.shared_services.unified_query_service.query_service"),
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            mock_ctx_inst = Mock()
            mock_ctx.return_value = mock_ctx_inst
            result = _unwrap(
                dispatch_legacy_tool_payload(
                    "customers",
                    "search",
                    {"keyword": "公司A", "unit_name": "公司A", "order_text": "添加客户"},
                    json_response_fn=_json_fn,
                    hdr_getter=_hdr_getter,
                    parse_order_text_fn=_parse_order_text,
                )
            )
        assert result["success"] is True

    def test_search_with_del_verb_not_redirected(self):
        with patch("app.domain.shared_services.unified_query_service.query_service") as mock_qs:
            mock_qs.delete.return_value = 0
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ):
                result = _unwrap(
                    dispatch_legacy_tool_payload(
                        "customers",
                        "search",
                        {"keyword": "公司A", "order_text": "删除客户"},
                        json_response_fn=_json_fn,
                        hdr_getter=_hdr_getter,
                        parse_order_text_fn=_parse_order_text,
                    )
                )
        assert result["success"] is True

    def test_fallback_message(self):
        return _assert_shared_view_action_0(self, True, "customers", "unknown")


# ========================= shipment_records list ===========================


class TestShipmentRecordsListTool:
    def test_list_with_unit(self):
        mock_svc = Mock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _shared_setup_case_1(
                case_value_1="shipment_records",
                case_value_2="list",
                case_value_3="unit",
                case_value_4="公司A",
            )
        assert result["success"] is True

    def test_query_with_unit_name(self):
        mock_svc = Mock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _shared_setup_case_1(
                case_value_1="shipment_records",
                case_value_2="query",
                case_value_3="unit_name",
                case_value_4="公司A",
            )
        assert result["success"] is True
