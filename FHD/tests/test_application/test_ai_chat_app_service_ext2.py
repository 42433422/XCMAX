"""Tests for app.application.ai_chat_app_service — coverage ramp for uncovered branches."""

from __future__ import annotations

import math
import uuid
from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.run_repository import (
    InMemoryAgentRunRepository,
    SQLAlchemyAgentRunRepository,
)
from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.domain.autonomy.risk_types import RiskDecision
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _make_service():
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan.return_value = PlanGraph(
            plan_id="test-plan",
            intent="test",
        )
        service.risk_gate.evaluate.return_value = RiskDecision(
            requires_confirmation=False,
            reason="",
            allowed=True,
        )
        service.approval_service.get_approval_required_nodes.return_value = []
        return service


@pytest.fixture
def dataset_store(tmp_path, monkeypatch):
    from app.application.dataset_rag_app_service import reset_dataset_rag_app_service_for_tests

    store = tmp_path / "dataset_store.json"
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(store))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "vectors.sqlite3"))
    monkeypatch.setenv("XCAGI_KNOWLEDGE_DEFAULT_DATASET", "confirmed-import-evidence")
    reset_dataset_rag_app_service_for_tests()
    yield store
    reset_dataset_rag_app_service_for_tests()


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


class TestInferExcelColumnRolesWithLLM:
    def test_empty_records(self):
        service = _make_service()
        result = service._infer_excel_column_roles_with_llm([])
        assert isinstance(result, dict)

    def test_with_records_llm_failure(self):
        service = _make_service()
        service.workflow_planner.complete_messages.return_value = None
        records = [{"产品名称": "X", "单价": 100}]
        result = service._infer_excel_column_roles_with_llm(records)
        assert isinstance(result, dict)

    def test_uses_the_configured_planner_provider(self):
        service = _make_service()
        service.workflow_planner.complete_messages.return_value = {
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
        records = [{"客户": "星光贸易", "产品": "面漆", "型号": "5003", "报价": "12.5"}]
        result = service._infer_excel_column_roles_with_llm(records)

        assert result == {
            "unit_name": "客户",
            "product_name": "产品",
            "model_number": "型号",
            "unit_price": "报价",
        }
        service.workflow_planner.complete_messages.assert_called_once()


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


class TestBuildWorkflowThinkingSteps:
    def test_basic(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.intent = "product_query"
        mock_plan.nodes = []
        mock_plan.metadata = {}
        result = service._build_workflow_thinking_steps(mock_plan, "low risk")
        assert "查询产品资料" in result
        assert "product_query" not in result
        assert "low risk" not in result

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
        assert "查询产品资料" in result
        assert "n1" not in result
        assert "products.query" not in result

    def test_with_user_memory_rag(self):
        service = _make_service()
        mock_plan = Mock()
        mock_plan.intent = "test"
        mock_plan.nodes = []
        mock_plan.metadata = {"user_memory_rag_summary": "用户偏好：涂料类"}
        result = service._build_workflow_thinking_steps(mock_plan, "ok")
        assert "用户偏好" in result


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
