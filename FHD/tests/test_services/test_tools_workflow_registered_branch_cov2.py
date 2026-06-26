"""Branch-coverage tests (round 2) for app.services.tools_workflow_registered.

Targets the missing branches not covered by the existing test_tools_workflow_registered*.py
files. Focuses on:
  - _registered_router_business_event (print_label / inventory_update / shipment_create / unknown)
  - _registered_router_system_maintenance (all sub-actions + cache branches)
  - _registered_router_excel_analyzer / excel_toolkit / label_template_generator
  - _registered_router_document_template (create/update/delete/unknown)
  - _registered_router_template_preview (view/list/create branches)
  - _registered_router_business_db (entity normalization, sql rejection, read/write)
  - _registered_router_dataset_rag (all actions + validation branches)
  - _registered_router_memory_v2 (all actions + validation branches)
  - _registered_router_excel_analysis (read/structure/statistics/query branches)
  - _registered_router_excel_vector_index (execute/query/unknown)
  - _registered_router_ocr (request/recognize/extract/analyze/recognize_and_extract)
  - _registered_router_excel_import (execute_import/import_records)
  - _registered_router_unit_products_import
  - _registered_router_print (workflow_label_dispatch / save_printer_selection)
  - _registered_router_employee (list/execute/missing fields)
  - _normalize_business_db_entity / _ocr_artifact_payload / _execute_excel_import_records
  - execute_registered_workflow_tool (employee tool dispatch path)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Pre-import app.application to break a circular import chain:
# app.services.__init__ → products_service → app.application.__init__ →
# employee_pack_runner → app.mod_sdk.__init__ → app.mod_sdk.services →
# app.services.get_products_service (circular).
# Importing app.application first ensures the chain resolves cleanly.
import app.application  # noqa: F401

from app.services.tools_workflow_registered import (
    _execute_excel_import_records,
    _normalize_business_db_entity,
    _ocr_artifact_payload,
    _registered_router_business_db,
    _registered_router_business_event,
    _registered_router_dataset_rag,
    _registered_router_document_template,
    _registered_router_employee,
    _registered_router_excel_analysis,
    _registered_router_excel_analyzer,
    _registered_router_excel_import,
    _registered_router_excel_toolkit,
    _registered_router_excel_vector_index,
    _registered_router_label_template_generator,
    _registered_router_memory_v2,
    _registered_router_ocr,
    _registered_router_print,
    _registered_router_system_maintenance,
    _registered_router_template_preview,
    _registered_router_unit_products_import,
    execute_registered_workflow_tool,
)


# ===========================================================================
# _registered_router_business_event
# ===========================================================================


class TestBusinessEventRouter:
    def test_print_label_success(self):
        with patch(
            "app.neuro_bus.domains.print_domain.get_print_domain"
        ) as mock_get:
            mock_get.return_value.emit_job_submitted.return_value = True
            result = _registered_router_business_event(
                "print_label", {"job_id": "j1", "document_name": "doc", "printer_id": "p1"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["job_id"] == "j1"

    def test_print_label_generates_uuid_when_missing(self):
        with patch(
            "app.neuro_bus.domains.print_domain.get_print_domain"
        ) as mock_get:
            mock_get.return_value.emit_job_submitted.return_value = True
            result = _registered_router_business_event(
                "print_label", {"document_name": "doc"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["job_id"]  # auto-generated uuid

    def test_print_label_failure(self):
        with patch(
            "app.neuro_bus.domains.print_domain.get_print_domain"
        ) as mock_get:
            mock_get.return_value.emit_job_submitted.return_value = False
            result = _registered_router_business_event(
                "print_label", {"job_id": "j1"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_inventory_update_success(self):
        with patch(
            "app.neuro_bus.domains.inventory_domain.get_inventory_domain"
        ) as mock_get:
            mock_get.return_value.emit_stock_changed.return_value = True
            result = _registered_router_business_event(
                "inventory_update", {"product_id": "p1", "delta": 5}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_inventory_update_failure(self):
        with patch(
            "app.neuro_bus.domains.inventory_domain.get_inventory_domain"
        ) as mock_get:
            mock_get.return_value.emit_stock_changed.return_value = False
            result = _registered_router_business_event(
                "inventory_update", {}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_shipment_create_success(self):
        with patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            return_value=True,
        ):
            result = _registered_router_business_event(
                "shipment_create",
                {"unit_name": "Co", "items": [{"id": 1}]},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["published"] is True

    def test_shipment_create_publish_failed(self):
        with patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            return_value=False,
        ):
            result = _registered_router_business_event(
                "shipment_create", {}, {}, "admin", ""
            )
        assert result["success"] is False
        assert result["published"] is False

    def test_unknown_action(self):
        result = _registered_router_business_event("fly", {}, {}, "admin", "")
        assert result["success"] is False
        assert "business_event" in result["message"]


# ===========================================================================
# _registered_router_system_maintenance
# ===========================================================================


class TestSystemMaintenanceRouter:
    def test_set_default_printer_success(self):
        with patch(
            "app.application.facades.session_facade.get_system_service"
        ) as mock_get:
            mock_get.return_value.set_default_printer.return_value = {"success": True}
            result = _registered_router_system_maintenance(
                "set_default_printer", {"printer_name": "HP"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["http_status_code"] == 200

    def test_set_default_printer_failure(self):
        with patch(
            "app.application.facades.session_facade.get_system_service"
        ) as mock_get:
            mock_get.return_value.set_default_printer.return_value = {"success": False}
            result = _registered_router_system_maintenance(
                "set_default_printer", {"printer_name": ""}, {}, "admin", ""
            )
        assert result["http_status_code"] == 500

    def test_enable_startup_success(self):
        with patch(
            "app.application.facades.session_facade.get_system_service"
        ) as mock_get:
            mock_get.return_value.enable_startup.return_value = {"success": True}
            result = _registered_router_system_maintenance(
                "enable_startup", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_enable_startup_failure(self):
        with patch(
            "app.application.facades.session_facade.get_system_service"
        ) as mock_get:
            mock_get.return_value.enable_startup.return_value = {"success": False}
            result = _registered_router_system_maintenance(
                "enable_startup", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 500

    def test_disable_startup_success(self):
        with patch(
            "app.application.facades.session_facade.get_system_service"
        ) as mock_get:
            mock_get.return_value.disable_startup.return_value = {"success": True}
            result = _registered_router_system_maintenance(
                "disable_startup", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_disable_startup_failure(self):
        with patch(
            "app.application.facades.session_facade.get_system_service"
        ) as mock_get:
            mock_get.return_value.disable_startup.return_value = {"success": False}
            result = _registered_router_system_maintenance(
                "disable_startup", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 500

    def test_backup_database_success(self):
        with patch(
            "app.application.facades.session_facade.get_database_service"
        ) as mock_get:
            mock_get.return_value.backup_database.return_value = {"success": True}
            result = _registered_router_system_maintenance(
                "backup_database", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_backup_database_failure(self):
        with patch(
            "app.application.facades.session_facade.get_database_service"
        ) as mock_get:
            mock_get.return_value.backup_database.return_value = {"success": False}
            result = _registered_router_system_maintenance(
                "backup_database", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 500

    def test_delete_database_backup_success(self):
        with patch(
            "app.application.facades.session_facade.get_database_service"
        ) as mock_get:
            mock_get.return_value.delete_backup.return_value = {"success": True}
            result = _registered_router_system_maintenance(
                "delete_database_backup", {"backup_file": "bak.sql"}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_delete_database_backup_failure(self):
        with patch(
            "app.application.facades.session_facade.get_database_service"
        ) as mock_get:
            mock_get.return_value.delete_backup.return_value = {"success": False}
            result = _registered_router_system_maintenance(
                "delete_database_backup", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 500

    def test_restore_database_success(self):
        with patch(
            "app.application.facades.session_facade.get_database_service"
        ) as mock_get:
            mock_get.return_value.restore_database.return_value = {"success": True}
            result = _registered_router_system_maintenance(
                "restore_database", {"backup_file": "bak.sql"}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_restore_database_failure(self):
        with patch(
            "app.application.facades.session_facade.get_database_service"
        ) as mock_get:
            mock_get.return_value.restore_database.return_value = {"success": False}
            result = _registered_router_system_maintenance(
                "restore_database", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 400

    def test_clear_performance_cache_no_redis(self):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer"
        ) as mock_get:
            mock_get.return_value.redis_cache = None
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {}, {}, "admin", ""
            )
        assert result["success"] is False
        assert result["http_status_code"] == 503

    def test_clear_performance_cache_with_pattern(self):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer"
        ) as mock_get:
            mock_get.return_value.redis_cache.clear_pattern.return_value = 5
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {"pattern": "user:*"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "user:*" in result["message"]

    def test_clear_performance_cache_without_pattern(self):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer"
        ) as mock_get:
            mock_get.return_value.redis_cache.clear_local_cache = MagicMock()
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "本地缓存" in result["message"]

    def test_invalidate_performance_cache_no_redis(self):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer"
        ) as mock_get:
            mock_get.return_value.redis_cache = None
            result = _registered_router_system_maintenance(
                "invalidate_performance_cache", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 503

    def test_invalidate_performance_cache_success(self):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer"
        ) as mock_get:
            mock_get.return_value.redis_cache.delete.return_value = 3
            result = _registered_router_system_maintenance(
                "invalidate_performance_cache", {"keys": ["k1", "k2", "k3"]}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["data"]["deleted_count"] == 3

    def test_reinitialize_performance(self):
        with patch(
            "app.utils.performance_initializer.init_performance_optimization"
        ) as mock_init:
            mock_init.return_value.get_status.return_value = {"ok": True}
            result = _registered_router_system_maintenance(
                "reinitialize_performance", {}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["data"] == {"ok": True}

    def test_unknown_action(self):
        result = _registered_router_system_maintenance("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ===========================================================================
# _registered_router_excel_analyzer
# ===========================================================================


class TestExcelAnalyzerRouter:
    def test_unknown_action(self):
        result = _registered_router_excel_analyzer("fly", {}, {}, "admin", "")
        assert result["success"] is False

    def test_missing_file_path(self):
        result = _registered_router_excel_analyzer("analyze", {}, {}, "admin", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_import_error(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "excel_template_analyzer" in name:
                raise ImportError("no skill")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _registered_router_excel_analyzer(
                "analyze", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "未正确安装" in result["message"]

    def test_dict_result(self):
        mock_skill = MagicMock()
        mock_skill.execute.return_value = {"success": True, "rows": 5}
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_excel_analyzer(
                "analyze", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["file_path"] == "/tmp/x.xlsx"

    def test_non_dict_result(self):
        mock_skill = MagicMock()
        mock_skill.execute.return_value = "not a dict"
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_excel_analyzer(
                "analyze", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "无效" in result["message"]


# ===========================================================================
# _registered_router_excel_toolkit
# ===========================================================================


class TestExcelToolkitRouter:
    def test_unknown_action(self):
        result = _registered_router_excel_toolkit("fly", {}, {}, "admin", "")
        assert result["success"] is False

    def test_missing_file_path(self):
        result = _registered_router_excel_toolkit("view", {}, {}, "admin", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_import_error(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if "excel_toolkit" in name:
                raise ImportError("no skill")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _registered_router_excel_toolkit(
                "view", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_dict_result_with_max_rows(self):
        mock_skill = MagicMock()
        mock_skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_excel_toolkit(
                "view", {"file_path": "/tmp/x.xlsx", "max_rows": 50}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["file_path"] == "/tmp/x.xlsx"

    def test_non_dict_result(self):
        mock_skill = MagicMock()
        mock_skill.execute.return_value = None
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_excel_toolkit(
                "view", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_action_normalization_empty(self):
        """Empty action normalizes to 'view'."""
        mock_skill = MagicMock()
        mock_skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_excel_toolkit(
                "", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True


# ===========================================================================
# _registered_router_label_template_generator
# ===========================================================================


class TestLabelTemplateGeneratorRouter:
    def test_unknown_action(self):
        result = _registered_router_label_template_generator("fly", {}, {}, "admin", "")
        assert result["success"] is False

    def test_missing_image_path(self):
        result = _registered_router_label_template_generator("execute", {}, {}, "admin", "")
        assert result["success"] is False
        assert "image_path" in result["message"]

    def test_import_error(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if "label_template_generator" in name:
                raise ImportError("no skill")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _registered_router_label_template_generator(
                "execute", {"image_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_dict_result(self):
        mock_skill = MagicMock()
        mock_skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.label_template_generator.get_label_template_generator_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_label_template_generator(
                "execute", {"image_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["image_path"] == "/tmp/img.png"

    def test_non_dict_result(self):
        mock_skill = MagicMock()
        mock_skill.execute.return_value = 42
        with patch(
            "app.infrastructure.skills.label_template_generator.get_label_template_generator_skill",
            return_value=mock_skill,
        ):
            result = _registered_router_label_template_generator(
                "execute", {"image_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is False


# ===========================================================================
# _registered_router_document_template
# ===========================================================================


class TestDocumentTemplateRouter:
    def test_create(self):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create",
            return_value=({"success": True}, 201),
        ):
            result = _registered_router_document_template(
                "create", {"name": "T1"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["http_status_code"] == 201

    def test_update(self):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_update",
            return_value=({"success": True}, 200),
        ):
            result = _registered_router_document_template(
                "update", {"id": 1}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_delete(self):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_delete",
            return_value=({"success": True}, 200),
        ):
            result = _registered_router_document_template(
                "delete", {"id": 1}, {"template_base_dir": "/tmp"}, {}, ""
            )
        assert result["success"] is True

    def test_delete_with_base_dir(self):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_delete",
            return_value=({"success": False, "message": "err"}, 400),
        ) as mock:
            result = _registered_router_document_template(
                "delete", {"id": 1}, {"template_base_dir": "/custom"}, "admin", ""
            )
        mock.assert_called_once()
        assert result["http_status_code"] == 400

    def test_unknown_action(self):
        result = _registered_router_document_template("fly", {}, {}, "admin", "")
        assert result["success"] is False

    def test_none_status_code_defaults(self):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create",
            return_value=({"success": True}, None),
        ):
            result = _registered_router_document_template(
                "create", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200

    def test_none_status_code_failure_defaults(self):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create",
            return_value=({"success": False}, None),
        ):
            result = _registered_router_document_template(
                "create", {}, {}, "admin", ""
            )
        assert result["http_status_code"] == 400


# ===========================================================================
# _registered_router_template_preview
# ===========================================================================


class TestTemplatePreviewRouter:
    def test_view_action(self):
        result = _registered_router_template_preview("view", {}, {}, "admin", "")
        assert result["success"] is True
        assert "redirect" in result

    def test_list_dict_result(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"success": True, "data": []}
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _registered_router_template_preview("list", {}, {}, "admin", "")
        assert result["success"] is True

    def test_list_non_dict_result(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = [{"id": 1}]
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _registered_router_template_preview("query", {}, {}, "admin", "")
        assert result["success"] is True
        assert result["data"] == [{"id": 1}]

    def test_query_alias(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"success": True}
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _registered_router_template_preview("query", {}, {}, "admin", "")
        assert result["success"] is True


# ===========================================================================
# _normalize_business_db_entity
# ===========================================================================


class TestNormalizeBusinessDbEntity:
    def test_empty_raw_returns_empty(self):
        assert _normalize_business_db_entity("") == ""

    def test_none_raw_returns_empty(self):
        assert _normalize_business_db_entity(None) == ""

    def test_lowercase_customer(self):
        assert _normalize_business_db_entity("customer") == "customers"

    def test_chinese_客户(self):
        assert _normalize_business_db_entity("客户") == "customers"

    def test_product(self):
        assert _normalize_business_db_entity("product") == "products"

    def test_materials(self):
        assert _normalize_business_db_entity("materials") == "materials"

    def test_shipment(self):
        assert _normalize_business_db_entity("shipment") == "shipment_records"

    def test_unknown_entity_returns_empty(self):
        assert _normalize_business_db_entity("unknown_thing") == ""

    def test_fallback_to_user_message(self):
        result = _normalize_business_db_entity("", user_message="请查询客户列表")
        assert result == "customers"

    def test_fallback_to_user_message_products(self):
        result = _normalize_business_db_entity("", user_message="产品列表")
        assert result == "products"


# ===========================================================================
# _registered_router_business_db
# ===========================================================================


class TestBusinessDbRouter:
    def test_missing_entity(self):
        result = _registered_router_business_db("read", {}, {}, "admin", "")
        assert result["success"] is False
        assert "entity" in result["message"]

    def test_sql_rejection(self):
        result = _registered_router_business_db(
            "read", {"entity": "customers", "sql": "SELECT *"}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "SQL" in result["message"]

    def test_raw_sql_rejection(self):
        result = _registered_router_business_db(
            "read", {"entity": "customers", "raw_sql": "DROP TABLE"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_query_sql_rejection(self):
        result = _registered_router_business_db(
            "read", {"entity": "products", "query_sql": "SELECT 1"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_read_customers(self):
        with patch("app.application.get_customer_app_service") as mock_get:
            mock_get.return_value.get_all.return_value = {"success": True, "data": []}
            result = _registered_router_business_db(
                "read", {"entity": "customers"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_read_products(self):
        with patch("app.services.get_products_service") as mock_get:
            mock_get.return_value.get_products.return_value = {"success": True, "data": []}
            result = _registered_router_business_db(
                "read", {"entity": "products"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_read_materials(self):
        with patch("app.application.get_material_application_service") as mock_get:
            mock_get.return_value.get_all_materials.return_value = {"success": True, "data": []}
            result = _registered_router_business_db(
                "read", {"entity": "materials"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_read_shipment_records(self):
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_get.return_value.get_shipment_records.return_value = []
            result = _registered_router_business_db(
                "read", {"entity": "shipment_records"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_unknown_action(self):
        result = _registered_router_business_db(
            "fly", {"entity": "customers"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_write_non_dict_payload(self):
        result = _registered_router_business_db(
            "write", {"entity": "customers", "payload": "not-a-dict"}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "dict" in result["message"]

    def test_write_customers_create(self):
        with patch("app.application.get_customer_app_service") as mock_get:
            mock_get.return_value.create.return_value = {"success": True}
            result = _registered_router_business_db(
                "write",
                {"entity": "customers", "operation": "create", "payload": {"customer_name": "X"}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_customers_ensure_exists(self):
        with patch("app.application.get_customer_app_service") as mock_get:
            mock_get.return_value.match_purchase_unit.return_value = None
            mock_get.return_value.create.return_value = {"success": True}
            result = _registered_router_business_db(
                "write",
                {"entity": "customers", "operation": "ensure_exists", "payload": {"customer_name": "X"}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_customers_upsert(self):
        with patch("app.application.get_customer_app_service") as mock_get:
            mock_get.return_value.match_purchase_unit.return_value = MagicMock(unit_name="X")
            result = _registered_router_business_db(
                "write",
                {"entity": "customers", "operation": "upsert", "payload": {"customer_name": "X"}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_customers_unsupported_op(self):
        result = _registered_router_business_db(
            "write",
            {"entity": "customers", "operation": "delete", "payload": {}},
            {},
            "admin",
            "",
        )
        assert result["success"] is False

    def test_write_products_create(self):
        with patch("app.services.get_products_service") as mock_get:
            mock_get.return_value.create_product.return_value = {"success": True}
            result = _registered_router_business_db(
                "write",
                {"entity": "products", "operation": "create", "payload": {"name": "P1", "unit_name": "U1"}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_products_unsupported_op(self):
        result = _registered_router_business_db(
            "write",
            {"entity": "products", "operation": "delete", "payload": {}},
            {},
            "admin",
            "",
        )
        assert result["success"] is False

    def test_write_materials_create(self):
        with patch("app.application.get_material_application_service") as mock_get:
            mock_get.return_value.create_material.return_value = {"success": True}
            result = _registered_router_business_db(
                "write",
                {"entity": "materials", "operation": "create", "payload": {"name": "M1"}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_materials_unsupported_op(self):
        result = _registered_router_business_db(
            "write",
            {"entity": "materials", "operation": "fly", "payload": {}},
            {},
            "admin",
            "",
        )
        assert result["success"] is False

    def test_write_shipment_records_update(self):
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_get.return_value.update_shipment_record.return_value = {"success": True}
            result = _registered_router_business_db(
                "write",
                {"entity": "shipment_records", "operation": "update", "payload": {"id": 1}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_shipment_records_unsupported_op(self):
        result = _registered_router_business_db(
            "write",
            {"entity": "shipment_records", "operation": "create", "payload": {}},
            {},
            "admin",
            "",
        )
        assert result["success"] is False


# ===========================================================================
# _registered_router_dataset_rag
# ===========================================================================


class TestDatasetRagRouter:
    def test_missing_dataset_id(self):
        result = _registered_router_dataset_rag("ingest_document", {}, {}, "admin", "")
        assert result["success"] is False
        assert "dataset_id" in result["message"]

    def test_ingest_document(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.ingest_document.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "ingest_document", {"dataset_id": "ds1", "text": "hello"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["dataset_id"] == "ds1"

    def test_query_missing_query(self):
        result = _registered_router_dataset_rag(
            "query", {"dataset_id": "ds1"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_query_with_answer(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.answer.return_value = {"success": True, "answer": "A"}
            result = _registered_router_dataset_rag(
                "query", {"dataset_id": "ds1", "query": "what?"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_query_without_answer(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.query.return_value = {"success": True, "chunks": []}
            result = _registered_router_dataset_rag(
                "query",
                {"dataset_id": "ds1", "query": "what?", "include_answer": "false"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_diff_versions_missing_source(self):
        result = _registered_router_dataset_rag(
            "diff_versions", {"dataset_id": "ds1"}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "source" in result["message"]

    def test_diff_versions_missing_from_version(self):
        result = _registered_router_dataset_rag(
            "diff_versions", {"dataset_id": "ds1", "source": "doc1"}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "from_version" in result["message"]

    def test_diff_versions_success(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.diff_versions.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "diff_versions",
                {"dataset_id": "ds1", "source": "doc1", "from_version": "v1"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_rollback_version_missing_source(self):
        result = _registered_router_dataset_rag(
            "rollback_version", {"dataset_id": "ds1"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_rollback_version_missing_target(self):
        result = _registered_router_dataset_rag(
            "rollback_version",
            {"dataset_id": "ds1", "source": "doc1"},
            {},
            "admin",
            "",
        )
        assert result["success"] is False

    def test_rollback_version_success(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.rollback_document_version.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "rollback_version",
                {"dataset_id": "ds1", "source": "doc1", "target_version": "v2"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_rebuild_index(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.start_rebuild_index.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "rebuild_index", {"dataset_id": "ds1"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_cancel_rebuild_missing_job_id(self):
        result = _registered_router_dataset_rag(
            "cancel_rebuild", {"dataset_id": "ds1"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_cancel_rebuild_success(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.cancel_rebuild_job.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "cancel_rebuild", {"dataset_id": "ds1", "job_id": "job1"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_delete_document_missing_id(self):
        result = _registered_router_dataset_rag(
            "delete_document", {"dataset_id": "ds1"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_delete_document_success(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.delete_document.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "delete_document",
                {"dataset_id": "ds1", "document_id": "doc1"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        result = _registered_router_dataset_rag("fly", {"dataset_id": "ds1"}, {}, "admin", "")
        assert result["success"] is False

    def test_access_context_with_explicit_context(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.ingest_document.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "ingest_document",
                {
                    "dataset_id": "ds1",
                    "text": "hello",
                    "access_context": {"tenant_id": "t1", "actor_id": "a1"},
                },
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_access_context_with_admin_flag(self):
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service"
        ) as mock_get:
            mock_get.return_value.ingest_document.return_value = {"success": True}
            result = _registered_router_dataset_rag(
                "ingest_document",
                {"dataset_id": "ds1", "text": "hello", "dataset_admin": "true"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True


# ===========================================================================
# _registered_router_memory_v2
# ===========================================================================


class TestMemoryV2Router:
    def test_missing_user_id(self):
        # user_id defaults to "default" via `or "default"` fallback, so we
        # must pass whitespace-only to make str(...).strip() produce "".
        result = _registered_router_memory_v2(
            "confirm", {"user_id": "  "}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "user_id" in result["message"]

    def test_propose_candidate_missing_key(self):
        with patch(
            "app.services.user_memory_service.get_user_memory_service"
        ):
            result = _registered_router_memory_v2(
                "propose_candidate", {"user_id": "u1", "value": "v"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "key" in result["message"]

    def test_propose_candidate_missing_value(self):
        with patch(
            "app.services.user_memory_service.get_user_memory_service"
        ):
            result = _registered_router_memory_v2(
                "propose_candidate", {"user_id": "u1", "key": "k"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "value" in result["message"]

    def test_propose_candidate_bad_confidence(self):
        with patch(
            "app.services.user_memory_service.get_user_memory_service"
        ):
            result = _registered_router_memory_v2(
                "propose_candidate",
                {"user_id": "u1", "key": "k", "value": "v", "confidence": "abc"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False
        assert "confidence" in result["message"]

    def test_propose_candidate_value_error(self):
        mock_svc = MagicMock()
        mock_svc.propose_memory_candidate.side_effect = ValueError("bad type")
        with patch(
            "app.services.user_memory_service.get_user_memory_service",
            return_value=mock_svc,
        ):
            result = _registered_router_memory_v2(
                "propose_candidate",
                {"user_id": "u1", "key": "k", "value": "v"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False
        assert "bad type" in result["message"]

    def test_propose_candidate_success(self):
        mock_svc = MagicMock()
        mock_svc.propose_memory_candidate.return_value = {"success": True}
        with patch(
            "app.services.user_memory_service.get_user_memory_service",
            return_value=mock_svc,
        ):
            result = _registered_router_memory_v2(
                "propose_candidate",
                {"user_id": "u1", "key": "k", "value": "v", "evidence": ["e1"]},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_missing_memory_id(self):
        with patch(
            "app.services.user_memory_service.get_user_memory_service"
        ):
            result = _registered_router_memory_v2(
                "confirm", {"user_id": "u1"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "memory_id" in result["message"]

    def test_confirm(self):
        mock_svc = MagicMock()
        mock_svc.confirm_memory_candidate.return_value = {"success": True}
        with patch(
            "app.services.user_memory_service.get_user_memory_service",
            return_value=mock_svc,
        ):
            result = _registered_router_memory_v2(
                "confirm",
                {"user_id": "u1", "memory_id": "m1", "correction": {"k": "v"}},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_reject(self):
        mock_svc = MagicMock()
        mock_svc.reject_memory_candidate.return_value = {"success": True}
        with patch(
            "app.services.user_memory_service.get_user_memory_service",
            return_value=mock_svc,
        ):
            result = _registered_router_memory_v2(
                "reject",
                {"user_id": "u1", "memory_id": "m1", "reason": "bad"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_correct(self):
        mock_svc = MagicMock()
        mock_svc.correct_memory.return_value = {"success": True}
        with patch(
            "app.services.user_memory_service.get_user_memory_service",
            return_value=mock_svc,
        ):
            result = _registered_router_memory_v2(
                "correct",
                {"user_id": "u1", "memory_id": "m1", "value": "new", "key": "k"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_delete(self):
        mock_svc = MagicMock()
        mock_svc.delete_memory.return_value = {"success": True}
        with patch(
            "app.services.user_memory_service.get_user_memory_service",
            return_value=mock_svc,
        ):
            result = _registered_router_memory_v2(
                "delete",
                {"user_id": "u1", "memory_id": "m1"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        with patch(
            "app.services.user_memory_service.get_user_memory_service"
        ):
            result = _registered_router_memory_v2(
                "fly", {"user_id": "u1", "memory_id": "m1"}, {}, "admin", ""
            )
        assert result["success"] is False


# ===========================================================================
# _registered_router_excel_analysis
# ===========================================================================


class TestExcelAnalysisRouter:
    def test_missing_file_path_no_context(self):
        result = _registered_router_excel_analysis("read", {}, {}, "admin", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_file_path_from_excel_analysis_context(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {"success": True}
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "read",
                {},
                {"excel_analysis": {"file_path": "/tmp/x.xlsx"}},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_file_path_from_last_excel_analysis_context(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {"success": True}
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "read",
                {},
                {"last_excel_analysis_context": {"result": {"file_path": "/tmp/x.xlsx"}}},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_import_error(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if "excel_toolkit" in name or "excel_analyzer" in name:
                raise ImportError("no skill")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _registered_router_excel_analysis(
                "read", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_read_action(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {"success": True, "content": []}
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "read", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_structure_action(self):
        mock_toolkit = MagicMock()
        mock_analyzer = MagicMock()
        mock_analyzer.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "structure", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_statistics_action_with_values(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 1}, {"value": 2}, {"value": "x"}]}],
            "row_count": 1,
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["statistics"]["count"] == 2

    def test_statistics_action_no_values(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": "x"}]}],
            "row_count": 1,
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["statistics"]["count"] == 0

    def test_statistics_action_view_fails(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {"success": False}
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_query_no_question(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 1}]}],
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "data" in result

    def test_query_sum_question(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 1}, {"value": 2}]}],
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "query",
                {"file_path": "/tmp/x.xlsx", "question": "总和是多少"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert "total" in result

    def test_query_max_question(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 5}, {"value": 3}]}],
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "query",
                {"file_path": "/tmp/x.xlsx", "question": "最大值"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["max"] == 5

    def test_query_max_no_values(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": None}]}],
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "query",
                {"file_path": "/tmp/x.xlsx", "question": "最大值"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert "未找到" in result["answer"]

    def test_query_view_fails(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {"success": False}
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/x.xlsx", "question": "x"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_query_default_branch(self):
        mock_toolkit = MagicMock()
        mock_toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 1}]}],
        }
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "query",
                {"file_path": "/tmp/x.xlsx", "question": "随便看看"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        mock_toolkit = MagicMock()
        mock_analyzer = MagicMock()
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=mock_toolkit,
        ), patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=mock_analyzer,
        ):
            result = _registered_router_excel_analysis(
                "fly", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False


# ===========================================================================
# _registered_router_excel_vector_index
# ===========================================================================


class TestExcelVectorIndexRouter:
    def test_execute_missing_file_path(self):
        result = _registered_router_excel_vector_index("execute", {}, {}, "admin", "")
        assert result["success"] is False

    def test_execute_success(self):
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service"
        ) as mock_get:
            mock_get.return_value.ingest_excel.return_value = {
                "success": True,
                "index_id": "idx1",
            }
            result = _registered_router_excel_vector_index(
                "execute", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["excel_vector_index_id"] == "idx1"

    def test_execute_exception(self):
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service"
        ) as mock_get:
            mock_get.return_value.ingest_excel.side_effect = RuntimeError("boom")
            result = _registered_router_excel_vector_index(
                "execute", {"file_path": "/tmp/x.xlsx"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "boom" in result["message"]

    def test_query_missing_index_id(self):
        result = _registered_router_excel_vector_index("query", {}, {}, "admin", "")
        assert result["success"] is False

    def test_query_missing_query_text(self):
        result = _registered_router_excel_vector_index(
            "query", {"index_id": "idx1"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_query_bad_top_k(self):
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service"
        ) as mock_get:
            mock_get.return_value.query.return_value = {"success": True}
            result = _registered_router_excel_vector_index(
                "query",
                {"index_id": "idx1", "query": "hello", "top_k": "bad"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_query_success(self):
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service"
        ) as mock_get:
            mock_get.return_value.query.return_value = {"success": True, "results": []}
            result = _registered_router_excel_vector_index(
                "query",
                {"index_id": "idx1", "query": "hello", "query_text": "hi"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_query_exception(self):
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service"
        ) as mock_get:
            mock_get.return_value.query.side_effect = RuntimeError("fail")
            result = _registered_router_excel_vector_index(
                "query", {"index_id": "idx1", "query": "hello"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_unknown_action(self):
        result = _registered_router_excel_vector_index("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ===========================================================================
# _ocr_artifact_payload + _registered_router_ocr
# ===========================================================================


class TestOcrArtifactPayload:
    def test_basic_payload(self):
        payload = _ocr_artifact_payload(
            text="hello",
            file_path="/tmp/img.png",
            structured_data={"name": "Alice"},
            analysis={"confidence": 0.9},
            confidence=0.95,
        )
        assert payload["artifact_type"] == "ocr_text"
        assert payload["preview"]["text"] == "hello"
        assert payload["preview"]["confidence"] == 0.95
        assert len(payload["fields"]) == 1

    def test_empty_structured_data(self):
        payload = _ocr_artifact_payload(text="hello", structured_data=None)
        assert payload["fields"] == []
        assert payload["preview"]["structured_data"] == {}

    def test_filters_empty_values(self):
        payload = _ocr_artifact_payload(
            text="hello",
            structured_data={"a": "x", "b": "", "c": None, "d": [], "e": {}},
        )
        assert len(payload["fields"]) == 1
        assert payload["fields"][0]["name"] == "a"


class TestOcrRouter:
    def test_request_missing_request_id(self):
        result = _registered_router_ocr("request", {}, {}, "admin", "")
        assert result["success"] is False

    def test_request_missing_image_url(self):
        result = _registered_router_ocr("request", {"request_id": "r1"}, {}, "admin", "")
        assert result["success"] is False

    def test_request_success(self):
        with patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain") as mock_get:
            mock_get.return_value.emit_ocr_requested.return_value = True
            result = _registered_router_ocr(
                "request",
                {"request_id": "r1", "image_url": "http://img.png"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["event"] == "ocr.requested"

    def test_request_failure(self):
        with patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain") as mock_get:
            mock_get.return_value.emit_ocr_requested.return_value = False
            result = _registered_router_ocr(
                "request",
                {"request_id": "r1", "image_url": "http://img.png"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False

    def test_recognize_missing_file_path(self):
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("recognize", {}, {}, "admin", "")
        assert result["success"] is False

    def test_recognize_success(self):
        mock_service = MagicMock()
        mock_service.recognize_file.return_value = {"success": True, "text": "hello"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_service):
            result = _registered_router_ocr(
                "recognize", {"file_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert len(result["artifacts"]) >= 1

    def test_recognize_failure(self):
        mock_service = MagicMock()
        mock_service.recognize_file.return_value = {"success": False}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_service):
            result = _registered_router_ocr(
                "recognize", {"file_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_extract_missing_text(self):
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("extract", {}, {}, "admin", "")
        assert result["success"] is False

    def test_extract_success(self):
        mock_service = MagicMock()
        mock_service.extract_structured_data.return_value = {"name": "Alice"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_service):
            result = _registered_router_ocr(
                "extract", {"text": "hello"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_analyze_missing_text(self):
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("analyze", {}, {}, "admin", "")
        assert result["success"] is False

    def test_analyze_success(self):
        mock_service = MagicMock()
        mock_service.analyze_text.return_value = {"confidence": 0.9}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_service):
            result = _registered_router_ocr(
                "analyze", {"text": "hello"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_recognize_and_extract_missing_file_path(self):
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("recognize_and_extract", {}, {}, "admin", "")
        assert result["success"] is False

    def test_recognize_and_extract_recognize_fails(self):
        mock_service = MagicMock()
        mock_service.recognize_file.return_value = {"success": False}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_service):
            result = _registered_router_ocr(
                "recognize_and_extract", {"file_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_recognize_and_extract_success(self):
        mock_service = MagicMock()
        mock_service.recognize_file.return_value = {"success": True, "text": "hello"}
        mock_service.extract_structured_data.return_value = {"name": "Alice"}
        mock_service.analyze_text.return_value = {"confidence": 0.9}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_service):
            result = _registered_router_ocr(
                "recognize_and_extract", {"file_path": "/tmp/img.png"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert len(result["artifacts"]) == 1

    def test_exception_returns_error(self):
        with patch(
            "app.fastapi_routes.ocr._get_ocr_service",
            side_effect=RuntimeError("ocr unavailable"),
        ):
            result = _registered_router_ocr("recognize", {}, {}, "admin", "")
        assert result["success"] is False
        assert result["error_code"] == "ocr_exception"

    def test_unknown_action(self):
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ===========================================================================
# _registered_router_excel_import + _execute_excel_import_records
# ===========================================================================


class TestExcelImportRouter:
    def test_execute_import_missing_id(self):
        result = _registered_router_excel_import("execute_import", {}, {}, "admin", "")
        assert result["success"] is False

    def test_execute_import_not_found(self):
        with patch("app.application.get_ai_chat_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc._pending_excel_imports = {}
            mock_get.return_value = mock_svc
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "x1"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_execute_import_bad_records(self):
        with patch("app.application.get_ai_chat_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc._pending_excel_imports = {"x1": {"records": "not-a-list"}}
            mock_get.return_value = mock_svc
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "x1"}, {}, "admin", ""
            )
        assert result["success"] is False

    def test_execute_import_success(self):
        with patch("app.application.get_ai_chat_app_service") as mock_get, patch(
            "app.services.tools_workflow_registered._execute_excel_import_records",
            return_value={"success": True},
        ) as mock_exec:
            mock_svc = MagicMock()
            # Use a real dict so .get() works, but track pop via a separate mock
            pending = {"x1": {"records": [{"unit_name": "Co"}]}}
            mock_svc._pending_excel_imports = pending
            mock_get.return_value = mock_svc
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "x1"}, {}, "admin", ""
            )
        assert result["success"] is True
        # The pending import should have been popped
        assert "x1" not in pending

    def test_import_records_not_list(self):
        result = _registered_router_excel_import(
            "import_records", {"records": "bad"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_import_records_success(self):
        with patch(
            "app.services.tools_workflow_registered._execute_excel_import_records",
            return_value={"success": True},
        ):
            result = _registered_router_excel_import(
                "import_records", {"records": [{"unit_name": "Co"}]}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_unknown_action(self):
        result = _registered_router_excel_import("fly", {}, {}, "admin", "")
        assert result["success"] is False


class TestExecuteExcelImportRecords:
    def test_empty_records(self):
        result = _execute_excel_import_records([])
        assert result["success"] is False

    def test_import_success(self):
        with patch("app.bootstrap.get_products_service") as mock_products, patch(
            "app.bootstrap.get_customer_app_service"
        ) as mock_customers:
            mock_products.return_value.get_products.return_value = {"success": True, "data": []}
            mock_products.return_value.create_product.return_value = {"success": True}
            mock_customers.return_value.match_purchase_unit.return_value = None
            mock_customers.return_value.create.return_value = {"success": True}
            result = _execute_excel_import_records(
                [{"unit_name": "Co", "product_name": "P1", "model_number": "M1", "unit_price": 1.0}]
            )
        assert result["success"] is True
        assert result["data"]["result"]["created_products"] == 1

    def test_import_skips_existing(self):
        with patch("app.bootstrap.get_products_service") as mock_products, patch(
            "app.bootstrap.get_customer_app_service"
        ) as mock_customers:
            mock_products.return_value.get_products.return_value = {
                "success": True,
                "data": [{"name": "P1", "model_number": "M1"}],
            }
            mock_customers.return_value.match_purchase_unit.return_value = MagicMock()
            result = _execute_excel_import_records(
                [{"unit_name": "Co", "product_name": "P1", "model_number": "M1", "unit_price": 1.0}]
            )
        assert result["success"] is True
        assert result["data"]["result"]["skipped_products"] == 1

    def test_import_customer_service_unavailable(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "app.bootstrap" and "get_customer_app_service" in str(args):
                raise ImportError("no service")
            return real_import(name, *args, **kwargs)

        with patch("app.bootstrap.get_products_service") as mock_products, patch(
            "builtins.__import__", side_effect=fake_import
        ):
            mock_products.return_value.get_products.return_value = {"success": True, "data": []}
            mock_products.return_value.create_product.return_value = {"success": True}
            result = _execute_excel_import_records(
                [{"unit_name": "Co", "product_name": "P1", "model_number": "M1", "unit_price": 1.0}]
            )
        assert result["success"] is True

    def test_import_exception(self):
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("boom")):
            result = _execute_excel_import_records(
                [{"unit_name": "Co", "product_name": "P1", "model_number": "M1", "unit_price": 1.0}]
            )
        assert result["success"] is False


# ===========================================================================
# _registered_router_unit_products_import
# ===========================================================================


class TestUnitProductsImportRouter:
    def test_unknown_action(self):
        result = _registered_router_unit_products_import("fly", {}, {}, "admin", "")
        assert result["success"] is False

    def test_missing_saved_name(self):
        result = _registered_router_unit_products_import(
            "execute_import", {"unit_name": "Co"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_missing_unit_name(self):
        result = _registered_router_unit_products_import(
            "execute_import", {"saved_name": "f.xlsx"}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_import_success(self):
        with patch(
            "app.application.get_unit_products_import_app_service"
        ) as mock_get:
            mock_get.return_value.import_unit_products.return_value = {
                "success": True,
                "created_unit": True,
                "created_products": 5,
                "imported": 5,
            }
            result = _registered_router_unit_products_import(
                "execute_import",
                {"saved_name": "f.xlsx", "unit_name": "Co"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["data"]["unit_name"] == "Co"

    def test_import_exception(self):
        with patch(
            "app.application.get_unit_products_import_app_service",
            side_effect=RuntimeError("boom"),
        ):
            result = _registered_router_unit_products_import(
                "execute_import",
                {"saved_name": "f.xlsx", "unit_name": "Co"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False


# ===========================================================================
# _registered_router_print — workflow_label_dispatch + save_printer_selection
# ===========================================================================


class TestPrintRouterWorkflowLabel:
    def test_workflow_label_dispatch_missing_model_number(self):
        result = _registered_router_print(
            "workflow_label_dispatch", {}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "model_number" in result["message"]

    def test_workflow_label_dispatch_no_product_found(self):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_print, patch(
            "app.application.get_product_app_service"
        ) as mock_products:
            mock_products.return_value.search_products.return_value = []
            mock_print.return_value.print_single_label.return_value = {"success": True}
            result = _registered_router_print(
                "workflow_label_dispatch",
                {"model_number": "M1", "quantity": 5},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_workflow_label_dispatch_with_product(self):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_print, patch(
            "app.application.get_product_app_service"
        ) as mock_products:
            mock_products.return_value.search_products.return_value = [
                {"name": "Widget", "specification": "spec", "unit": "个"}
            ]
            mock_print.return_value.print_single_label.return_value = {"success": True}
            result = _registered_router_print(
                "workflow_label_dispatch",
                {"model_number": "M1"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_workflow_label_dispatch_product_lookup_fails(self):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_print, patch(
            "app.application.get_product_app_service",
            side_effect=RuntimeError("db down"),
        ):
            mock_print.return_value.print_single_label.return_value = {"success": True}
            result = _registered_router_print(
                "workflow_label_dispatch",
                {"model_number": "M1"},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_workflow_label_dispatch_quantity_clamped(self):
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_print, patch(
            "app.application.get_product_app_service"
        ) as mock_products:
            mock_products.return_value.search_products.return_value = []
            mock_print.return_value.print_single_label.return_value = {"success": True}
            _registered_router_print(
                "workflow_label_dispatch",
                {"model_number": "M1", "quantity": 200},
                {},
                "admin",
                "",
            )
        call_kwargs = mock_print.return_value.print_single_label.call_args.kwargs
        assert call_kwargs["quantity"] == 100


class TestPrintRouterSavePrinterSelection:
    def test_invalid_document_printer(self):
        with patch("app.services.get_printer_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_printers.return_value = {"printers": [{"name": "HP"}]}
            mock_get.return_value = mock_svc
            result = _registered_router_print(
                "save_printer_selection",
                {"document_printer": "Epson"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False
        assert "发货单" in result["message"]

    def test_invalid_label_printer(self):
        with patch("app.services.get_printer_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_printers.return_value = {"printers": [{"name": "HP"}]}
            mock_get.return_value = mock_svc
            result = _registered_router_print(
                "save_printer_selection",
                {"document_printer": "HP", "label_printer": "Epson"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False
        assert "标签" in result["message"]

    def test_valid_selection_none_printers(self):
        with patch("app.services.get_printer_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_printers.return_value = {"printers": "not-a-list"}
            mock_svc.save_printer_selection.return_value = {"success": True}
            mock_svc.classify_printers.return_value = {}
            mock_get.return_value = mock_svc
            result = _registered_router_print(
                "save_printer_selection",
                {"document_printer": None, "label_printer": None},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_valid_selection_success(self):
        with patch("app.services.get_printer_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.get_printers.return_value = {"printers": [{"name": "HP"}]}
            mock_svc.save_printer_selection.return_value = {"success": True}
            mock_svc.classify_printers.return_value = {"label_printers": []}
            mock_get.return_value = mock_svc
            result = _registered_router_print(
                "save_printer_selection",
                {"document_printer": "HP", "label_printer": ""},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        with patch("app.services.get_printer_service"):
            result = _registered_router_print("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ===========================================================================
# _registered_router_employee
# ===========================================================================


class TestEmployeeRouter:
    def test_list_action(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build:
            mock_build.return_value = {"registered_tool_count": 3}
            result = _registered_router_employee("list", {}, {}, "admin", "")
        assert result["success"] is True
        assert result["data"]["registered_tool_count"] == 3

    def test_query_alias(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build:
            mock_build.return_value = {"registered_tool_count": 1}
            result = _registered_router_employee("query", {}, {}, "admin", "")
        assert result["success"] is True

    def test_unknown_action(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ):
            result = _registered_router_employee("fly", {}, {}, "admin", "")
        assert result["success"] is False

    def test_execute_missing_employee_id_no_message(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build:
            mock_build.return_value = {"employee_pack_tools": []}
            result = _registered_router_employee("execute", {}, {}, "admin", "")
        assert result["success"] is False
        assert "employee_id" in result["message"]

    def test_execute_missing_employee_id_with_user_message_match(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build, patch(
            "app.application.employee_runtime.executor.execute_employee_task_local"
        ) as mock_exec:
            mock_build.return_value = {
                "employee_pack_tools": [{"pack_id": "emp-001"}]
            }
            mock_exec.return_value = {"success": True}
            result = _registered_router_employee(
                "execute",
                {},
                {},
                "admin",
                "please run emp-001 for me",
            )
        assert result["success"] is True
        assert result["employee_id"] == "emp-001"

    def test_execute_missing_task(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build:
            mock_build.return_value = {"employee_pack_tools": []}
            result = _registered_router_employee(
                "execute", {"employee_id": "emp-001"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "task" in result["message"]

    def test_execute_success(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build, patch(
            "app.application.employee_runtime.executor.execute_employee_task_local"
        ) as mock_exec:
            mock_build.return_value = {"employee_pack_tools": []}
            mock_exec.return_value = {"success": True}
            result = _registered_router_employee(
                "execute",
                {"employee_id": "emp-001", "task": "do work"},
                {"user_id": "abc"},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_execute_blocked_by_risk_gate(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build, patch(
            "app.application.employee_runtime.executor.execute_employee_task_local"
        ) as mock_exec:
            mock_build.return_value = {"employee_pack_tools": []}
            mock_exec.return_value = {"success": True, "blocked_by_risk_gate": True}
            result = _registered_router_employee(
                "execute",
                {"employee_id": "emp-001", "task": "do work"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False

    def test_execute_with_input_data(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_build, patch(
            "app.application.employee_runtime.executor.execute_employee_task_local"
        ) as mock_exec:
            mock_build.return_value = {"employee_pack_tools": []}
            mock_exec.return_value = {"success": True}
            result = _registered_router_employee(
                "execute",
                {
                    "employee_id": "emp-001",
                    "task": "do work",
                    "input": {"key": "val"},
                    "extra_param": "x",
                },
                {"session_id": "s1"},
                "admin",
                "msg",
            )
        assert result["success"] is True
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["session_id"] == "s1"


# ===========================================================================
# execute_registered_workflow_tool — employee tool dispatch
# ===========================================================================


class TestExecuteRegisteredWorkflowToolEmployee:
    def test_dispatches_employee_tool(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="admin",
        ), patch(
            "app.mod_sdk.employee_tool_registry.execute_employee_tool",
            return_value='{"success": true}',
        ) as mock_exec, patch(
            "app.mod_sdk.employee_tool_registry.is_employee_tool",
            return_value=True,
        ):
            result = execute_registered_workflow_tool(
                "custom-emp-tool",
                "run",
                {"task": "do something", "_runtime_context": {"workspace_root": "/tmp"}},
            )
        assert result["success"] is True
        mock_exec.assert_called_once()

    def test_employee_tool_returns_non_dict_json(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="admin",
        ), patch(
            "app.mod_sdk.employee_tool_registry.execute_employee_tool",
            return_value='"just a string"',
        ), patch(
            "app.mod_sdk.employee_tool_registry.is_employee_tool",
            return_value=True,
        ):
            result = execute_registered_workflow_tool(
                "custom-emp-tool", "run", {}
            )
        assert result["success"] is False

    def test_employee_tool_dispatch_exception(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="admin",
        ), patch(
            "app.mod_sdk.employee_tool_registry.execute_employee_tool",
            side_effect=RuntimeError("boom"),
        ), patch(
            "app.mod_sdk.employee_tool_registry.is_employee_tool",
            return_value=True,
        ):
            result = execute_registered_workflow_tool(
                "custom-emp-tool", "run", {}
            )
        assert result["success"] is False

    def test_unknown_tool_returns_failure(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="admin",
        ), patch(
            "app.mod_sdk.employee_tool_registry.is_employee_tool",
            return_value=False,
        ):
            result = execute_registered_workflow_tool(
                "nonexistent-tool", "run", {}
            )
        assert result["success"] is False
        assert "未注册" in result["message"]
