"""Tests for app.application.ai_chat_app_service — coverage ramp for uncovered branches."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)


def _make_service():
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


# ========================= _default_purchase_unit_for_import ==============


class TestDefaultPurchaseUnitForImport:
    def test_from_request_context_excel_customer_hint(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {}, {"excel_customer_hint": "公司A"}
        )
        assert result == "公司A"

    def test_from_preview_data_customer_hint(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {"customer_hint": "公司B"}, None
        )
        assert result == "公司B"

    def test_from_preview_data_document_customer(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {"document_customer": "公司C"}, None
        )
        assert result == "公司C"

    def test_from_excel_analysis_customer_hint(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {"customer_hint": "公司D"}, {}, None
        )
        assert result == "公司D"

    def test_guess_from_filename(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {"file_name": "某某有限公司产品报价表.xlsx"}, {}, None
        )
        assert "某某有限公司" in result

    def test_empty_all_sources(self):
        result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, None)
        assert result == ""

    def test_none_request_context(self):
        result = AIChatApplicationService._default_purchase_unit_for_import({}, {}, None)
        assert result == ""

    def test_request_context_hint_priority(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {}, {"customer_hint": "低优先级"}, {"excel_customer_hint": "高优先级"}
        )
        assert result == "高优先级"


# ========================= _customer_hint_from_preview_grid ==============


class TestCustomerHintFromPreviewGrid:
    def test_non_dict_preview(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid(None)
        assert result == ""

    def test_empty_preview(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid({})
        assert result == ""

    def test_no_grid_preview(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid({"other": "data"})
        assert result == ""

    def test_grid_preview_no_rows(self):
        result = AIChatApplicationService._customer_hint_from_preview_grid({"grid_preview": {}})
        assert result == ""


# ========================= _try_structured_reload_records =================


class TestTryStructuredReloadRecords:
    def test_no_file_path(self):
        result = AIChatApplicationService._try_structured_reload_records({}, {})
        assert result is None

    def test_file_not_exists(self):
        result = AIChatApplicationService._try_structured_reload_records(
            {"file_path": "/nonexistent/path.xlsx"}, {}
        )
        assert result is None

    def test_empty_preview_path(self):
        result = AIChatApplicationService._try_structured_reload_records(
            {"file_path": ""}, {"file_path": ""}
        )
        assert result is None


# ========================= _infer_excel_column_roles_with_llm ============


class TestInferExcelColumnRolesWithLLM:
    def test_empty_records(self):
        service = _make_service()
        result = service._infer_excel_column_roles_with_llm([])
        assert isinstance(result, dict)

    def test_with_records_llm_failure(self):
        service = _make_service()
        records = [{"产品名称": "X", "单价": 100}]
        with patch("app.application.ai_chat_app_service.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            result = service._infer_excel_column_roles_with_llm(records)
        assert isinstance(result, dict)

    def test_uses_xcauto_credentials_when_ai_service_has_no_deepseek_key(self, monkeypatch):
        service = _make_service()
        service.ai_service = Mock(api_key="", api_url="", model="")
        monkeypatch.setenv("XCAUTO_API_KEY", "pat-xcauto")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        records = [{"客户": "星光贸易", "产品": "面漆", "型号": "5003", "报价": "12.5"}]
        raw = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"unit_name":"客户","product_name":"产品",'
                            '"model_number":"型号","unit_price":"报价"}'
                        )
                    }
                }
            ]
        }

        with patch("app.application.ai_chat_app_service.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = raw
            result = service._infer_excel_column_roles_with_llm(records)

        assert result == {
            "unit_name": "客户",
            "product_name": "产品",
            "model_number": "型号",
            "unit_price": "报价",
        }
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer pat-xcauto"
        assert post.call_args.kwargs["json"]["model"] == "xcauto-account"
        assert post.call_args.args[0] == "https://xiu-ci.com/v1/chat/completions"


# ========================= _extract_excel_import_records ==================


class TestExtractExcelImportRecords:
    def test_empty_excel_analysis(self):
        service = _make_service()
        records, err = service._extract_excel_import_records({})
        assert records == []
        assert err is None

    def test_no_records(self):
        service = _make_service()
        records, err = service._extract_excel_import_records({"preview_data": {"sample_rows": []}})
        assert records == []
        assert err is None

    def test_with_sample_rows_and_roles(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"客户": "公司A", "产品名称": "产品X", "型号": "5003A", "单价": 100},
                    {"客户": "公司A", "产品名称": "产品Y", "型号": "5004B", "单价": 200},
                ]
            }
        }
        with patch.object(
            service,
            "_infer_excel_column_roles",
            return_value=(
                {
                    "unit_name": "客户",
                    "product_name": "产品名称",
                    "model_number": "型号",
                    "unit_price": "单价",
                },
                0.9,
            ),
        ):
            with patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}):
                with patch.object(service, "_try_structured_reload_records", return_value=None):
                    records, err = service._extract_excel_import_records(
                        excel_analysis, user_message="导入数据库"
                    )
        assert err is None
        assert len(records) >= 1

    def test_ambiguous_price_columns(self):
        service = _make_service()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"调价前单价": 100, "调价后单价": 90, "产品名称": "X"},
                ]
            }
        }
        with patch.object(
            service,
            "_infer_excel_column_roles",
            return_value=(
                {
                    "unit_name": "",
                    "product_name": "产品名称",
                    "model_number": "",
                    "unit_price": "调价前单价",
                },
                0.9,
            ),
        ):
            with patch.object(service, "_infer_excel_column_roles_with_llm", return_value={}):
                with patch.object(service, "_try_structured_reload_records", return_value=None):
                    with patch(
                        "app.application.ai_chat_app_service.AIChatApplicationService._resolve_unit_price_column",
                        return_value=("", "ambiguous_price_columns"),
                    ):
                        records, err = service._extract_excel_import_records(
                            excel_analysis, user_message="导入"
                        )
        assert err == "ambiguous_price_columns"
        assert records == []


# ========================= _try_handle_dynamic_workflow - more branches ===


class TestTryHandleDynamicWorkflowExtended:
    def test_pro_import_with_db_file_success(self):
        service = _make_service()
        repo = InMemoryAgentRunRepository()
        ctx = {
            "file_analysis": {
                "suggested_use": "unit_products_db",
                "saved_name": "test.db",
                "unit_name": "公司A",
            },
            "file_context": {},
        }
        mock_import_svc = Mock()
        mock_import_svc.import_unit_products.return_value = {
            "success": True,
            "unit_name": "公司A",
            "created_unit": True,
            "imported": 5,
            "skipped_duplicates": 1,
        }
        with (
            patch(
                "app.application.get_unit_products_import_app_service",
                return_value=mock_import_svc,
            ),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
        assert result["success"] is True
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["data"]["run_id"] == result["run_id"]
        assert result["data"]["data"]["artifact_count"] == 1
        assert result["data"]["data"]["artifacts"][0]["artifact_type"] == "database_file"
        run = repo.get(result["run_id"])
        assert run is not None
        assert run.intent == "import_unit_products_db"
        assert run.status == "waiting_user"

        with (
            patch(
                "app.application.get_unit_products_import_app_service",
                return_value=mock_import_svc,
            ),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            completed = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert completed["success"] is True
        assert completed["run_id"] == result["run_id"]
        assert completed["data"]["data"]["tool_call_count"] == 1
        assert completed["data"]["data"]["cost_units_total"] == 2
        run = repo.get(result["run_id"])
        assert run is not None
        assert run.status == "completed"
        assert run.artifacts[0].artifact_type == "database_file"
        assert "tool.started" in [event.event_type for event in run.events]
        assert run.final_output["node_outputs"]["import_unit_products"]["imported"] == 5

    def test_pro_import_with_db_file_failure(self):
        service = _make_service()
        repo = InMemoryAgentRunRepository()
        ctx = {
            "file_analysis": {
                "suggested_use": "unit_products_db",
                "saved_name": "test.db",
                "unit_name": "公司A",
            },
            "file_context": {},
        }
        mock_import_svc = Mock()
        mock_import_svc.import_unit_products.return_value = {
            "success": False,
            "message": "导入出错",
        }
        with (
            patch(
                "app.application.get_unit_products_import_app_service",
                return_value=mock_import_svc,
            ),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
            failed = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert result["success"] is True
        assert result["run_id"]
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert failed["success"] is False
        assert failed["run_id"] == result["run_id"]
        run = repo.get(result["run_id"])
        assert run is not None
        assert run.intent == "import_unit_products_db"
        assert run.status == "failed"

    def test_pro_import_with_db_file_exception(self):
        service = _make_service()
        repo = InMemoryAgentRunRepository()
        ctx = {
            "file_analysis": {
                "suggested_use": "unit_products_db",
                "saved_name": "test.db",
                "unit_name": "公司A",
            },
            "file_context": {},
        }
        with (
            patch(
                "app.application.get_unit_products_import_app_service",
                side_effect=ImportError("no module"),
            ),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
            failed = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert result["success"] is True
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert failed["success"] is False
        assert failed["run_id"] == result["run_id"]

    def test_pro_excel_deterministic_import_no_records(self):
        service = _make_service()
        repo = InMemoryAgentRunRepository()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"label": "产品名称"}],
            }
        }
        with (
            patch.object(service, "_extract_excel_import_records", return_value=([], None)),
            patch(
                "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
        assert result is not None
        assert "未解析到" in result["response"] or "未识别" in result["response"]
        run = repo.get(result["run_id"])
        assert run is not None
        assert run.intent == "excel_import_to_db"
        assert run.status == "completed"
        assert run.metadata["runtime_context"]["workflow_trace_mode"] == "deterministic_shortcut"

    def test_pro_excel_deterministic_import_success(self):
        service = _make_service()
        repo = InMemoryAgentRunRepository()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"label": "产品名称"}],
            }
        }
        records = [
            {
                "unit_name": "公司A",
                "product_name": "产品X",
                "model_number": "5003A",
                "unit_price": 100.0,
            },
        ]
        mock_products_svc = Mock()
        mock_products_svc.get_products.return_value = {"success": True, "data": []}
        mock_products_svc.create_product.return_value = {"success": True}

        mock_customer_svc = Mock()
        mock_customer_svc.match_purchase_unit.return_value = None
        mock_customer_svc.create.return_value = {"success": True}

        with (
            patch.object(service, "_extract_excel_import_records", return_value=(records, None)),
            patch("app.bootstrap.get_products_service", return_value=mock_products_svc),
            patch("app.bootstrap.get_customer_app_service", return_value=mock_customer_svc),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
        assert result["success"] is True
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["data"]["run_id"] == result["run_id"]
        assert result["data"]["data"]["artifact_count"] == 1
        assert result["data"]["data"]["artifacts"][0]["artifact_type"] == "excel_records"
        run = repo.get(result["run_id"])
        assert run is not None
        assert run.intent == "excel_import_to_db"
        assert run.status == "waiting_user"

        with (
            patch("app.bootstrap.get_products_service", return_value=mock_products_svc),
            patch("app.bootstrap.get_customer_app_service", return_value=mock_customer_svc),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            completed = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert completed["success"] is True
        assert completed["run_id"] == result["run_id"]
        assert completed["data"]["data"]["tool_call_count"] == 1
        assert completed["data"]["data"]["cost_units_total"] == 2
        run = repo.get(result["run_id"])
        assert run is not None
        assert run.status == "completed"
        assert run.artifacts[0].preview["record_count"] == 1
        output = run.final_output["node_outputs"]["import_excel_records"]
        assert output["data"]["result"]["created_products"] == 1

    def test_pro_excel_deterministic_import_customer_unavailable(self):
        service = _make_service()
        repo = InMemoryAgentRunRepository()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"label": "产品名称"}],
            }
        }
        records = [
            {
                "unit_name": "公司A",
                "product_name": "产品X",
                "model_number": "5003A",
                "unit_price": 100.0,
            },
        ]
        mock_products_svc = Mock()
        mock_products_svc.get_products.return_value = {"success": True, "data": []}
        mock_products_svc.create_product.return_value = {"success": True}

        with (
            patch.object(service, "_extract_excel_import_records", return_value=(records, None)),
            patch("app.bootstrap.get_products_service", return_value=mock_products_svc),
            patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no module")),
            patch(
                "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
                return_value=repo,
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
            completed = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert result["success"] is True
        assert completed["success"] is True
        run = repo.get(result["run_id"])
        assert run is not None
        output = run.final_output["node_outputs"]["import_excel_records"]
        assert output["data"]["result"]["unit_service_available"] is False

    def test_pro_excel_deterministic_import_skip_deterministic(self):
        service = _make_service()
        ctx = {
            "excel_analysis": {"summary": "test", "fields": [{"label": "x"}]},
            "excel_import_skip_deterministic_shortcut": True,
        }
        with patch.object(service, "_extract_excel_import_records") as mock_extract:
            with patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ):
                result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
        mock_extract.assert_not_called()

    def test_pro_normal_profile_product_query(self):
        service = _make_service()
        ctx = {}
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "product_query"},
            ),
            patch(
                "app.application.normal_chat_dispatch.build_product_query_response_dict",
                return_value={"success": True, "response": "产品查询结果"},
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "查询产品", "pro", ctx, {})
        assert result is not None
        assert result["success"] is True

    def test_pro_normal_profile_shipment(self):
        service = _make_service()
        ctx = {}
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "shipment"},
            ),
            patch(
                "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
                return_value={"success": True, "response": "发货单预览"},
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "发货单", "pro", ctx, {})
        assert result is not None
        assert result["success"] is True

    def test_pro_normal_profile_customers_query(self):
        service = _make_service()
        ctx = {}
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "customers_query"},
            ),
            patch(
                "app.application.normal_chat_dispatch.build_customers_query_response_dict",
                return_value={"success": True, "response": "客户查询结果"},
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "查询客户", "pro", ctx, {})
        assert result is not None

    def test_pro_normal_profile_inventory_alert(self):
        service = _make_service()
        ctx = {}
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "inventory_alert"},
            ),
            patch(
                "app.application.normal_chat_dispatch.build_inventory_alert_response_dict",
                return_value={"success": True, "response": "库存预警"},
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "库存预警", "pro", ctx, {})
        assert result is not None

    def test_pro_normal_profile_label_print(self):
        service = _make_service()
        ctx = {}
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "label_print"},
            ),
            patch(
                "app.application.normal_chat_dispatch.build_label_print_response_dict",
                return_value={"success": True, "response": "标签打印"},
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "打印标签", "pro", ctx, {})
        assert result is not None

    def test_pro_normal_profile_no_match_returns_none(self):
        service = _make_service()
        ctx = {}
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "unknown"},
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "随便聊聊", "pro", ctx, {})
        assert result is None

    def test_pro_pending_workflow_confirm(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.plan_id = "p1"
        mock_plan.intent = "test"
        mock_plan.nodes = []
        mock_plan.todo_steps = []
        service._pending_workflows["u1"] = {
            "plan": mock_plan,
            "runtime_context": {"message": "test"},
            "approval_required": False,
            "approval_nodes": [],
        }
        mock_run_result = Mock()
        mock_run_result.success = True
        mock_run_result.node_results = []
        mock_run_result.message = ""
        with (
            patch.object(service.workflow_engine, "run", return_value=mock_run_result),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
        ):
            result = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert result is not None
        assert "u1" not in service._pending_workflows

    def test_pro_pending_workflow_cancel(self):
        service = _make_service()
        mock_plan = Mock()
        service._pending_workflows["u1"] = {
            "plan": mock_plan,
            "runtime_context": {},
            "approval_required": False,
            "approval_nodes": [],
        }
        result = service._try_handle_dynamic_workflow("u1", "取消", "pro", {}, {})
        assert result is not None
        assert "取消" in result["response"]
        assert "u1" not in service._pending_workflows

    def test_pro_pending_workflow_approval_required(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.plan_id = "p1"
        mock_node = Mock()
        mock_node.node_id = "n1"
        mock_plan.nodes = [mock_node]
        service._pending_workflows["u1"] = {
            "plan": mock_plan,
            "runtime_context": {},
            "approval_required": True,
            "approval_nodes": [{"node_id": "n1", "tool_id": "products", "action": "create"}],
        }
        with patch.object(service.approval_service, "create_approval_request"):
            result = service._try_handle_dynamic_workflow("u1", "确认", "pro", {}, {})
        assert result is not None
        assert "审批" in result["response"]


# ========================= _build_workflow_thinking_steps =================


class TestBuildWorkflowThinkingSteps:
    def test_basic(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.intent = "product_query"
        mock_plan.nodes = []
        mock_plan.metadata = {}
        result = service._build_workflow_thinking_steps(mock_plan, "low risk")
        assert "product_query" in result
        assert "low risk" in result

    def test_with_nodes(self):
        service = _make_service()
        mock_node = Mock()
        mock_node.node_id = "n1"
        mock_node.tool_id = "products"
        mock_node.action = "query"
        mock_node.risk = "low"
        mock_node.depends_on = []
        mock_plan = Mock()
        mock_plan.intent = "test"
        mock_plan.nodes = [mock_node]
        mock_plan.metadata = {}
        result = service._build_workflow_thinking_steps(mock_plan, "ok")
        assert "n1" in result
        assert "products.query" in result

    def test_with_user_memory_rag(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.intent = "test"
        mock_plan.nodes = []
        mock_plan.metadata = {"user_memory_rag_summary": "用户偏好：涂料类"}
        result = service._build_workflow_thinking_steps(mock_plan, "ok")
        assert "用户偏好" in result

    def test_with_tool_probe_outputs(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.intent = "test"
        mock_plan.nodes = []
        mock_plan.metadata = {
            "tool_probe_outputs": [
                {
                    "tool_id": "products",
                    "action": "query",
                    "success": True,
                    "message": "found",
                    "data_preview": "3 items",
                }
            ]
        }
        result = service._build_workflow_thinking_steps(mock_plan, "ok")
        assert "products.query" in result


# ========================= _workflow_products_float_query =================


class TestWorkflowProductsFloatQuery:
    def test_from_node_params(self):
        service = _make_service()
        mock_node = Mock()
        mock_node.tool_id = "products"
        mock_node.action = "query"
        mock_node.params = {"keyword": "5003A"}
        mock_plan = Mock()
        mock_plan.nodes = [mock_node]
        mock_result = Mock()
        mock_result.node_results = []
        q = service._workflow_products_float_query(mock_plan, mock_result, "hello")
        assert q == "5003A"

    def test_from_node_result(self):
        service = _make_service()
        mock_node = Mock()
        mock_node.tool_id = "products"
        mock_node.action = "query"
        mock_node.params = {}
        mock_plan = Mock()
        mock_plan.nodes = [mock_node]
        mock_item = Mock()
        mock_item.success = True
        mock_item.tool_id = "products"
        mock_item.action = "query"
        mock_item.output = {"data": [{"model_number": "5003A"}]}
        mock_result = Mock()
        mock_result.node_results = [mock_item]
        q = service._workflow_products_float_query(mock_plan, mock_result, "hello")
        assert q == "5003A"

    def test_fallback_to_message(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.nodes = []
        mock_result = Mock()
        mock_result.node_results = []
        q = service._workflow_products_float_query(mock_plan, mock_result, "查产品")
        assert q == "查产品"


# ========================= _format_workflow_run_response ==================


class TestFormatWorkflowRunResponse:
    def test_basic_success(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.plan_id = "p1"
        mock_plan.intent = "test"
        mock_plan.todo_steps = ["步骤1"]
        mock_item = Mock()
        mock_item.success = True
        mock_item.node_id = "n1"
        mock_item.tool_id = "other"
        mock_item.action = "exec"
        mock_item.error = None
        mock_result = Mock()
        mock_result.success = True
        mock_result.node_results = [mock_item]
        mock_result.message = ""
        result = service._format_workflow_run_response(mock_plan, mock_result, "thinking", "msg")
        assert result["success"] is True
        assert "步骤1" in result["response"]

    def test_failed_node(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.plan_id = "p1"
        mock_plan.intent = "test"
        mock_plan.todo_steps = None
        mock_item = Mock()
        mock_item.success = False
        mock_item.node_id = "n1"
        mock_item.tool_id = "products"
        mock_item.action = "create"
        mock_item.error = "db error"
        mock_result = Mock()
        mock_result.success = False
        mock_result.node_results = [mock_item]
        mock_result.message = "failed"
        result = service._format_workflow_run_response(mock_plan, mock_result, "", "msg")
        assert result["success"] is False
        assert "失败" in result["response"]

    def test_products_query_with_rows(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.plan_id = "p1"
        mock_plan.intent = "product_query"
        mock_plan.todo_steps = []
        mock_plan.nodes = []
        mock_item = Mock()
        mock_item.success = True
        mock_item.node_id = "n1"
        mock_item.tool_id = "products"
        mock_item.action = "query"
        mock_item.output = {
            "data": [{"model_number": "5003A", "name": "产品X", "price": 100.0, "unit": "个"}]
        }
        mock_item.error = None
        mock_result = Mock()
        mock_result.success = True
        mock_result.node_results = [mock_item]
        mock_result.message = ""
        with (
            patch("app.utils.ai_helpers.format_money", return_value="100.00"),
            patch("app.utils.ai_helpers.safe_float", return_value=100.0),
        ):
            result = service._format_workflow_run_response(mock_plan, mock_result, "", "5003A")
        assert result["success"] is True
        assert "autoAction" in result
        assert result["autoAction"]["type"] == "show_products_float"


# ========================= _dispatch_workflow_tool ========================


class TestDispatchWorkflowTool:
    def test_exception(self):
        service = _make_service()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=ImportError("no module"),
        ):
            result = service._dispatch_workflow_tool("products", "query", {})
        assert result["success"] is False


# ========================= _excel_analysis_payload_present - grid branch ==


class TestExcelAnalysisPayloadPresentGridBranch:
    def test_grid_preview_with_rows(self):
        assert (
            AIChatApplicationService._excel_analysis_payload_present(
                {
                    "excel_analysis": {
                        "preview_data": {"grid_preview": {"rows": [["h1", "h2"], ["d1", "d2"]]}}
                    }
                }
            )
            is True
        )

    def test_grid_preview_insufficient_rows(self):
        assert (
            AIChatApplicationService._excel_analysis_payload_present(
                {"excel_analysis": {"preview_data": {"grid_preview": {"rows": [["h1"]]}}}}
            )
            is False
        )


# ========================= _inject_excel_vector_context - more branches ==


class TestInjectExcelVectorContextExtended:
    def test_with_non_dict_context(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", "not a dict")
        assert result == {}

    def test_with_empty_index_id(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", {"excel_index_id": ""})
        assert "excel_vector_context" not in result

    def test_query_exception(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.side_effect = RuntimeError("fail")
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" not in result


# ========================= process_chat - more branches ===================


class TestProcessChatExtended:
    def test_generic_exception(self):
        async def raise_generic(*a, **kw):
            raise RuntimeError("unknown error")

        mock_ai = Mock()
        mock_ai.chat = raise_generic
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
            service.ai_service = mock_ai
            result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False

    def test_pro_source_with_message(self):
        async def mock_chat(*a, **kw):
            return {"success": True, "text": "结果", "action": "followup", "data": {}}

        mock_ai = Mock()
        mock_ai.chat = mock_chat
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
            service.ai_service = mock_ai
            with patch.object(service, "_try_handle_dynamic_workflow", return_value=None):
                result = service.process_chat("u1", "查询", source="pro", context={})
        assert result["success"] is True


# ========================= _resolve_unit_price_column - extended ==========


class TestResolveUnitPriceColumnExtended:
    def test_forced_override_not_in_keys(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["单价"], "", "", {"unit_price": "不存在的列"}
        )
        # forced but not found in keys → falls through to normal logic
        # "单价" is a generic price column, so it gets matched
        assert col == "单价"

    def test_tension_both_preferred(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "导入调价前和调价后数据", {}
        )
        assert err == "ambiguous_price_columns"

    def test_no_tension_before_only(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "数量"], "", "", {}
        )
        assert col == "调价前单价"
        assert err is None

    def test_no_tension_after_only(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价后单价", "数量"], "", "", {}
        )
        assert col == "调价后单价"
        assert err is None

    def test_multiple_generic_price_columns(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["单价A", "单价B"], "", "", {}
        )
        assert err == "ambiguous_price_columns"

    def test_generic_with_current(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["单价A", "单价B"], "单价A", "", {}
        )
        assert col == "单价A"

    def test_tension_default_before(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "普通消息", {}
        )
        assert col == "调价前单价"

    def test_implicit_prefer_before(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "使用调价前", {}
        )
        assert col == "调价前单价"

    def test_implicit_prefer_after(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "使用调价后", {}
        )
        assert col == "调价后单价"


# ========================= _handle_tool_call - extended ===================


class TestHandleToolCallExtended:
    def test_no_tool_key(self):
        service = _make_service()
        response_data = {
            "success": True,
            "message": "处理完成",
            "data": {"text": "", "action": "", "data": {}},
        }
        ai_result = {"text": "处理中", "action": "tool_call", "data": {"params": {}}}
        result_data = {"params": {}}
        result = service._handle_tool_call(response_data, ai_result, result_data, None, "")
        assert result["success"] is True


# ========================= _execute_normal_mode_tools ====================


class TestExecuteNormalModeTools:
    def test_unknown_tool(self):
        service = _make_service()
        response_data = {"success": True, "data": {}}
        result = service._execute_normal_mode_tools(
            response_data, "unknown_tool", {}, {"text": "test"}, {"tool_key": "unknown_tool"}
        )
        assert isinstance(result, dict)


# ========================= _execute_customers_query - extended ============


class TestExecuteCustomersQueryExtended:
    def test_service_failure(self):
        service = _make_service()
        response_data = {"success": True, "data": {}}
        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = service._execute_customers_query(response_data)
        assert "失败" in result["response"]


# ========================= _build_response - extended =====================


class TestBuildResponseExtended:
    def test_followup_action(self):
        service = _make_service()
        result = service._build_response(
            {"text": "请提供更多信息", "action": "followup", "data": {"key": "val"}}, None
        )
        assert result["followup"] == {"key": "val"}

    def test_auto_action_empty_data(self):
        service = _make_service()
        result = service._build_response(
            {"text": "处理中", "action": "auto_action", "data": None}, None
        )
        assert result["success"] is True

    def test_no_action(self):
        service = _make_service()
        result = service._build_response({"text": "你好", "action": "", "data": {}}, None)
        assert result["success"] is True
        assert result["response"] == "你好"
