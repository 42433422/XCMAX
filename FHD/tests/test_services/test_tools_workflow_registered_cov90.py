"""覆盖补强：tools_workflow_registered 未测路由（business_event/system_maintenance/
finance/ocr/dataset_rag/memory_v2/excel_analysis/excel_vector_index/excel_import/
unit_products_import/business_db-write/employee/skills/dispatcher 等）。

全部 mock 外部依赖，离线/确定性。仅断言真实返回值与副作用。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.tools_workflow_registered import (
    _execute_excel_import_records,
    _normalize_business_db_entity,
    _ocr_artifact_payload,
    _registered_router_business_db,
    _registered_router_business_event,
    _registered_router_dataset_rag,
    _registered_router_employee,
    _registered_router_excel_analysis,
    _registered_router_excel_analyzer,
    _registered_router_excel_import,
    _registered_router_excel_toolkit,
    _registered_router_excel_vector_index,
    _registered_router_finance,
    _registered_router_label_template_generator,
    _registered_router_memory_v2,
    _registered_router_ocr,
    _registered_router_system_maintenance,
    _registered_router_unit_products_import,
    execute_registered_workflow_tool,
)

# ---------------------------------------------------------------------------
# _registered_router_finance
# ---------------------------------------------------------------------------


class TestFinanceRouter:
    def test_create_transaction(self):
        svc = MagicMock()
        svc.create_transaction.return_value = {"success": True, "id": 1}
        with patch("app.application.finance_app_service.FinanceAppService", return_value=svc):
            result = _registered_router_finance(
                "create_transaction", {"amount": 100}, {}, "admin", ""
            )
        assert result["success"] is True
        svc.create_transaction.assert_called_once_with({"amount": 100})

    def test_update_transaction(self):
        svc = MagicMock()
        svc.update_transaction.return_value = {"success": True}
        with patch("app.application.finance_app_service.FinanceAppService", return_value=svc):
            result = _registered_router_finance(
                "update_transaction", {"transaction_id": 7, "amount": 50}, {}, "admin", ""
            )
        assert result["success"] is True
        svc.update_transaction.assert_called_once_with(7, {"amount": 50})

    def test_delete_transaction(self):
        svc = MagicMock()
        svc.delete_transaction.return_value = {"success": True}
        with patch("app.application.finance_app_service.FinanceAppService", return_value=svc):
            result = _registered_router_finance(
                "delete_transaction", {"transaction_id": 9}, {}, "admin", ""
            )
        assert result["success"] is True
        svc.delete_transaction.assert_called_once_with(9)

    def test_unknown_action(self):
        svc = MagicMock()
        with patch("app.application.finance_app_service.FinanceAppService", return_value=svc):
            result = _registered_router_finance("fly", {}, {}, "admin", "")
        assert result["success"] is False
        assert "未注册" in result["message"]

    def test_fastapi_finance_route_source(self):
        svc = MagicMock()
        svc.create_transaction.return_value = {"success": True}
        with patch("app.fastapi_routes.finance._svc", return_value=svc):
            result = _registered_router_finance(
                "create_transaction",
                {"amount": 1},
                {"service_source": "fastapi_finance_route"},
                "admin",
                "",
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_business_event
# ---------------------------------------------------------------------------


class TestBusinessEventRouter:
    def test_print_label_success(self):
        domain = MagicMock()
        domain.emit_job_submitted.return_value = True
        with patch("app.neuro_bus.domains.print_domain.get_print_domain", return_value=domain):
            result = _registered_router_business_event(
                "print_label",
                {"job_id": "J1", "document_name": "doc", "printer_id": "p1", "copies": 3},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["job_id"] == "J1"
        assert result["event"] == "print.job.submitted"
        domain.emit_job_submitted.assert_called_once_with(
            job_id="J1", document_name="doc", printer_id="p1", copies=3
        )

    def test_print_label_generates_job_id_when_missing(self):
        domain = MagicMock()
        domain.emit_job_submitted.return_value = True
        with patch("app.neuro_bus.domains.print_domain.get_print_domain", return_value=domain):
            result = _registered_router_business_event("print_label", {}, {}, "admin", "")
        assert result["success"] is True
        # job_id auto-generated (uuid4 hex form), non-empty
        assert result["job_id"]

    def test_inventory_update(self):
        domain = MagicMock()
        domain.emit_stock_changed.return_value = True
        with patch(
            "app.neuro_bus.domains.inventory_domain.get_inventory_domain",
            return_value=domain,
        ):
            result = _registered_router_business_event(
                "inventory_update",
                {"product_id": "P1", "delta": 5, "new_quantity": 20},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["event"] == "inventory.changed"
        domain.emit_stock_changed.assert_called_once()

    def test_shipment_create_published(self):
        with patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            return_value=True,
        ) as mock_pub:
            result = _registered_router_business_event(
                "shipment_create",
                {"unit_name": "Co", "items": [{"id": 1}]},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["published"] is True
        mock_pub.assert_called_once()

    def test_shipment_create_publish_failed(self):
        with patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            return_value=False,
        ):
            result = _registered_router_business_event(
                "shipment_create", {"unit_name": "Co"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert result["published"] is False

    def test_unknown_action(self):
        result = _registered_router_business_event("fly", {}, {}, "admin", "")
        assert result["success"] is False
        assert "未知" in result["message"]


# ---------------------------------------------------------------------------
# _registered_router_system_maintenance
# ---------------------------------------------------------------------------


class TestSystemMaintenanceRouter:
    def test_set_default_printer_success(self):
        svc = MagicMock()
        svc.set_default_printer.return_value = {"success": True}
        with patch("app.application.facades.session_facade.get_system_service", return_value=svc):
            result = _registered_router_system_maintenance(
                "set_default_printer", {"printer_name": "HP"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["http_status_code"] == 200

    def test_enable_startup_failure_sets_500(self):
        svc = MagicMock()
        svc.enable_startup.return_value = {"success": False}
        with patch("app.application.facades.session_facade.get_system_service", return_value=svc):
            result = _registered_router_system_maintenance("enable_startup", {}, {}, "admin", "")
        assert result["success"] is False
        assert result["http_status_code"] == 500

    def test_disable_startup(self):
        svc = MagicMock()
        svc.disable_startup.return_value = {"success": True}
        with patch("app.application.facades.session_facade.get_system_service", return_value=svc):
            result = _registered_router_system_maintenance("disable_startup", {}, {}, "admin", "")
        assert result["http_status_code"] == 200

    def test_backup_database(self):
        svc = MagicMock()
        svc.backup_database.return_value = {"success": True}
        with patch("app.application.facades.session_facade.get_database_service", return_value=svc):
            result = _registered_router_system_maintenance("backup_database", {}, {}, "admin", "")
        assert result["http_status_code"] == 200

    def test_delete_database_backup(self):
        svc = MagicMock()
        svc.delete_backup.return_value = {"success": True}
        with patch("app.application.facades.session_facade.get_database_service", return_value=svc):
            result = _registered_router_system_maintenance(
                "delete_database_backup", {"backup_file": "b.db"}, {}, "admin", ""
            )
        assert result["http_status_code"] == 200
        svc.delete_backup.assert_called_once_with("b.db")

    def test_restore_database_failure_sets_400(self):
        svc = MagicMock()
        svc.restore_database.return_value = {"success": False}
        with patch("app.application.facades.session_facade.get_database_service", return_value=svc):
            result = _registered_router_system_maintenance(
                "restore_database", {"backup_file": "b.db"}, {}, "admin", ""
            )
        assert result["http_status_code"] == 400

    def test_clear_performance_cache_no_redis(self):
        optimizer = MagicMock()
        optimizer.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=optimizer,
        ):
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {}, {}, "admin", ""
            )
        assert result["success"] is False
        assert result["http_status_code"] == 503

    def test_clear_performance_cache_with_pattern(self):
        optimizer = MagicMock()
        optimizer.redis_cache.clear_pattern.return_value = 4
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=optimizer,
        ):
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {"pattern": "abc:*"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "4" in result["message"]
        optimizer.redis_cache.clear_pattern.assert_called_once_with("abc:*")

    def test_clear_performance_cache_local(self):
        optimizer = MagicMock()
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=optimizer,
        ):
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {}, {}, "admin", ""
            )
        assert result["success"] is True
        optimizer.redis_cache.clear_local_cache.assert_called_once()

    def test_invalidate_performance_cache(self):
        optimizer = MagicMock()
        optimizer.redis_cache.delete.return_value = 2
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=optimizer,
        ):
            result = _registered_router_system_maintenance(
                "invalidate_performance_cache", {"keys": ["a", "b"]}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["data"]["deleted_count"] == 2

    def test_invalidate_performance_cache_no_redis(self):
        optimizer = MagicMock()
        optimizer.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=optimizer,
        ):
            result = _registered_router_system_maintenance(
                "invalidate_performance_cache", {"keys": []}, {}, "admin", ""
            )
        assert result["http_status_code"] == 503

    def test_reinitialize_performance(self):
        optimizer = MagicMock()
        optimizer.get_status.return_value = {"ready": True}
        with patch(
            "app.utils.performance_initializer.init_performance_optimization",
            return_value=optimizer,
        ):
            result = _registered_router_system_maintenance(
                "reinitialize_performance", {}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["data"] == {"ready": True}

    def test_unknown_action(self):
        result = _registered_router_system_maintenance("fly", {}, {}, "admin", "")
        assert result["success"] is False
        assert "未知" in result["message"]


# ---------------------------------------------------------------------------
# skills: excel_analyzer / excel_toolkit / label_template_generator
# ---------------------------------------------------------------------------


class TestSkillRouters:
    def test_excel_analyzer_wrong_action(self):
        result = _registered_router_excel_analyzer("view", {"file_path": "/x"}, {}, "a", "")
        assert result["success"] is False
        assert "未知" in result["message"]

    def test_excel_analyzer_missing_file_path(self):
        result = _registered_router_excel_analyzer("analyze", {}, {}, "a", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_excel_analyzer_success(self):
        skill = MagicMock()
        skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=skill,
        ):
            result = _registered_router_excel_analyzer(
                "analyze", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["file_path"] == "/tmp/a.xlsx"

    def test_excel_analyzer_non_dict_result(self):
        skill = MagicMock()
        skill.execute.return_value = "not-a-dict"
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
            return_value=skill,
        ):
            result = _registered_router_excel_analyzer(
                "analyze", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "无效" in result["message"]

    def test_excel_toolkit_wrong_action(self):
        result = _registered_router_excel_toolkit("explode", {"file_path": "/x"}, {}, "a", "")
        assert result["success"] is False
        assert "未知" in result["message"]

    def test_excel_toolkit_missing_file_path(self):
        result = _registered_router_excel_toolkit("view", {}, {}, "a", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_excel_toolkit_success_with_max_rows(self):
        skill = MagicMock()
        skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=skill,
        ):
            result = _registered_router_excel_toolkit(
                "view", {"file_path": "/tmp/a.xlsx", "max_rows": 5}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["file_path"] == "/tmp/a.xlsx"
        assert skill.execute.call_args.kwargs["max_rows"] == 5

    def test_excel_toolkit_defaults_action_to_view(self):
        skill = MagicMock()
        skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
            return_value=skill,
        ):
            _registered_router_excel_toolkit("", {"file_path": "/tmp/a.xlsx"}, {}, "a", "")
        assert skill.execute.call_args.kwargs["action"] == "view"

    def test_label_template_generator_wrong_action(self):
        result = _registered_router_label_template_generator(
            "view", {"image_path": "/x"}, {}, "a", ""
        )
        assert result["success"] is False
        assert "未知" in result["message"]

    def test_label_template_generator_missing_image_path(self):
        result = _registered_router_label_template_generator("execute", {}, {}, "a", "")
        assert result["success"] is False
        assert "image_path" in result["message"]

    def test_label_template_generator_success(self):
        skill = MagicMock()
        skill.execute.return_value = {"success": True}
        with patch(
            "app.infrastructure.skills.label_template_generator.get_label_template_generator_skill",
            return_value=skill,
        ):
            result = _registered_router_label_template_generator(
                "execute", {"image_path": "/tmp/img.png"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["image_path"] == "/tmp/img.png"


# ---------------------------------------------------------------------------
# _registered_router_excel_analysis
# ---------------------------------------------------------------------------


class TestExcelAnalysisRouter:
    def _patch_skills(self, toolkit, analyzer):
        return [
            patch(
                "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill",
                return_value=toolkit,
            ),
            patch(
                "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill",
                return_value=analyzer,
            ),
        ]

    def test_missing_file_path(self):
        result = _registered_router_excel_analysis("read", {}, {}, "a", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_file_path_from_runtime_context(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {"success": True, "content": []}
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "read",
                {},
                {"excel_analysis": {"file_path": "/ctx/a.xlsx"}},
                "a",
                "",
            )
        assert result["success"] is True
        assert toolkit.execute.call_args.kwargs["file_path"] == "/ctx/a.xlsx"

    def test_read_action(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {"success": True, "content": [{"cells": []}]}
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "read", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is True

    def test_structure_action(self):
        toolkit = MagicMock()
        analyzer = MagicMock()
        analyzer.execute.return_value = {"success": True, "fields": []}
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "structure", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is True
        analyzer.execute.assert_called_once_with(file_path="/tmp/a.xlsx")

    def test_statistics_with_numbers(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "row_count": 2,
            "content": [
                {"cells": [{"value": 10}, {"value": 20}]},
                {"cells": [{"value": 30}, {"value": None}]},
            ],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["statistics"]["count"] == 3
        assert result["statistics"]["sum"] == 60.0
        assert result["statistics"]["max"] == 30.0

    def test_statistics_no_numbers(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "row_count": 1,
            "content": [{"cells": [{"value": "text"}]}],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["statistics"] == {"count": 0}

    def test_statistics_view_failed(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {"success": False, "message": "bad"}
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is False

    def test_query_sum_keyword(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 5}, {"value": 15}]}],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/a.xlsx", "question": "总和是多少"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["total"] == 20.0

    def test_query_max_keyword(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 5}, {"value": 99}]}],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/a.xlsx", "question": "最大值"}, {}, "a", ""
            )
        assert result["max"] == 99.0

    def test_query_max_no_values(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": None}]}],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/a.xlsx", "question": "最大"}, {}, "a", ""
            )
        assert result["answer"] == "未找到数值"

    def test_query_no_question_returns_data(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 1}]}],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is True
        assert "data" in result

    def test_query_generic_question(self):
        toolkit = MagicMock()
        toolkit.execute.return_value = {
            "success": True,
            "content": [{"cells": [{"value": 1}]}],
        }
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "query", {"file_path": "/tmp/a.xlsx", "question": "列出全部"}, {}, "a", ""
            )
        assert "message" in result

    def test_unknown_action(self):
        toolkit = MagicMock()
        analyzer = MagicMock()
        p1, p2 = self._patch_skills(toolkit, analyzer)
        with p1, p2:
            result = _registered_router_excel_analysis(
                "fly", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "未知" in result["message"]


# ---------------------------------------------------------------------------
# _registered_router_excel_vector_index
# ---------------------------------------------------------------------------


class TestExcelVectorIndexRouter:
    def test_execute_missing_file_path(self):
        result = _registered_router_excel_vector_index("execute", {}, {}, "a", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_execute_success_enriches_index_id(self):
        svc = MagicMock()
        svc.ingest_excel.return_value = {"success": True, "index_id": "IDX1"}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=svc,
        ):
            result = _registered_router_excel_vector_index(
                "execute", {"file_path": "/tmp/a.xlsx", "index_name": "n"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["excel_vector_index_id"] == "IDX1"
        assert result["excel_index_id"] == "IDX1"

    def test_execute_service_exception(self):
        svc = MagicMock()
        svc.ingest_excel.side_effect = RuntimeError("boom")
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=svc,
        ):
            result = _registered_router_excel_vector_index(
                "execute", {"file_path": "/tmp/a.xlsx"}, {}, "a", ""
            )
        assert result["success"] is False
        assert result["error_code"] == "excel_vector_exception"

    def test_query_missing_index_id(self):
        result = _registered_router_excel_vector_index("query", {"query": "q"}, {}, "a", "")
        assert result["success"] is False
        assert "index_id" in result["message"]

    def test_query_missing_query(self):
        result = _registered_router_excel_vector_index("query", {"index_id": "IDX"}, {}, "a", "")
        assert result["success"] is False
        assert "query" in result["message"]

    def test_query_success(self):
        svc = MagicMock()
        svc.query.return_value = {"success": True, "results": []}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=svc,
        ):
            result = _registered_router_excel_vector_index(
                "query", {"index_id": "IDX", "query": "hello", "top_k": "bad"}, {}, "a", ""
            )
        assert result["success"] is True
        # top_k="bad" → fallback to 5
        assert svc.query.call_args.kwargs["top_k"] == 5

    def test_query_service_exception(self):
        svc = MagicMock()
        svc.query.side_effect = ValueError("nope")
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=svc,
        ):
            result = _registered_router_excel_vector_index(
                "query", {"index_id": "IDX", "query": "x"}, {}, "a", ""
            )
        assert result["success"] is False
        assert result["error_code"] == "excel_vector_exception"

    def test_unknown_action(self):
        result = _registered_router_excel_vector_index("fly", {}, {}, "a", "")
        assert result["success"] is False
        assert "未知" in result["message"]


# ---------------------------------------------------------------------------
# _ocr_artifact_payload + _registered_router_ocr
# ---------------------------------------------------------------------------


class TestOcrArtifactPayload:
    def test_filters_empty_fields_and_truncates_text(self):
        payload = _ocr_artifact_payload(
            text="x" * 2000,
            file_path="/img.png",
            structured_data={"a": "v", "b": "", "c": None},
            confidence=0.8,
        )
        assert payload["artifact_type"] == "ocr_text"
        assert len(payload["preview"]["text"]) == 1000
        names = {f["name"] for f in payload["fields"]}
        assert names == {"a"}  # empty/None filtered out
        assert payload["metadata"]["text"] == "x" * 2000


class TestOcrRouter:
    def test_request_missing_request_id(self):
        result = _registered_router_ocr("request", {"image_url": "u"}, {}, "a", "")
        assert result["success"] is False
        assert "request_id" in result["message"]

    def test_request_missing_image_url(self):
        result = _registered_router_ocr("request", {"request_id": "r1"}, {}, "a", "")
        assert result["success"] is False
        assert "image_url" in result["message"]

    def test_request_published(self):
        domain = MagicMock()
        domain.emit_ocr_requested.return_value = True
        with patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=domain):
            result = _registered_router_ocr(
                "request",
                {"request_id": "r1", "image_url": "http://x/i.png"},
                {},
                "a",
                "",
            )
        assert result["success"] is True
        assert result["published"] is True
        assert result["event"] == "ocr.requested"

    def test_recognize_missing_file_path(self):
        svc = MagicMock()
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("recognize", {}, {}, "a", "")
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_recognize_success_appends_artifact(self):
        svc = MagicMock()
        svc.recognize_file.return_value = {
            "success": True,
            "text": "hello world",
            "confidence": 0.9,
        }
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("recognize", {"file_path": "/tmp/i.png"}, {}, "a", "")
        assert result["success"] is True
        assert result["artifacts"][-1]["artifact_type"] == "ocr_text"

    def test_recognize_failure_returns_as_is(self):
        svc = MagicMock()
        svc.recognize_file.return_value = {"success": False, "message": "bad"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("recognize", {"file_path": "/tmp/i.png"}, {}, "a", "")
        assert result["success"] is False
        assert "artifacts" not in result

    def test_extract_missing_text(self):
        svc = MagicMock()
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("extract", {}, {}, "a", "")
        assert result["success"] is False
        assert "text" in result["message"]

    def test_extract_success(self):
        svc = MagicMock()
        svc.extract_structured_data.return_value = {"name": "Foo"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("extract", {"text": "abc"}, {}, "a", "")
        assert result["success"] is True
        assert result["data"] == {"name": "Foo"}

    def test_analyze_success(self):
        svc = MagicMock()
        svc.analyze_text.return_value = {"sentiment": "neutral"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("analyze", {"text": "abc"}, {}, "a", "")
        assert result["success"] is True
        assert result["data"] == {"sentiment": "neutral"}

    def test_analyze_missing_text(self):
        svc = MagicMock()
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("analyze", {}, {}, "a", "")
        assert result["success"] is False

    def test_recognize_and_extract_success(self):
        svc = MagicMock()
        svc.recognize_file.return_value = {"success": True, "text": "T"}
        svc.extract_structured_data.return_value = {"k": "v"}
        svc.analyze_text.return_value = {"confidence": 0.7}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr(
                "recognize_and_extract", {"file_path": "/tmp/i.png"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["text"] == "T"
        assert result["data"] == {"k": "v"}
        assert result["artifacts"][0]["artifact_type"] == "ocr_text"

    def test_recognize_and_extract_recognize_failure(self):
        svc = MagicMock()
        svc.recognize_file.return_value = {"success": False, "message": "nope"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr(
                "recognize_and_extract", {"file_path": "/tmp/i.png"}, {}, "a", ""
            )
        assert result["success"] is False

    def test_unknown_action(self):
        svc = MagicMock()
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
            result = _registered_router_ocr("fly", {}, {}, "a", "")
        assert result["success"] is False
        assert "未知" in result["message"]

    def test_outer_exception_handled(self):
        # _get_ocr_service raises a recoverable error → outer except branch
        with patch(
            "app.fastapi_routes.ocr._get_ocr_service",
            side_effect=RuntimeError("svc down"),
        ):
            result = _registered_router_ocr("recognize", {"file_path": "/x"}, {}, "a", "")
        assert result["success"] is False
        assert result["error_code"] == "ocr_exception"


# ---------------------------------------------------------------------------
# _registered_router_dataset_rag
# ---------------------------------------------------------------------------


class TestDatasetRagRouter:
    def test_missing_dataset_id(self):
        result = _registered_router_dataset_rag("query", {}, {}, "a", "")
        assert result["success"] is False
        assert "dataset_id" in result["message"]

    def test_ingest_document(self):
        svc = MagicMock()
        svc.ingest_document.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "ingest_document",
                {"dataset_id": "D1", "text": "hello", "permissions": "dataset.write"},
                {},
                "a",
                "",
            )
        assert result["success"] is True
        assert result["dataset_id"] == "D1"
        # access_context built because permissions present
        assert svc.ingest_document.call_args.kwargs["access_context"] is not None

    def test_query_missing_query(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag("query", {"dataset_id": "D1"}, {}, "a", "")
        assert result["success"] is False
        assert "query" in result["message"]

    def test_query_with_answer(self):
        svc = MagicMock()
        svc.answer.return_value = {"success": True, "answer": "A"}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "query", {"dataset_id": "D1", "query": "q"}, {}, "a", ""
            )
        assert result["success"] is True
        svc.answer.assert_called_once()

    def test_query_without_answer_uses_query_method(self):
        svc = MagicMock()
        svc.query.return_value = {"success": True, "chunks": []}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "query",
                {"dataset_id": "D1", "query": "q", "include_answer": False},
                {},
                "a",
                "",
            )
        assert result["success"] is True
        svc.query.assert_called_once()

    def test_diff_versions_missing_source(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "diff_versions", {"dataset_id": "D1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "source" in result["message"]

    def test_diff_versions_missing_from_version(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "diff_versions", {"dataset_id": "D1", "source": "s"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "from_version" in result["message"]

    def test_diff_versions_success(self):
        svc = MagicMock()
        svc.diff_versions.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "diff_versions",
                {"dataset_id": "D1", "source": "s", "from_version": "v1"},
                {},
                "a",
                "",
            )
        assert result["success"] is True

    def test_rollback_missing_source(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "rollback_version", {"dataset_id": "D1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "source" in result["message"]

    def test_rollback_missing_target_version(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "rollback_version", {"dataset_id": "D1", "source": "s"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "target_version" in result["message"]

    def test_rollback_success(self):
        svc = MagicMock()
        svc.rollback_document_version.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "rollback_version",
                {"dataset_id": "D1", "source": "s", "target_version": "v0"},
                {},
                "a",
                "",
            )
        assert result["success"] is True

    def test_rebuild_index(self):
        svc = MagicMock()
        svc.start_rebuild_index.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "rebuild_index", {"dataset_id": "D1"}, {}, "a", ""
            )
        assert result["success"] is True

    def test_cancel_rebuild_missing_job_id(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "cancel_rebuild", {"dataset_id": "D1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "job_id" in result["message"]

    def test_cancel_rebuild_success(self):
        svc = MagicMock()
        svc.cancel_rebuild_job.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "cancel_rebuild", {"dataset_id": "D1", "job_id": "J1"}, {}, "a", ""
            )
        assert result["success"] is True

    def test_delete_document_missing_id(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "delete_document", {"dataset_id": "D1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "document_id" in result["message"]

    def test_delete_document_success(self):
        svc = MagicMock()
        svc.delete_document.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag(
                "delete_document",
                {"dataset_id": "D1", "document_id": "doc1"},
                {},
                "a",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        svc = MagicMock()
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            result = _registered_router_dataset_rag("fly", {"dataset_id": "D1"}, {}, "a", "")
        assert result["success"] is False
        assert "未注册" in result["message"]

    def test_access_context_admin_flag(self):
        svc = MagicMock()
        svc.ingest_document.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            _registered_router_dataset_rag(
                "ingest_document",
                {"dataset_id": "D1", "dataset_admin": "yes"},
                {},
                "a",
                "",
            )
        ctx = svc.ingest_document.call_args.kwargs["access_context"]
        assert ctx is not None and ctx.is_admin is True

    def test_access_context_none_when_no_signal(self):
        svc = MagicMock()
        svc.ingest_document.return_value = {"success": True}
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=svc,
        ):
            _registered_router_dataset_rag("ingest_document", {"dataset_id": "D1"}, {}, "a", "")
        assert svc.ingest_document.call_args.kwargs["access_context"] is None


# ---------------------------------------------------------------------------
# _registered_router_memory_v2
# ---------------------------------------------------------------------------


class TestMemoryV2Router:
    def test_propose_candidate_missing_key(self):
        svc = MagicMock()
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2("propose_candidate", {"value": 1}, {}, "a", "")
        assert result["success"] is False
        assert "key" in result["message"]

    def test_propose_candidate_missing_value(self):
        svc = MagicMock()
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2("propose_candidate", {"key": "k"}, {}, "a", "")
        assert result["success"] is False
        assert "value" in result["message"]

    def test_propose_candidate_bad_confidence(self):
        svc = MagicMock()
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2(
                "propose_candidate",
                {"key": "k", "value": "v", "confidence": "abc"},
                {},
                "a",
                "",
            )
        assert result["success"] is False
        assert "confidence" in result["message"]

    def test_propose_candidate_success(self):
        svc = MagicMock()
        svc.propose_memory_candidate.return_value = {"success": True, "memory_id": "m1"}
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2(
                "propose_candidate",
                {"key": "k", "value": "v", "confidence": 0.9},
                {},
                "a",
                "",
            )
        assert result["success"] is True

    def test_propose_candidate_value_error(self):
        svc = MagicMock()
        svc.propose_memory_candidate.side_effect = ValueError("invalid type")
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2(
                "propose_candidate", {"key": "k", "value": "v"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "invalid type" in result["message"]

    def test_action_requires_memory_id(self):
        svc = MagicMock()
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2("confirm", {}, {}, "a", "")
        assert result["success"] is False
        assert "memory_id" in result["message"]

    def test_confirm(self):
        svc = MagicMock()
        svc.confirm_memory_candidate.return_value = {"success": True}
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2(
                "confirm", {"memory_id": "m1", "correction": {"k": "v"}}, {}, "a", ""
            )
        assert result["success"] is True
        svc.confirm_memory_candidate.assert_called_once()

    def test_reject(self):
        svc = MagicMock()
        svc.reject_memory_candidate.return_value = {"success": True}
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2(
                "reject", {"memory_id": "m1", "reason": "no"}, {}, "a", ""
            )
        assert result["success"] is True

    def test_correct(self):
        svc = MagicMock()
        svc.correct_memory.return_value = {"success": True}
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2(
                "correct", {"memory_id": "m1", "value": "new", "key": "k"}, {}, "a", ""
            )
        assert result["success"] is True

    def test_delete(self):
        svc = MagicMock()
        svc.delete_memory.return_value = {"success": True}
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2("delete", {"memory_id": "m1"}, {}, "a", "")
        assert result["success"] is True

    def test_unknown_action(self):
        svc = MagicMock()
        with patch("app.services.user_memory_service.get_user_memory_service", return_value=svc):
            result = _registered_router_memory_v2("fly", {"memory_id": "m1"}, {}, "a", "")
        assert result["success"] is False
        assert "未注册" in result["message"]


# ---------------------------------------------------------------------------
# _normalize_business_db_entity + _registered_router_business_db (write)
# ---------------------------------------------------------------------------


class TestBusinessDbEntityNormalization:
    def test_direct_alias(self):
        assert _normalize_business_db_entity("customer") == "customers"

    def test_chinese_alias(self):
        assert _normalize_business_db_entity("产品") == "products"

    def test_from_user_message(self):
        assert _normalize_business_db_entity("", "我要查发货单") == "shipment_records"

    def test_empty_returns_empty(self):
        assert _normalize_business_db_entity("", "无关文本") == ""


class TestBusinessDbWriteRouter:
    def test_missing_entity(self):
        result = _registered_router_business_db("write", {}, {}, "a", "")
        assert result["success"] is False
        assert "entity" in result["message"]

    def test_rejects_raw_sql(self):
        result = _registered_router_business_db(
            "write", {"entity": "customers", "sql": "SELECT 1"}, {}, "a", ""
        )
        assert result["success"] is False
        assert "SQL" in result["message"]

    def test_write_unknown_action(self):
        result = _registered_router_business_db("explode", {"entity": "customers"}, {}, "a", "")
        assert result["success"] is False
        assert "business_db" in result["message"]

    def test_write_requires_dict_payload(self):
        result = _registered_router_business_db(
            "write", {"entity": "customers", "payload": "not-dict"}, {}, "a", ""
        )
        assert result["success"] is False
        assert "payload" in result["message"]

    def test_write_customers_ensure_exists(self):
        svc = MagicMock()
        match = MagicMock()
        match.unit_name = "Co"
        svc.match_purchase_unit.return_value = match
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_business_db(
                "write",
                {
                    "entity": "customers",
                    "operation": "upsert",
                    "payload": {"unit_name": "Co"},
                },
                {},
                "a",
                "",
            )
        assert result["success"] is True
        assert result["exists"] is True

    def test_write_customers_unsupported_op(self):
        result = _registered_router_business_db(
            "write",
            {"entity": "customers", "operation": "delete", "payload": {}},
            {},
            "a",
            "",
        )
        assert result["success"] is False
        assert "create/ensure_exists/upsert" in result["message"]

    def test_write_products_create(self):
        svc = MagicMock()
        svc.create_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_business_db(
                "write",
                {
                    "entity": "products",
                    "operation": "create",
                    "payload": {"name_or_model": "P1", "unit_name": "U1"},
                },
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
            "a",
            "",
        )
        assert result["success"] is False
        assert "create" in result["message"]

    def test_write_materials_update(self):
        svc = MagicMock()
        svc.update_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_business_db(
                "write",
                {
                    "entity": "materials",
                    "operation": "update",
                    "payload": {"id": 1, "name": "X"},
                },
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_write_materials_unsupported_op(self):
        result = _registered_router_business_db(
            "write",
            {"entity": "materials", "operation": "weird", "payload": {}},
            {},
            "a",
            "",
        )
        assert result["success"] is False
        assert "materials" in result["message"]

    def test_write_shipment_records_delete(self):
        svc = MagicMock()
        svc.delete_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_business_db(
                "write",
                {
                    "entity": "shipment_records",
                    "operation": "delete",
                    "payload": {"id": 5},
                },
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
            "a",
            "",
        )
        assert result["success"] is False
        assert "shipment_records" in result["message"]

    def test_read_routes_to_materials(self):
        svc = MagicMock()
        svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_business_db(
                "read", {"entity": "materials"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_read_routes_to_shipment_records(self):
        svc = MagicMock()
        svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_business_db(
                "read", {"entity": "shipment_records"}, {}, "admin", ""
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _execute_excel_import_records + _registered_router_excel_import
# ---------------------------------------------------------------------------


class TestExcelImportRecords:
    def test_empty_records(self):
        result = _execute_excel_import_records([])
        assert result["success"] is False
        assert "没有可导入" in result["message"]

    def test_creates_unit_and_product(self):
        products_svc = MagicMock()
        products_svc.get_products.return_value = {"success": True, "data": []}
        products_svc.create_product.return_value = {"success": True}
        customer_svc = MagicMock()
        customer_svc.match_purchase_unit.return_value = None
        customer_svc.create.return_value = {"success": True}
        with (
            patch("app.bootstrap.get_products_service", return_value=products_svc),
            patch("app.bootstrap.get_customer_app_service", return_value=customer_svc),
        ):
            result = _execute_excel_import_records(
                [{"unit_name": "U1", "product_name": "P1", "model_number": "m1"}]
            )
        assert result["success"] is True
        assert result["data"]["result"]["created_units"] == 1
        assert result["data"]["result"]["created_products"] == 1

    def test_skips_existing_product(self):
        products_svc = MagicMock()
        products_svc.get_products.return_value = {
            "success": True,
            "data": [{"name": "P1", "model_number": "M1"}],
        }
        customer_svc = MagicMock()
        customer_svc.match_purchase_unit.return_value = MagicMock()
        with (
            patch("app.bootstrap.get_products_service", return_value=products_svc),
            patch("app.bootstrap.get_customer_app_service", return_value=customer_svc),
        ):
            result = _execute_excel_import_records(
                [{"unit_name": "U1", "product_name": "P1", "model_number": "m1"}]
            )
        assert result["success"] is True
        assert result["data"]["result"]["skipped_products"] == 1

    def test_customer_service_unavailable_degrades(self):
        products_svc = MagicMock()
        products_svc.get_products.return_value = {"success": True, "data": []}
        products_svc.create_product.return_value = {"success": True}
        with (
            patch("app.bootstrap.get_products_service", return_value=products_svc),
            patch(
                "app.bootstrap.get_customer_app_service",
                side_effect=RuntimeError("no customer svc"),
            ),
        ):
            result = _execute_excel_import_records([{"unit_name": "U1", "product_name": "P1"}])
        assert result["success"] is True
        assert result["data"]["result"]["unit_service_available"] is False
        assert "no customer svc" in result["data"]["result"]["unit_service_error"]

    def test_outer_exception(self):
        with patch(
            "app.bootstrap.get_products_service",
            side_effect=RuntimeError("boom"),
        ):
            result = _execute_excel_import_records([{"unit_name": "U1"}])
        assert result["success"] is False
        assert "导入执行失败" in result["message"]


class TestExcelImportRouter:
    def test_execute_import_missing_id(self):
        result = _registered_router_excel_import("execute_import", {}, {}, "a", "")
        assert result["success"] is False
        assert "pending_import_id" in result["message"]

    def test_execute_import_not_found(self):
        ai_svc = MagicMock()
        ai_svc._pending_excel_imports = {}
        with patch("app.application.get_ai_chat_app_service", return_value=ai_svc):
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "PI1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "未找到" in result["message"]

    def test_execute_import_bad_records_format(self):
        ai_svc = MagicMock()
        ai_svc._pending_excel_imports = {"PI1": {"records": "not-a-list"}}
        with patch("app.application.get_ai_chat_app_service", return_value=ai_svc):
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "PI1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "格式错误" in result["message"]

    def test_execute_import_success_pops_pending(self):
        ai_svc = MagicMock()
        ai_svc._pending_excel_imports = {
            "PI1": {"records": [{"unit_name": "U1", "product_name": "P1"}]}
        }
        products_svc = MagicMock()
        products_svc.get_products.return_value = {"success": True, "data": []}
        products_svc.create_product.return_value = {"success": True}
        customer_svc = MagicMock()
        customer_svc.match_purchase_unit.return_value = MagicMock()
        with (
            patch("app.application.get_ai_chat_app_service", return_value=ai_svc),
            patch("app.bootstrap.get_products_service", return_value=products_svc),
            patch("app.bootstrap.get_customer_app_service", return_value=customer_svc),
        ):
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "PI1"}, {}, "a", ""
            )
        assert result["success"] is True
        assert "PI1" not in ai_svc._pending_excel_imports

    def test_import_records_not_list(self):
        result = _registered_router_excel_import("import_records", {"records": "abc"}, {}, "a", "")
        assert result["success"] is False
        assert "数组" in result["message"]

    def test_import_records_success(self):
        products_svc = MagicMock()
        products_svc.get_products.return_value = {"success": True, "data": []}
        products_svc.create_product.return_value = {"success": True}
        customer_svc = MagicMock()
        customer_svc.match_purchase_unit.return_value = MagicMock()
        with (
            patch("app.bootstrap.get_products_service", return_value=products_svc),
            patch("app.bootstrap.get_customer_app_service", return_value=customer_svc),
        ):
            result = _registered_router_excel_import(
                "import_records",
                {"records": [{"unit_name": "U1", "product_name": "P1"}]},
                {},
                "a",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        result = _registered_router_excel_import("fly", {}, {}, "a", "")
        assert result["success"] is False
        assert "未知" in result["message"]


# ---------------------------------------------------------------------------
# _registered_router_unit_products_import
# ---------------------------------------------------------------------------


class TestUnitProductsImportRouter:
    def test_wrong_action(self):
        result = _registered_router_unit_products_import("view", {}, {}, "a", "")
        assert result["success"] is False
        assert "未知" in result["message"]

    def test_missing_saved_name(self):
        result = _registered_router_unit_products_import(
            "execute_import", {"unit_name": "U1"}, {}, "a", ""
        )
        assert result["success"] is False
        assert "saved_name" in result["message"]

    def test_missing_unit_name(self):
        result = _registered_router_unit_products_import(
            "execute_import", {"saved_name": "S1"}, {}, "a", ""
        )
        assert result["success"] is False
        assert "unit_name" in result["message"]

    def test_success_enriches_data(self):
        svc = MagicMock()
        svc.import_unit_products.return_value = {
            "success": True,
            "created_unit": True,
            "created_products": 3,
        }
        with patch("app.application.get_unit_products_import_app_service", return_value=svc):
            result = _registered_router_unit_products_import(
                "execute_import", {"saved_name": "S1", "unit_name": "U1"}, {}, "a", ""
            )
        assert result["success"] is True
        assert result["created_customers"] == 1
        assert result["data"]["unit_name"] == "U1"
        assert result["data"]["saved_name"] == "S1"

    def test_service_exception(self):
        svc = MagicMock()
        svc.import_unit_products.side_effect = RuntimeError("boom")
        with patch("app.application.get_unit_products_import_app_service", return_value=svc):
            result = _registered_router_unit_products_import(
                "execute_import", {"saved_name": "S1", "unit_name": "U1"}, {}, "a", ""
            )
        assert result["success"] is False
        assert "导入执行失败" in result["message"]


# ---------------------------------------------------------------------------
# _registered_router_employee
# ---------------------------------------------------------------------------


class TestEmployeeRouter:
    def test_list_action(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"registered_tool_count": 3, "employee_pack_tools": []},
        ):
            result = _registered_router_employee("list", {}, {}, "a", "")
        assert result["success"] is True
        assert "3" in result["message"]
        assert result["data"]["registered_tool_count"] == 3

    def test_unknown_action(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"registered_tool_count": 0, "employee_pack_tools": []},
        ):
            result = _registered_router_employee("fly", {}, {}, "a", "")
        assert result["success"] is False
        assert "未注册" in result["message"]

    def test_execute_missing_employee_id(self):
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": []},
        ):
            result = _registered_router_employee("execute", {}, {}, "a", "")
        assert result["success"] is False
        assert "employee_id" in result["message"]

    def test_execute_infers_employee_id_from_message(self):
        status = {"employee_pack_tools": [{"pack_id": "emp_alpha", "tool_name": "emp_alpha"}]}
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
                return_value=status,
            ),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True},
            ) as mock_exec,
        ):
            result = _registered_router_employee(
                "execute", {"task": "do it"}, {}, "a", "请让 emp_alpha 干活"
            )
        assert result["success"] is True
        assert result["employee_id"] == "emp_alpha"
        mock_exec.assert_called_once()

    def test_execute_missing_task(self):
        status = {"employee_pack_tools": []}
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value=status,
        ):
            result = _registered_router_employee("execute", {"employee_id": "emp1"}, {}, "a", "")
        assert result["success"] is False
        assert "task" in result["message"]

    def test_execute_success(self):
        status = {"employee_pack_tools": []}
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
                return_value=status,
            ),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True, "output": "ok"},
            ),
        ):
            result = _registered_router_employee(
                "execute",
                {"employee_id": "emp1", "task": "do work", "user_id": "12"},
                {},
                "a",
                "",
            )
        assert result["success"] is True
        assert result["employee_id"] == "emp1"
        assert result["message"] == "员工执行完成"

    def test_execute_blocked_by_risk_gate(self):
        status = {"employee_pack_tools": []}
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
                return_value=status,
            ),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={
                    "success": True,
                    "blocked_by_risk_gate": True,
                    "error": "risk",
                },
            ),
        ):
            result = _registered_router_employee(
                "execute",
                {"employee_id": "emp1", "task": "danger"},
                {},
                "a",
                "",
            )
        assert result["success"] is False
        assert "risk" in result["message"]

    def test_execute_bad_user_id_falls_back_to_zero(self):
        status = {"employee_pack_tools": []}
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
                return_value=status,
            ),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True},
            ) as mock_exec,
        ):
            _registered_router_employee(
                "execute",
                {"employee_id": "emp1", "task": "t", "user_id": "not-a-number"},
                {},
                "a",
                "",
            )
        assert mock_exec.call_args.kwargs["user_id"] == 0


# ---------------------------------------------------------------------------
# execute_registered_workflow_tool — employee-tool dispatch fallback
# ---------------------------------------------------------------------------


class TestExecuteRegisteredWorkflowToolEmployeeFallback:
    def test_employee_tool_dispatched_via_registry(self):
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=True),
            patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                return_value='{"success": true, "output": "done"}',
            ),
        ):
            result = execute_registered_workflow_tool("emp_custom_tool", "execute", {"task": "go"})
        assert result["success"] is True
        assert result["output"] == "done"

    def test_employee_tool_non_dict_json(self):
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=True),
            patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                return_value='"just-a-string"',
            ),
        ):
            result = execute_registered_workflow_tool("emp_x", "execute", {})
        assert result["success"] is False

    def test_employee_tool_registry_error_swallowed(self):
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                side_effect=RuntimeError("registry down"),
            ),
        ):
            result = execute_registered_workflow_tool("unknown_x", "execute", {})
        assert result["success"] is False
        assert "未注册的工具动作" in result["message"]

    def test_not_employee_tool_returns_unregistered(self):
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
        ):
            result = execute_registered_workflow_tool("ghost_tool", "query", {})
        assert result["success"] is False
        assert "未注册的工具动作" in result["message"]
