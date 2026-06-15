"""Tests for app.application.ai_chat_app_service — coverage ramp."""

import math
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)


# ---------------------------------------------------------------------------
# Helper: create service with all heavy deps mocked
# ---------------------------------------------------------------------------
def _make_service():
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


# ========================= _skip_pro_excel_deterministic_import =============


class TestSkipProExcelDeterministicImport:
    def test_none_context_returns_false(self):
        assert _skip_pro_excel_deterministic_import(None) is False

    def test_use_deterministic_shortcut_true_returns_false(self):
        assert (
            _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": True})
            is False
        )

    def test_skip_deterministic_shortcut_true(self):
        assert (
            _skip_pro_excel_deterministic_import({"excel_import_skip_deterministic_shortcut": True})
            is True
        )

    def test_ai_decides_true(self):
        assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True

    def test_env_disable_shortcut(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "1")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_ai_decides(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "true")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_default_returns_false(self):
        assert _skip_pro_excel_deterministic_import({}) is False

    def test_use_deterministic_overrides_skip(self):
        ctx = {
            "excel_import_use_deterministic_shortcut": True,
            "excel_import_skip_deterministic_shortcut": True,
        }
        assert _skip_pro_excel_deterministic_import(ctx) is False


# ========================= _is_pro_source ================================


class TestIsProSource:
    def test_pro(self):
        assert AIChatApplicationService._is_pro_source("pro") is True

    def test_pro_mode(self):
        assert AIChatApplicationService._is_pro_source("pro_mode") is True

    def test_promode(self):
        assert AIChatApplicationService._is_pro_source("promode") is True

    def test_professional(self):
        assert AIChatApplicationService._is_pro_source("professional") is True

    def test_xcagi_pro(self):
        assert AIChatApplicationService._is_pro_source("xcagi_pro") is True

    def test_pro_dash_mode(self):
        assert AIChatApplicationService._is_pro_source("pro-mode") is True

    def test_normal(self):
        assert AIChatApplicationService._is_pro_source("normal") is False

    def test_none(self):
        assert AIChatApplicationService._is_pro_source(None) is False

    def test_empty(self):
        assert AIChatApplicationService._is_pro_source("") is False


# ========================= _merge_tool_runtime_context ===================


class TestMergeToolRuntimeContext:
    def test_basic_merge(self):
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hello")
        assert result["user_id"] == "u1"
        assert result["message"] == "hello"

    def test_context_ui_surface(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hi", {"ui_surface": "normal", "intent_channel": "pro"}
        )
        assert result["ui_surface"] == "normal"
        assert result["intent_channel"] == "pro"

    def test_context_excel_analysis(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hi", {"excel_analysis": {"file_path": "/tmp/a.xlsx"}}
        )
        assert result["excel_analysis"] == {"file_path": "/tmp/a.xlsx"}

    def test_none_values_skipped(self):
        result = AIChatApplicationService._merge_tool_runtime_context(
            "u1", "hi", {"ui_surface": None}
        )
        assert "ui_surface" not in result

    def test_none_context(self):
        result = AIChatApplicationService._merge_tool_runtime_context("u1", "hi", None)
        assert result == {"user_id": "u1", "message": "hi"}


# ========================= _build_fallback_response ======================


class TestBuildFallbackResponse:
    def test_greeting_keywords(self):
        for kw in ("你好", "您好", "hi", "hello", "嗨"):
            resp = AIChatApplicationService._build_fallback_response(kw, "test error")
            assert "XCAGI" in resp["response"] or "智能助手" in resp["response"]

    def test_default_fallback(self):
        resp = AIChatApplicationService._build_fallback_response("查询产品", "timeout")
        assert "timeout" in resp["response"]
        assert resp["success"] is False
        assert resp["data"]["action"] == "error_fallback"

    def test_empty_message(self):
        resp = AIChatApplicationService._build_fallback_response("", "err")
        assert resp["success"] is False


# ========================= _is_number_text ===============================


class TestIsNumberText:
    def test_integer(self):
        assert AIChatApplicationService._is_number_text("123") is True

    def test_float(self):
        assert AIChatApplicationService._is_number_text("12.5") is True

    def test_comma_number(self):
        assert AIChatApplicationService._is_number_text("1,000") is True

    def test_text(self):
        assert AIChatApplicationService._is_number_text("abc") is False

    def test_empty(self):
        assert AIChatApplicationService._is_number_text("") is False

    def test_none(self):
        assert AIChatApplicationService._is_number_text(None) is False


# ========================= _sanitize_import_scalar =======================


class TestSanitizeImportScalar:
    def test_none(self):
        assert AIChatApplicationService._sanitize_import_scalar(None) is None

    def test_nan_float(self):
        assert AIChatApplicationService._sanitize_import_scalar(float("nan")) is None

    def test_nan_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("nan") is None

    def test_none_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("none") is None

    def test_normal_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("hello") == "hello"

    def test_integer(self):
        assert AIChatApplicationService._sanitize_import_scalar(42) == 42

    def test_nat_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("NaT") is None

    def test_null_string(self):
        assert AIChatApplicationService._sanitize_import_scalar("null") is None


# ========================= _excel_cell_looks_like_product_measure_unit ====


class TestExcelCellLooksLikeMeasureUnit:
    def test_件(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("件") is True

    def test_pcs(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("pcs") is True

    def test_qty_measure(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("10件") is True

    def test_company_name(self):
        assert (
            AIChatApplicationService._excel_cell_looks_like_product_measure_unit("某某有限公司")
            is False
        )

    def test_empty(self):
        assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("") is False


# ========================= _model_like_score ==============================


class TestModelLikeScore:
    def test_alphanumeric(self):
        assert AIChatApplicationService._model_like_score("5003A") == 1.0

    def test_digits_only_short(self):
        assert AIChatApplicationService._model_like_score("5003") == 0.6

    def test_text_only(self):
        assert AIChatApplicationService._model_like_score("产品名称") == 0.0

    def test_too_long(self):
        assert AIChatApplicationService._model_like_score("A" * 30) == 0.0

    def test_empty(self):
        assert AIChatApplicationService._model_like_score("") == 0.0


# ========================= _row_values_look_like_table_headers ===========


class TestRowValuesLookLikeTableHeaders:
    def test_header_like(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(
                ["产品名称", "单价", "型号"]
            )
            is True
        )

    def test_data_like(self):
        assert (
            AIChatApplicationService._row_values_look_like_table_headers(["100", "200", "300"])
            is False
        )

    def test_too_few(self):
        assert AIChatApplicationService._row_values_look_like_table_headers(["产品"]) is False


# ========================= _excel_analysis_payload_present ===============


class TestExcelAnalysisPayloadPresent:
    def test_none_context(self):
        assert AIChatApplicationService._excel_analysis_payload_present(None) is False

    def test_with_summary(self):
        assert (
            AIChatApplicationService._excel_analysis_payload_present(
                {"excel_analysis": {"summary": "test"}}
            )
            is True
        )

    def test_with_fields(self):
        assert (
            AIChatApplicationService._excel_analysis_payload_present(
                {"excel_analysis": {"fields": [{"label": "x"}]}}
            )
            is True
        )

    def test_with_sample_rows(self):
        assert (
            AIChatApplicationService._excel_analysis_payload_present(
                {"excel_analysis": {"preview_data": {"sample_rows": [{}]}}}
            )
            is True
        )

    def test_empty(self):
        assert (
            AIChatApplicationService._excel_analysis_payload_present({"excel_analysis": {}})
            is False
        )


# ========================= _looks_like_short_excel_import_command =========


class TestLooksLikeShortExcelImportCommand:
    def test_exact_match(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("入库") is True

    def test_containing_keyword(self):
        assert (
            AIChatApplicationService._looks_like_short_excel_import_command("请加入数据库") is True
        )

    def test_normal_message(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("查询产品") is False

    def test_empty(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("") is False

    def test_too_long(self):
        assert AIChatApplicationService._looks_like_short_excel_import_command("a" * 50) is False


# ========================= _resolve_excel_path_for_import ================


class TestResolveExcelPathForImport:
    def test_from_excel_analysis(self):
        result = AIChatApplicationService._resolve_excel_path_for_import(
            {"file_path": "/tmp/a.xlsx"}, {}
        )
        assert result == "/tmp/a.xlsx"

    def test_from_preview_data(self):
        result = AIChatApplicationService._resolve_excel_path_for_import(
            {}, {"file_path": "/tmp/b.xlsx"}
        )
        assert result == "/tmp/b.xlsx"

    def test_excel_analysis_priority(self):
        result = AIChatApplicationService._resolve_excel_path_for_import(
            {"file_path": "/tmp/a.xlsx"}, {"file_path": "/tmp/b.xlsx"}
        )
        assert result == "/tmp/a.xlsx"

    def test_empty(self):
        result = AIChatApplicationService._resolve_excel_path_for_import({}, {})
        assert result == ""


# ========================= _resolve_force_header_row_1based ===============


class TestResolveForceHeaderRow1based:
    def test_from_grid_preview(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 3}}
        )
        assert result == 3

    def test_from_tables(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"tables": [{"header_row": 2}]}
        )
        assert result == 2

    def test_from_excel_sheets(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"tables": [{"header_row": 4}]}]}, {}
        )
        assert result == 4

    def test_none_when_absent(self):
        result = AIChatApplicationService._resolve_force_header_row_1based({}, {})
        assert result is None

    def test_invalid_value(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": "abc"}}
        )
        assert result is None

    def test_zero_rejected(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 0}}
        )
        assert result is None


# ========================= _resolve_sheet_name_for_reimport ==============


class TestResolveSheetNameForReimport:
    def test_from_request_context_selected_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"excel_analysis_selected_sheet": {"sheet_name": "Sheet2"}}
        )
        assert result == "Sheet2"

    def test_from_request_context_preferred(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {}, {"preferred_sheet_name": "Sheet3"}
        )
        assert result == "Sheet3"

    def test_from_preview_data(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {}, {"sheet_name": "Sheet1"}, None
        )
        assert result == "Sheet1"

    def test_from_excel_analysis_sheets(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {"sheets": [{"sheet_name": "Data"}]}, {}, None
        )
        assert result == "Data"

    def test_none_when_absent(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}, None)
        assert result is None


# ========================= _guess_default_purchase_unit ===================


class TestGuessDefaultPurchaseUnit:
    def test_company_name_in_filename(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "某某有限公司产品报价表.xlsx"}
        )
        assert "某某有限公司" in result

    def test_file_path_fallback(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_path": "/tmp/测试公司报价单.xlsx"}
        )
        assert "测试公司" in result

    def test_empty(self):
        result = AIChatApplicationService._guess_default_purchase_unit({})
        assert result == ""

    def test_short_stem(self):
        result = AIChatApplicationService._guess_default_purchase_unit({"file_name": "a.xlsx"})
        assert result == ""


# ========================= _price_column_buckets ==========================


class TestPriceColumnBuckets:
    def test_before_and_after(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["调价前含税单价", "调价后含税单价", "数量"]
        )
        assert "调价前含税单价" in before
        assert "调价后含税单价" in after

    def test_generic_price(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(["单价", "数量"])
        assert "单价" in generic

    def test_no_price(self):
        before, after, generic = AIChatApplicationService._price_column_buckets(
            ["产品名称", "数量"]
        )
        assert before == [] and after == [] and generic == []


# ========================= _resolve_unit_price_column ====================


class TestResolveUnitPriceColumn:
    def test_forced_override(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["单价", "调价前单价"], "", "", {"unit_price": "调价前单价"}
        )
        assert col == "调价前单价"
        assert err is None

    def test_ambiguous(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "导入调价前和调价后数据", {}
        )
        assert err == "ambiguous_price_columns"

    def test_prefer_before(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "导入调价前数据", {}
        )
        assert col == "调价前单价"

    def test_prefer_after(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "导入调价后数据", {}
        )
        assert col == "调价后单价"

    def test_single_generic(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(["单价"], "", "", {})
        assert col == "单价"

    def test_empty_keys(self):
        col, err = AIChatApplicationService._resolve_unit_price_column([], "", "", {})
        assert col == ""

    def test_current_in_keys(self):
        col, err = AIChatApplicationService._resolve_unit_price_column(["单价"], "单价", "", {})
        assert col == "单价"


# ========================= _merge_user_intent_for_price_resolution =======


class TestMergeUserIntentForPriceResolution:
    def test_basic(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "导入调价前", None
        )
        assert "导入调价前" in result

    def test_with_recent_messages(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "确认", {"recent_messages": [{"role": "user", "content": "导入调价前数据"}]}
        )
        assert "导入调价前数据" in result

    def test_html_stripped(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "确认", {"recent_messages": [{"role": "user", "content": "导入<br/>调价前"}]}
        )
        assert "<br" not in result

    def test_truncation(self):
        long_msg = "x" * 10000
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(long_msg, None)
        assert len(result) <= 8000


# ========================= _infer_excel_column_roles =====================


class TestInferExcelColumnRoles:
    def test_basic_inference(self):
        service = _make_service()
        records = [
            {"客户": "公司A", "产品名称": "产品X", "型号": "5003A", "单价": 100},
            {"客户": "公司B", "产品名称": "产品Y", "型号": "5004B", "单价": 200},
        ]
        roles, conf = service._infer_excel_column_roles(records)
        assert isinstance(roles, dict)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_empty_records(self):
        service = _make_service()
        roles, conf = service._infer_excel_column_roles([])
        assert roles == {}
        assert conf == 0.0


# ========================= _fallback_excel_product_name_column ===========


class TestFallbackExcelProductNameColumn:
    def test_selects_text_column(self):
        service = _make_service()
        records = [
            {"序号": 1, "名称": "产品A", "数量": 10},
            {"序号": 2, "名称": "产品B", "数量": 20},
        ]
        result = service._fallback_excel_product_name_column(records, {"序号", "数量"})
        assert result == "名称"

    def test_empty_records(self):
        service = _make_service()
        result = service._fallback_excel_product_name_column([], set())
        assert result == ""


# ========================= _fallback_excel_model_number_column ===========


class TestFallbackExcelModelNumberColumn:
    def test_selects_model_like(self):
        service = _make_service()
        records = [
            {"名称": "产品A", "型号": "5003A"},
            {"名称": "产品B", "型号": "5004B"},
        ]
        result = service._fallback_excel_model_number_column(records, {"名称"})
        assert result == "型号"

    def test_empty_records(self):
        service = _make_service()
        result = service._fallback_excel_model_number_column([], set())
        assert result == ""


# ========================= _packaging_or_measure_ratio ===================


class TestPackagingOrMeasureRatio:
    def test_all_measures(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["件", "箱", "套"])
        assert ratio == 1.0

    def test_mixed(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["件", "产品A"])
        assert 0.0 < ratio < 1.0

    def test_empty(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio([])
        assert ratio == 0.0


# ========================= _header_hint_column_roles =====================


class TestHeaderHintColumnRoles:
    def test_returns_dict(self):
        result = AIChatApplicationService._header_hint_column_roles(["产品名称", "单价"])
        assert isinstance(result, dict)


# ========================= _inject_excel_vector_context ==================


class TestInjectExcelVectorContext:
    def test_no_index_id(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", {"other_key": "val"})
        assert result == {"other_key": "val"}

    def test_non_dict_context(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", None)
        assert result == {}

    def test_with_index_id_success(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": [{"text": "hit1"}]}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" in result

    def test_with_index_id_failure(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": False}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" not in result


# ========================= _handle_confirmation_flow =====================


class TestHandleConfirmationFlow:
    def test_no_file_context(self):
        service = _make_service()
        service.ai_service = Mock()
        service._handle_confirmation_flow("u1", "是", None)
        service.ai_service.set_pending_confirmation.assert_not_called()

    def test_non_confirm_message(self):
        service = _make_service()
        service.ai_service = Mock()
        service._handle_confirmation_flow("u1", "查询产品", {"saved_name": "f.xlsx"})
        service.ai_service.set_pending_confirmation.assert_not_called()

    def test_confirm_with_valid_context(self):
        service = _make_service()
        service.ai_service = Mock()
        ctx = {
            "saved_name": "test.xlsx",
            "unit_name_guess": "测试公司",
            "suggested_use": "unit_products_db",
        }
        service._handle_confirmation_flow("u1", "确认", ctx)
        service.ai_service.set_pending_confirmation.assert_called_once()

    def test_confirm_without_unit_name(self):
        service = _make_service()
        service.ai_service = Mock()
        ctx = {
            "saved_name": "test.xlsx",
            "suggested_use": "unit_products_db",
        }
        service._handle_confirmation_flow("u1", "是", ctx)
        service.ai_service.set_pending_confirmation.assert_not_called()


# ========================= _build_response ===============================


class TestBuildResponse:
    def test_simple_followup(self):
        service = _make_service()
        result = service._build_response(
            {"text": "hi", "action": "followup", "data": {"k": "v"}}, None
        )
        assert result["success"] is True
        assert result["followup"] == {"k": "v"}

    def test_auto_action(self):
        service = _make_service()
        result = service._build_response(
            {"text": "doing", "action": "auto_action", "data": {"type": "x"}}, None
        )
        assert result["autoAction"] == {"type": "x"}

    def test_tool_call_no_tool_key(self):
        service = _make_service()
        result = service._build_response(
            {"text": "processing", "action": "tool_call", "data": {"params": {}}}, None
        )
        assert result["success"] is True

    def test_tool_call_pro_mode(self):
        service = _make_service()
        ai_result = {
            "text": "查询中",
            "action": "tool_call",
            "data": {"tool_key": "products", "slots": {"keyword": "test"}, "params": {}},
        }
        with patch("app.application.ai_chat_app_service.get_ai_conversation_service"):
            with patch("app.bootstrap.get_products_service") as mock_ps:
                mock_svc = Mock()
                mock_svc.get_products.return_value = {"success": True, "data": []}
                mock_ps.return_value = mock_svc
                with patch(
                    "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                    return_value=None,
                ):
                    result = service._build_response(ai_result, "pro", "查询产品")
        assert result["success"] is True


# ========================= _execute_customers_intent =====================


class TestExecuteCustomersIntent:
    def test_add_intent_no_unit_name(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        result = service._execute_customers_intent(resp, {}, {}, "添加单位")
        assert "哪个单位" in result["response"]

    def test_query_intent(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = Mock()
            mock_svc.get_all.return_value = {"success": True, "data": []}
            mock_get.return_value = mock_svc
            result = service._execute_customers_intent(resp, {}, {}, "查询客户列表")
        assert result["success"] is True

    def test_ambiguous_intent(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        result = service._execute_customers_intent(resp, {}, {}, "客户")
        assert "customers_followup" in str(result["data"]["data"])


# ========================= _build_order_text_from_products ==============


class TestBuildOrderTextFromProducts:
    def test_basic(self):
        service = _make_service()
        products = [{"model": "5003", "quantity_tins": 10, "spec": 25}]
        result = service._build_order_text_from_products("公司A", products)
        assert "公司A" in result
        assert "10桶5003规格25" in result

    def test_empty_products(self):
        service = _make_service()
        assert service._build_order_text_from_products("公司A", []) == ""

    def test_empty_unit(self):
        service = _make_service()
        assert service._build_order_text_from_products("", [{"model": "X"}]) == ""


# ========================= _try_merge_split_model ========================


class TestTryMergeSplitModel:
    def test_merge_success(self):
        service = _make_service()
        result = service._try_merge_split_model("10桶5003A规格25", {"quantity_tins": 10})
        assert "5003A" in result

    def test_no_match(self):
        service = _make_service()
        result = service._try_merge_split_model("无型号信息", {"quantity_tins": 1})
        assert result == ""


# ========================= _normal_slot_dispatch_chat_overlay ============


class TestNormalSlotDispatchChatOverlay:
    def test_empty_result(self):
        mock_result = Mock()
        mock_result.node_results = []
        assert AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result) == {}

    def test_with_normal_slot_dispatch(self):
        mock_result = Mock()
        mock_item = Mock()
        mock_item.success = True
        mock_item.tool_id = "normal_slot_dispatch"
        mock_item.output = {"success": True, "response": "test", "autoAction": {"type": "x"}}
        mock_result.node_results = [mock_item]
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result)
        assert result["response"] == "test"


# ========================= process_chat ==================================


class TestProcessChat:
    def test_empty_message(self):
        service = _make_service()
        result = service.process_chat("u1", "")
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_connection_error(self):
        async def raise_conn(*a, **kw):
            raise ConnectionError("refused")

        mock_ai = Mock()
        mock_ai.chat = raise_conn
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
            service.ai_service = mock_ai
            result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False
        assert "连接失败" in result["message"]

    def test_timeout_error(self):
        async def raise_timeout(*a, **kw):
            raise TimeoutError("timed out")

        mock_ai = Mock()
        mock_ai.chat = raise_timeout
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
            service.ai_service = mock_ai
            result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False
        assert "超时" in result["message"]

    def test_api_key_error(self):
        async def raise_key(*a, **kw):
            raise RuntimeError("invalid api_key")

        mock_ai = Mock()
        mock_ai.chat = raise_key
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
            service.ai_service = mock_ai
            result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False
        assert "API Key" in result["message"]


# ========================= _try_handle_dynamic_workflow ==================


class TestTryHandleDynamicWorkflow:
    def test_non_pro_returns_none(self):
        service = _make_service()
        result = service._try_handle_dynamic_workflow("u1", "hello", None, {}, {})
        assert result is None

    def test_pro_empty_message_returns_none(self):
        service = _make_service()
        result = service._try_handle_dynamic_workflow("u1", "", "pro", {}, {})
        assert result is None

    def test_pro_short_import_no_context(self):
        service = _make_service()
        result = service._try_handle_dynamic_workflow("u1", "入库", "pro", {}, {})
        assert result is not None
        assert result["success"] is True
        assert "Excel 分析上下文" in result["response"]

    def test_pro_import_with_file_context_no_saved_name(self):
        service = _make_service()
        ctx = {
            "file_analysis": {"suggested_use": "unit_products_db"},
            "file_context": {},
        }
        result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
        assert result is not None
        assert "缺少源文件" in result["response"]

    def test_pro_import_with_file_context_no_unit_name(self):
        service = _make_service()
        ctx = {
            "file_analysis": {"suggested_use": "unit_products_db", "saved_name": "test.db"},
            "file_context": {},
        }
        result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
        assert result is not None
        assert "客户名称" in result["response"]

    def test_pro_excel_import_ambiguous_price(self):
        service = _make_service()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"label": "调价前单价"}, {"label": "调价后单价"}],
                "preview_data": {
                    "sample_rows": [
                        {"客户": "A", "产品名称": "X", "调价前单价": 100, "调价后单价": 90}
                    ]
                },
            }
        }
        with patch.object(
            service, "_extract_excel_import_records", return_value=([], "ambiguous_price_columns")
        ):
            result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
        assert result is not None
        assert "歧义" in result["response"] or "调价" in result["response"]
