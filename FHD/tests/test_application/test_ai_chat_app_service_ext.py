"""Tests for app.application.ai_chat_app_service — coverage ramp."""

from unittest.mock import Mock, patch

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
        # Numeric column -> unit_price; alphanumeric -> model_number.
        assert roles["unit_price"] == "单价"
        assert roles["model_number"] == "型号"
        assert roles["unit_name"] == "客户"
        # 4 roles share only 3 distinct semantic columns here -> one role drops out.
        assert roles["product_name"] == ""
        assert set(roles.keys()) == {
            "unit_price",
            "model_number",
            "unit_name",
            "product_name",
        }
        # Confidence is the mean of per-role confidences; one empty role caps it below 1.
        assert 0.0 < conf < 1.0

    def test_no_role_collision_when_distinct_columns(self):
        service = _make_service()
        records = [
            {"客户": "长期合作的公司甲", "品名": "高级清漆涂料", "货号": "5003A", "报价": 100},
            {"客户": "长期合作的公司甲", "品名": "环保水性涂料", "货号": "7782B", "报价": 250},
            {"客户": "另一家供货商乙", "品名": "工业级稀释剂", "货号": "9001C", "报价": 88},
        ]
        roles, conf = service._infer_excel_column_roles(records)
        # All four roles resolve to distinct, sensible columns.
        assert roles["unit_price"] == "报价"
        assert roles["model_number"] == "货号"
        assert roles["product_name"] == "品名"
        assert roles["unit_name"] == "客户"
        # No column is reused across roles.
        assigned = [v for v in roles.values() if v]
        assert len(assigned) == len(set(assigned)) == 4

    def test_empty_records(self):
        service = _make_service()
        roles, conf = service._infer_excel_column_roles([])
        assert roles == {}
        assert conf == 0.0

    def test_records_with_only_blank_keys(self):
        service = _make_service()
        roles, conf = service._infer_excel_column_roles([{"  ": "x", "": "y"}])
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
        # 1 of 2 values is a measure unit -> exactly 0.5.
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["件", "产品A"])
        assert ratio == 0.5

    def test_quantity_measure_pattern_counts(self):
        # "5箱"/"3桶" match the qty+measure regex; the company name does not.
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["5箱", "3桶", "某某有限公司"])
        assert ratio == pytest.approx(2.0 / 3.0)

    def test_blank_values_ignored_in_denominator(self):
        # Empty/whitespace entries are dropped before computing the ratio.
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["件", "", "  ", None])
        assert ratio == 1.0

    def test_empty(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio([])
        assert ratio == 0.0

    def test_all_blank_returns_zero(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["", "   ", None])
        assert ratio == 0.0


# ========================= _header_hint_column_roles =====================


class TestHeaderHintColumnRoles:
    def test_maps_known_header_synonyms_to_roles(self):
        result = AIChatApplicationService._header_hint_column_roles(["产品名称", "单价"])
        # Always returns the full 4-role schema.
        assert set(result.keys()) == {
            "unit_name",
            "product_name",
            "model_number",
            "unit_price",
        }
        assert result["product_name"] == "产品名称"
        assert result["unit_price"] == "单价"
        # Roles with no matching header stay empty (not absent).
        assert result["unit_name"] == ""
        assert result["model_number"] == ""

    def test_full_header_row_maps_all_four_roles(self):
        result = AIChatApplicationService._header_hint_column_roles(
            ["客户名称", "产品名称", "型号", "单价"]
        )
        assert result == {
            "unit_name": "客户名称",
            "product_name": "产品名称",
            "model_number": "型号",
            "unit_price": "单价",
        }

    def test_normalizes_punctuation_in_header(self):
        # Spaces/colons/slashes are stripped before matching the synonym table.
        result = AIChatApplicationService._header_hint_column_roles(["客 户 名 称", "单 价："])
        assert result["unit_name"] == "客 户 名 称"
        assert result["unit_price"] == "单 价："

    def test_unrelated_headers_yield_empty_roles(self):
        result = AIChatApplicationService._header_hint_column_roles(["备注", "下单日期"])
        assert result == {
            "unit_name": "",
            "product_name": "",
            "model_number": "",
            "unit_price": "",
        }


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
            result = service._inject_excel_vector_context(
                "找清漆", {"excel_index_id": "idx1", "excel_top_k": 7}
            )
        # The search service is queried with the message and the requested top_k.
        mock_svc.query.assert_called_once_with(index_id="idx1", query_text="找清漆", top_k=7)
        # On success the enriched context carries the full vector payload.
        assert result["excel_vector_context"] == {
            "index_id": "idx1",
            "query": "找清漆",
            "hits": [{"text": "hit1"}],
        }
        # Original keys are preserved (returned a copy, not the same dict).
        assert result["excel_index_id"] == "idx1"

    def test_top_k_defaults_to_five_when_invalid(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            service._inject_excel_vector_context(
                "hi", {"excel_vector_index_id": "idx2", "excel_top_k": "not-a-number"}
            )
        # Non-int top_k falls back to 5; the alternate id key is also honoured.
        mock_svc.query.assert_called_once_with(index_id="idx2", query_text="hi", top_k=5)

    def test_with_index_id_failure(self):
        service = _make_service()
        original = {"excel_index_id": "idx1", "keep": "me"}
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": False}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", original)
        # A failed query returns the original context unchanged (no enrichment).
        assert "excel_vector_context" not in result
        assert result is original

    def test_query_exception_returns_context_unchanged(self):
        service = _make_service()
        original = {"excel_index_id": "idx1"}
        mock_svc = Mock()
        mock_svc.query.side_effect = RuntimeError("vector backend down")
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", original)
        # Recoverable errors are swallowed; caller still gets the untouched context.
        assert result is original
        assert "excel_vector_context" not in result


# ========================= _handle_confirmation_flow =====================


class TestHandleConfirmationFlow:
    def test_no_file_context(self):
        service = _make_service()
        service.ai_service = Mock()
        # No file context -> early return, nothing pended.
        assert service._handle_confirmation_flow("u1", "是", None) is None
        service.ai_service.set_pending_confirmation.assert_not_called()

    def test_non_confirm_message(self):
        service = _make_service()
        service.ai_service = Mock()
        # Message is not one of the confirmation keywords -> no pending write.
        service._handle_confirmation_flow("u1", "查询产品", {"saved_name": "f.xlsx"})
        service.ai_service.set_pending_confirmation.assert_not_called()

    @pytest.mark.parametrize("confirm_word", ["是", "好的", "确认", "yes", "ok", "好"])
    def test_confirm_with_valid_context_pends_exact_payload(self, confirm_word):
        service = _make_service()
        service.ai_service = Mock()
        ctx = {
            "saved_name": "test.xlsx",
            "unit_name_guess": "测试公司",
            "suggested_use": "unit_products_db",
        }
        service._handle_confirmation_flow("u1", confirm_word, ctx)
        # The pending confirmation captures the import tool + resolved params.
        args, _ = service.ai_service.set_pending_confirmation.call_args
        assert args[0] == "u1"
        assert args[1] == {
            "type": "import_unit_products",
            "tool_key": "sqlite_import_unit_products",
            "params": {"saved_name": "test.xlsx", "unit_name": "测试公司"},
            "description": "导入 测试公司 的产品",
        }

    def test_unit_name_falls_back_to_plain_unit_name_key(self):
        service = _make_service()
        service.ai_service = Mock()
        ctx = {
            "saved_name": "test.xlsx",
            "unit_name": "直接单位名",  # no unit_name_guess
            "suggested_use": "unit_products_db",
        }
        service._handle_confirmation_flow("u1", "确认", ctx)
        payload = service.ai_service.set_pending_confirmation.call_args.args[1]
        assert payload["params"]["unit_name"] == "直接单位名"

    def test_confirm_without_unit_name(self):
        service = _make_service()
        service.ai_service = Mock()
        ctx = {
            "saved_name": "test.xlsx",
            "suggested_use": "unit_products_db",
        }
        # Missing unit name blocks the pending write (guard requires all three).
        service._handle_confirmation_flow("u1", "是", ctx)
        service.ai_service.set_pending_confirmation.assert_not_called()

    def test_confirm_wrong_suggested_use_not_pended(self):
        service = _make_service()
        service.ai_service = Mock()
        ctx = {
            "saved_name": "test.xlsx",
            "unit_name_guess": "测试公司",
            "suggested_use": "something_else",
        }
        service._handle_confirmation_flow("u1", "确认", ctx)
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
        # tool_call action but no tool_key -> falls back to echoing text + inner data.
        result = service._build_response(
            {
                "text": "processing",
                "action": "tool_call",
                "data": {"params": {}, "data": {"hint": "x"}},
            },
            None,
        )
        assert result["success"] is True
        assert result["response"] == "processing"
        # No toolCall is constructed when there is nothing to dispatch.
        assert "toolCall" not in result
        assert result["data"]["data"] == {"hint": "x"}

    def test_tool_call_pro_mode_products_query(self):
        service = _make_service()
        ai_result = {
            "text": "查询中",
            "action": "tool_call",
            "data": {
                "tool_key": "products",
                "slots": {"keyword": "清漆"},
                "params": {},
            },
        }
        mock_svc = Mock()
        mock_svc.get_products.return_value = {
            "success": True,
            "data": [{"model_number": "5003A"}, {"model_number": "5004B"}],
        }
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ):
                result = service._build_response(ai_result, "pro", "查询产品")
        # Products service is queried by keyword (no unit/model parsed).
        mock_svc.get_products.assert_called_once_with(keyword="清漆")
        assert result["success"] is True
        # Found products are surfaced in response text and autoAction payload.
        assert result["response"] == "查询到 2 个产品"
        assert result["data"]["data"]["products"] == [
            {"model_number": "5003A"},
            {"model_number": "5004B"},
        ]
        assert result["autoAction"]["tool_key"] == "products"
        assert result["autoAction"]["query"] == "清漆"

    def test_tool_call_pro_mode_products_empty(self):
        service = _make_service()
        ai_result = {
            "text": "查询中",
            "action": "tool_call",
            "data": {"tool_key": "products", "slots": {"keyword": "不存在"}, "params": {}},
        }
        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ):
                result = service._build_response(ai_result, "pro", "查询产品")
        # Empty result set produces the "not found" branch.
        assert result["response"] == "未找到产品"
        assert result["data"]["data"]["products"] == []


# ========================= _execute_customers_intent =====================


class TestExecuteCustomersIntent:
    def test_add_intent_no_unit_name(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        result = service._execute_customers_intent(resp, {}, {}, "添加单位")
        assert "哪个单位" in result["response"]
        # The missing-field intent is reported back for the UI to prompt on.
        assert result["data"]["data"] == {
            "intent": "customer_create",
            "missing_fields": ["unit_name"],
        }

    def test_add_intent_with_unit_creates_customer(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_exec:
            mock_exec.return_value = {"success": True, "created": True, "id": 9}
            result = service._execute_customers_intent(
                resp, {"unit_name": "七彩乐园"}, {}, "添加单位 七彩乐园"
            )
        # ensure_exists is invoked with the resolved unit name.
        mock_exec.assert_called_once_with(
            tool_id="customers", action="ensure_exists", params={"unit_name": "七彩乐园"}
        )
        assert result["response"] == "单位已创建：七彩乐园"
        assert result["data"]["data"] == {"success": True, "created": True, "id": 9}

    def test_add_intent_existing_unit_reports_existing(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_exec:
            mock_exec.return_value = {"success": True, "created": False}
            result = service._execute_customers_intent(
                resp, {}, {"customer_name": "老客户甲"}, "新增 老客户甲"
            )
        # unit_name resolved from parsed_params.customer_name; created=False branch.
        assert result["response"] == "单位已存在：老客户甲"

    def test_query_intent_lists_customers(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = Mock()
            mock_svc.get_all.return_value = {
                "success": True,
                "data": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
            }
            mock_get.return_value = mock_svc
            result = service._execute_customers_intent(resp, {}, {}, "查询客户列表")
        mock_svc.get_all.assert_called_once_with()
        assert result["response"] == "查询到 3 个客户"
        assert result["data"]["data"] == {
            "customers": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}]
        }

    def test_ambiguous_intent(self):
        service = _make_service()
        resp = {"success": True, "data": {}}
        result = service._execute_customers_intent(resp, {}, {}, "客户")
        # Neither add nor query keywords present -> followup guidance, no list query.
        assert result["data"]["data"] == {"intent": "customers_followup"}
        assert "添加单位" in result["response"] and "查询客户列表" in result["response"]


# ========================= _build_order_text_from_products ==============


class TestBuildOrderTextFromProducts:
    def test_basic(self):
        service = _make_service()
        products = [{"model": "5003", "quantity_tins": 10, "spec": 25}]
        result = service._build_order_text_from_products("公司A", products)
        assert result == "公司A，10桶5003规格25"

    def test_multiple_products_joined(self):
        service = _make_service()
        products = [
            {"model": "5003", "quantity_tins": 10, "spec": 25},
            {"model_number": "7782", "quantity": 3, "tin_spec": 18},
        ]
        result = service._build_order_text_from_products("公司B", products)
        # Falls back through model/quantity/spec aliases and joins with the comma.
        assert result == "公司B，10桶5003规格25，3桶7782规格18"

    def test_defaults_applied_when_qty_and_spec_missing(self):
        service = _make_service()
        # No quantity -> default 1; no spec and no default -> 25.
        result = service._build_order_text_from_products("公司C", [{"model": "X9"}])
        assert result == "公司C，1桶X9规格25"

    def test_empty_products(self):
        service = _make_service()
        assert service._build_order_text_from_products("公司A", []) == ""

    def test_empty_unit(self):
        service = _make_service()
        assert service._build_order_text_from_products("", [{"model": "X"}]) == ""


# ========================= _try_merge_split_model ========================


class TestTryMergeSplitModel:
    def test_merge_uses_template_quantity(self):
        service = _make_service()
        # First pattern matches "5003A规格25"; quantity comes from the template.
        result = service._try_merge_split_model("5003A规格25", {"quantity_tins": 7})
        assert result == "7桶5003A规格25"

    def test_merge_with_explicit_quantity_in_text(self):
        service = _make_service()
        result = service._try_merge_split_model("10桶5003A规格25", {"quantity_tins": 10})
        assert result == "10桶5003A规格25"

    def test_quantity_defaults_to_one(self):
        service = _make_service()
        # No quantity_tins in template -> defaults to 1.
        result = service._try_merge_split_model("7782B规格18", {})
        assert result == "1桶7782B规格18"

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
        mock_item.output = {
            "success": True,
            "response": "test",
            "message": "msg",
            "autoAction": {"type": "x"},
        }
        mock_result.node_results = [mock_item]
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result)
        # Only the whitelisted keys present in output are picked.
        assert result == {
            "response": "test",
            "message": "msg",
            "autoAction": {"type": "x"},
        }

    def test_skips_dispatch_without_action_or_task(self):
        mock_result = Mock()
        item = Mock()
        item.success = True
        item.tool_id = "normal_slot_dispatch"
        # Success but neither autoAction nor task -> not an overlay candidate.
        item.output = {"success": True, "response": "ignored"}
        mock_result.node_results = [item]
        assert AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result) == {}

    def test_skips_failed_or_other_tool(self):
        mock_result = Mock()
        failed = Mock()
        failed.success = False
        failed.tool_id = "normal_slot_dispatch"
        failed.output = {"success": True, "autoAction": {"type": "x"}}
        other = Mock()
        other.success = True
        other.tool_id = "some_other_tool"
        other.output = {"success": True, "autoAction": {"type": "y"}}
        mock_result.node_results = [failed, other]
        assert AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result) == {}

    def test_picks_last_matching_dispatch(self):
        mock_result = Mock()
        first = Mock()
        first.success = True
        first.tool_id = "normal_slot_dispatch"
        first.output = {"success": True, "response": "first", "task": {"id": 1}}
        last = Mock()
        last.success = True
        last.tool_id = "normal_slot_dispatch"
        last.output = {"success": True, "response": "last", "task": {"id": 2}}
        mock_result.node_results = [first, last]
        # Iteration is reversed -> the last node wins.
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(mock_result)
        assert result == {"response": "last", "task": {"id": 2}}


# ========================= process_chat ==================================


class TestProcessChat:
    def test_empty_message(self):
        service = _make_service()
        result = service.process_chat("u1", "")
        # Early guard: no AI call, just the validation message.
        assert result == {"success": False, "message": "消息内容不能为空"}

    @staticmethod
    def _service_with_failing_chat(exc: Exception):
        async def raise_exc(*a, **kw):
            raise exc

        mock_ai = Mock()
        mock_ai.chat = raise_exc
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
        service.ai_service = mock_ai
        # Avoid touching persistence / neuro bus during the error path.
        service._persist_chat_turn = Mock()
        return service

    def test_connection_error_returns_fallback(self):
        service = self._service_with_failing_chat(ConnectionError("refused"))
        result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False
        assert "连接失败" in result["message"]
        # Fallback envelope is fully populated for the UI.
        assert result["data"]["action"] == "error_fallback"
        assert result["data"]["data"]["fallback_mode"] is True
        assert result["data"]["data"]["error_reason"] == result["message"]
        assert result["response"] == result["data"]["text"]

    def test_timeout_error_returns_fallback(self):
        service = self._service_with_failing_chat(TimeoutError("timed out"))
        result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False
        assert "超时" in result["message"]
        assert result["data"]["action"] == "error_fallback"

    def test_api_key_error_maps_to_key_message(self):
        # A RuntimeError mentioning api_key is classified as a key config problem.
        service = self._service_with_failing_chat(RuntimeError("invalid api_key"))
        result = service.process_chat("u1", "查产品", source=None)
        assert result["success"] is False
        assert "API Key" in result["message"]
        assert result["data"]["data"]["fallback_mode"] is True

    def test_greeting_message_uses_greeting_fallback(self):
        # The greeting branch of the fallback response wins for "你好".
        service = self._service_with_failing_chat(RuntimeError("backend exploded"))
        result = service.process_chat("u1", "你好", source=None)
        assert result["success"] is False
        assert "XCAGI 智能助手" in result["response"]

    def test_successful_chat_builds_followup_response(self):
        async def ok_chat(*a, **kw):
            return {"text": "稍等", "action": "followup", "data": {"step": 1}}

        mock_ai = Mock()
        mock_ai.chat = ok_chat
        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ):
            service = _make_service()
        service.ai_service = mock_ai
        service._persist_chat_turn = Mock()
        result = service.process_chat("u1", "继续", source=None)
        assert result["success"] is True
        assert result["response"] == "稍等"
        assert result["followup"] == {"step": 1}


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
        assert result["success"] is True
        assert "Excel 分析上下文" in result["response"]
        # Followup tells the UI which intent stalled for lack of context.
        assert result["data"]["action"] == "followup"
        assert result["data"]["data"] == {"intent": "excel_import_missing_context"}

    def test_pro_import_with_file_context_no_saved_name(self):
        service = _make_service()
        ctx = {
            "file_analysis": {"suggested_use": "unit_products_db"},
            "file_context": {},
        }
        result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
        assert result["success"] is True
        assert "缺少源文件" in result["response"]
        assert result["data"]["action"] == "followup"
        # No source file -> empty inner data, asks user to upload/analyse first.
        assert result["data"]["data"] == {}

    def test_pro_import_with_file_context_no_unit_name(self):
        service = _make_service()
        ctx = {
            "file_analysis": {"suggested_use": "unit_products_db", "saved_name": "test.db"},
            "file_context": {},
        }
        result = service._try_handle_dynamic_workflow("u1", "导入", "pro", ctx, {})
        assert "客户名称" in result["response"]
        # Saved file present but unit name missing -> reports the missing field.
        assert result["data"]["data"] == {"missing_fields": ["unit_name"]}

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
        ) as mock_extract:
            result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
        # The ambiguity is surfaced from the extractor's blocked_reason verbatim.
        mock_extract.assert_called_once()
        assert result["data"]["action"] == "followup"
        inner = result["data"]["data"]
        assert inner["intent"] == "excel_import_to_db"
        assert inner["blocked_reason"] == "ambiguous_price_columns"
        assert inner["import_pipeline"] == "deterministic_shortcut"
        # Both ambiguous column families are named in the user-facing prompt.
        assert "调价前" in result["response"]
        assert "调价后" in result["response"]

    def test_pro_explicit_skip_deterministic_bypasses_rule_shortcut(self):
        service = _make_service()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"label": "单价"}],
                "preview_data": {"sample_rows": [{"客户": "A"}]},
            },
            "excel_import_ai_decides": True,  # opt out of the deterministic shortcut
        }
        # When AI decides, the deterministic record extractor must NOT run; the
        # request instead falls through to the LLM workflow planner branch.
        with patch.object(service, "_extract_excel_import_records") as mock_extract:
            result = service._try_handle_dynamic_workflow("u1", "导入数据库", "pro", ctx, {})
        mock_extract.assert_not_called()
        # Not the deterministic followup: it reaches the planner-driven path.
        assert result["data"]["action"] == "workflow_confirmation_required"
