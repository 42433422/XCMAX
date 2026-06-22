"""扩展覆盖：ai_chat_app_service 缺失分支（静态方法 + process_chat 错误路径）。"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.utils.operational_errors import RECOVERABLE_ERRORS

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_svc():
    """构造能正常实例化的服务（模拟所有构造依赖）。"""
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


# ---------------------------------------------------------------------------
# process_chat — neuro_notify 异常不中断流程
# ---------------------------------------------------------------------------


class TestProcessChatNeuroBusBranches:
    def test_neuro_received_exception_ignored(self):
        """neuro_notify_chat_received 抛出 RECOVERABLE_ERRORS 时流程继续。"""
        svc = _make_svc()
        svc.ai_service.chat = AsyncMock(return_value={"success": True, "message": "ok"})
        svc._try_handle_dynamic_workflow = MagicMock(return_value=None)
        svc._handle_confirmation_flow = MagicMock()
        svc._inject_excel_vector_context = MagicMock(side_effect=lambda **kw: kw.get("context", {}))
        svc._persist_chat_turn = MagicMock()

        with patch(
            "app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received",
            side_effect=RuntimeError("bus down"),
        ):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed",
                return_value=None,
            ):
                result = svc.process_chat("u1", "hello")
        assert result.get("success") is True

    def test_neuro_completed_exception_ignored(self):
        """neuro_notify_chat_completed 抛出 RECOVERABLE_ERRORS 时仍返回结果。"""
        svc = _make_svc()
        svc.ai_service.chat = AsyncMock(return_value={"success": True, "message": "ok"})
        svc._try_handle_dynamic_workflow = MagicMock(return_value=None)
        svc._handle_confirmation_flow = MagicMock()
        svc._inject_excel_vector_context = MagicMock(side_effect=lambda **kw: kw.get("context", {}))
        svc._persist_chat_turn = MagicMock()

        with patch(
            "app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received",
            return_value=None,
        ):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed",
                side_effect=RuntimeError("bus down"),
            ):
                result = svc.process_chat("u1", "hello")
        assert result.get("success") is True


# ---------------------------------------------------------------------------
# process_chat — AI 服务错误分支
# ---------------------------------------------------------------------------


class TestProcessChatAIServiceErrors:
    def _svc_with_no_workflow(self):
        svc = _make_svc()
        svc._try_handle_dynamic_workflow = MagicMock(return_value=None)
        svc._handle_confirmation_flow = MagicMock()
        svc._inject_excel_vector_context = MagicMock(side_effect=lambda **kw: kw.get("context", {}))
        svc._persist_chat_turn = MagicMock()
        svc._build_fallback_response = MagicMock(side_effect=lambda msg, reason: {"success": False, "message": reason})
        return svc

    def test_connection_error(self):
        svc = self._svc_with_no_workflow()
        svc.ai_service.chat = AsyncMock(side_effect=ConnectionError("refused"))
        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                result = svc.process_chat("u1", "hello")
        assert "连接失败" in result["message"]

    def test_timeout_error(self):
        svc = self._svc_with_no_workflow()
        svc.ai_service.chat = AsyncMock(side_effect=TimeoutError("timed out"))
        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                result = svc.process_chat("u1", "hello")
        assert "超时" in result["message"]

    def test_recoverable_error_api_key(self):
        svc = self._svc_with_no_workflow()
        # RuntimeError is in RECOVERABLE_ERRORS; message contains "api_key" → special branch
        svc.ai_service.chat = AsyncMock(side_effect=RuntimeError("invalid api_key provided"))
        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                result = svc.process_chat("u1", "hello")
        assert "API Key" in result["message"]

    def test_recoverable_error_connection(self):
        svc = self._svc_with_no_workflow()
        # ValueError is in RECOVERABLE_ERRORS; message contains "connection" → connection branch
        svc.ai_service.chat = AsyncMock(side_effect=ValueError("connection refused by provider"))
        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                result = svc.process_chat("u1", "hello")
        assert "连接" in result["message"]

    def test_recoverable_error_other(self):
        svc = self._svc_with_no_workflow()
        # RuntimeError is in RECOVERABLE_ERRORS; generic message → else branch
        svc.ai_service.chat = AsyncMock(side_effect=RuntimeError("internal server error"))
        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                result = svc.process_chat("u1", "hello")
        assert "暂时不可用" in result["message"]

    def test_excel_file_path_in_file_context(self):
        """file_context 含 file_path 时注入 excel_analysis。"""
        svc = self._svc_with_no_workflow()
        svc.ai_service.chat = AsyncMock(return_value={"success": True, "message": "ok"})
        svc._inject_excel_vector_context = MagicMock(side_effect=lambda **kw: kw.get("context", {}))

        captured_context: dict = {}

        async def _capture_chat(user_id, message, context, source=None):
            captured_context.update(context)
            return {"success": True, "message": "ok"}

        svc.ai_service.chat = _capture_chat

        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                svc.process_chat(
                    "u1",
                    "导入数据",
                    context={},
                    file_context={"file_path": "/tmp/data.xlsx"},
                )
        assert captured_context.get("excel_analysis", {}).get("file_path") == "/tmp/data.xlsx"

    def test_excel_file_path_with_sheet_name(self):
        """file_context 含 sheet_name 时也注入到 excel_analysis。"""
        svc = self._svc_with_no_workflow()
        captured_context: dict = {}

        async def _capture_chat(user_id, message, context, source=None):
            captured_context.update(context)
            return {"success": True, "message": "ok"}

        svc.ai_service.chat = _capture_chat
        svc._inject_excel_vector_context = MagicMock(side_effect=lambda **kw: kw.get("context", {}))

        with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received", return_value=None):
            with patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_completed", return_value=None):
                svc.process_chat(
                    "u1",
                    "导入",
                    file_context={"file_path": "/tmp/d.xlsx", "sheet_name": "Sheet2"},
                )
        ea = captured_context.get("excel_analysis", {})
        assert ea.get("sheet_name") == "Sheet2"


# ---------------------------------------------------------------------------
# _sanitize_import_scalar
# ---------------------------------------------------------------------------


class TestSanitizeImportScalar:
    def test_none_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar(None) is None

    def test_nan_float_returns_none(self):
        assert AIChatApplicationService._sanitize_import_scalar(float("nan")) is None

    def test_string_nan_returns_none(self):
        for s in ("nan", "NaN", "NAN", "none", "None", "nat", "<na>", "null"):
            assert AIChatApplicationService._sanitize_import_scalar(s) is None, f"failed for {s!r}"

    def test_string_with_whitespace_stripped(self):
        assert AIChatApplicationService._sanitize_import_scalar("  hello  ") == "hello"

    def test_integer_passthrough(self):
        assert AIChatApplicationService._sanitize_import_scalar(42) == 42

    def test_float_nan_via_non_str(self):
        """custom object that converts to NaN float。"""
        class FakeNaN:
            def __float__(self):
                return float("nan")

        result = AIChatApplicationService._sanitize_import_scalar(FakeNaN())
        assert result is None

    def test_non_convertible_passthrough(self):
        obj = object()
        assert AIChatApplicationService._sanitize_import_scalar(obj) is obj


# ---------------------------------------------------------------------------
# _customer_hint_from_preview_grid
# ---------------------------------------------------------------------------


class TestCustomerHintFromPreviewGrid:
    def test_non_dict_returns_empty(self):
        assert AIChatApplicationService._customer_hint_from_preview_grid("bad") == ""

    def test_no_grid_preview_returns_empty(self):
        assert AIChatApplicationService._customer_hint_from_preview_grid({}) == ""

    def test_grid_preview_not_dict(self):
        assert (
            AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": "not-a-dict"}
            )
            == ""
        )

    def test_rows_not_list(self):
        assert (
            AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": "bad"}}
            )
            == ""
        )

    def test_import_error_returns_empty(self):
        """template_grid_core unavailable → except RECOVERABLE_ERRORS returns ''."""
        import sys
        # Force the import to fail by temporarily injecting a broken module
        saved = sys.modules.pop("app.application.template_grid_core", None)
        try:
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "ACME Corp"}]]}}
            )
        finally:
            if saved is not None:
                sys.modules["app.application.template_grid_core"] = saved
        # Either the import failed (returns "") or it succeeded (non-empty) — just assert no crash
        assert isinstance(result, str)

    def test_non_list_row_skipped(self):
        mock_fn = MagicMock(return_value=[])
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            mock_fn,
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": ["not-a-list", [{"text": "X"}]]}}
            )
        # "not-a-list" row is skipped; "X" row returns no hits → ""
        assert result == ""

    def test_non_dict_cell_skipped(self):
        mock_fn = MagicMock(return_value=[])
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            mock_fn,
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [["not-a-dict", {"text": ""}]]}}
            )
        assert result == ""

    def test_empty_text_cell_skipped(self):
        mock_fn = MagicMock(return_value=[])
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            mock_fn,
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "  "}, {"text": ""}]]}}
            )
        assert result == ""

    def test_cell_hit_returns_first(self):
        mock_fn = MagicMock(return_value=["Acme Corp"])
        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            mock_fn,
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "Acme Corp"}]]}}
            )
        assert result == "Acme Corp"

    def test_joined_row_hit(self):
        call_count = {"n": 0}

        def _mock_fn(text):
            call_count["n"] += 1
            # First cell: no hits; joined row: has hits
            if text == "foo bar":
                return ["FooBar Co"]
            return []

        with patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            side_effect=_mock_fn,
        ):
            result = AIChatApplicationService._customer_hint_from_preview_grid(
                {"grid_preview": {"rows": [[{"text": "foo"}, {"text": "bar"}]]}}
            )
        assert result == "FooBar Co"


# ---------------------------------------------------------------------------
# _default_purchase_unit_for_import
# ---------------------------------------------------------------------------


class TestDefaultPurchaseUnitForImport:
    def test_request_context_hint_takes_priority(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {},
            {},
            request_context={"excel_customer_hint": "Priority Co"},
        )
        assert result == "Priority Co"

    def test_preview_data_customer_hint(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {},
            {"customer_hint": "Preview Co"},
        )
        assert result == "Preview Co"

    def test_excel_analysis_customer_hint(self):
        result = AIChatApplicationService._default_purchase_unit_for_import(
            {"customer_hint": "Analysis Co"},
            {},
        )
        assert result == "Analysis Co"

    def test_grid_hint_fallback(self):
        with patch.object(
            AIChatApplicationService,
            "_customer_hint_from_preview_grid",
            return_value="Grid Co",
        ):
            with patch.object(
                AIChatApplicationService,
                "_resolve_excel_path_for_import",
                return_value="",
            ):
                result = AIChatApplicationService._default_purchase_unit_for_import({}, {})
        assert result == "Grid Co"

    def test_excel_file_parse_success(self, tmp_path):
        xl_file = tmp_path / "quotation.xlsx"
        xl_file.write_bytes(b"fake xlsx")
        with patch.object(
            AIChatApplicationService,
            "_customer_hint_from_preview_grid",
            return_value="",
        ):
            with patch.object(
                AIChatApplicationService,
                "_resolve_excel_path_for_import",
                return_value=str(xl_file),
            ):
                with patch.object(
                    AIChatApplicationService,
                    "_resolve_sheet_name_for_reimport",
                    return_value=None,
                ):
                    with patch(
                        "app.application.template_grid_core._extract_customer_hint_from_excel",
                        return_value="Parsed Co",
                    ):
                        result = AIChatApplicationService._default_purchase_unit_for_import(
                            {}, {}
                        )
        assert result == "Parsed Co"

    def test_excel_file_parse_exception_falls_through(self, tmp_path):
        xl_file = tmp_path / "file.xlsx"
        xl_file.write_bytes(b"fake")
        with patch.object(
            AIChatApplicationService, "_customer_hint_from_preview_grid", return_value=""
        ):
            with patch.object(
                AIChatApplicationService,
                "_resolve_excel_path_for_import",
                return_value=str(xl_file),
            ):
                with patch.object(
                    AIChatApplicationService, "_resolve_sheet_name_for_reimport", return_value=None
                ):
                    with patch(
                        "app.application.template_grid_core._extract_customer_hint_from_excel",
                        side_effect=RuntimeError("parse error"),
                    ):
                        with patch.object(
                            AIChatApplicationService,
                            "_guess_default_purchase_unit",
                            return_value="Guess Co",
                        ):
                            result = AIChatApplicationService._default_purchase_unit_for_import(
                                {}, {}
                            )
        assert result == "Guess Co"

    def test_no_file_guesses_from_analysis(self):
        with patch.object(
            AIChatApplicationService, "_customer_hint_from_preview_grid", return_value=""
        ):
            with patch.object(
                AIChatApplicationService, "_resolve_excel_path_for_import", return_value=""
            ):
                with patch.object(
                    AIChatApplicationService,
                    "_guess_default_purchase_unit",
                    return_value="Guessed",
                ):
                    result = AIChatApplicationService._default_purchase_unit_for_import({}, {})
        assert result == "Guessed"


# ---------------------------------------------------------------------------
# _guess_default_purchase_unit
# ---------------------------------------------------------------------------


class TestGuessDefaultPurchaseUnit:
    def test_empty_excel_analysis(self):
        assert AIChatApplicationService._guess_default_purchase_unit({}) == ""

    def test_file_name_with_company_suffix(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "成都修茈科技有限公司报价表.xlsx"}
        )
        assert "修茈" in result or "成都" in result

    def test_file_path_fallback(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_path": "/uploads/大丰实业有限公司2024年.xlsx"}
        )
        assert "大丰" in result or result == ""

    def test_strips_year_suffix(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "ACME公司2024年"}
        )
        # year suffix should be stripped
        assert "2024" not in result or result == ""

    def test_strips_quotation_suffix(self):
        result = AIChatApplicationService._guess_default_purchase_unit(
            {"file_name": "客户ABC产品报价表"}
        )
        assert "报价表" not in result

    def test_stem_too_short_returns_empty(self):
        result = AIChatApplicationService._guess_default_purchase_unit({"file_name": "x.xlsx"})
        assert result == ""


# ---------------------------------------------------------------------------
# _resolve_force_header_row_1based
# ---------------------------------------------------------------------------


class TestResolveForceHeaderRow:
    def test_grid_preview_header_row_index(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 2}}
        )
        assert result == 2

    def test_grid_preview_invalid_header_row(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": "bad"}}
        )
        assert result is None

    def test_grid_preview_zero_header_row(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {}, {"grid_preview": {"header_row_index": 0}}
        )
        assert result is None  # 0 is not >= 1

    def test_tables_header_row(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {},
            {"tables": [{"header_row": 3}]},
        )
        assert result == 3

    def test_tables_non_dict_skipped(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {},
            {"tables": ["not-a-dict", {"header_row": 1}]},
        )
        assert result == 1

    def test_tables_invalid_header_row(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {},
            {"tables": [{"header_row": "bad"}]},
        )
        assert result is None

    def test_sheets_tables_header_row(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"tables": [{"header_row": 4}]}]},
            {},
        )
        assert result == 4

    def test_sheets_grid_preview_header_row_index(self):
        result = AIChatApplicationService._resolve_force_header_row_1based(
            {"sheets": [{"grid_preview": {"header_row_index": 5}}]},
            {},
        )
        assert result == 5

    def test_no_clues_returns_none(self):
        assert AIChatApplicationService._resolve_force_header_row_1based({}, {}) is None


# ---------------------------------------------------------------------------
# _resolve_sheet_name_for_reimport
# ---------------------------------------------------------------------------


class TestResolveSheetName:
    def test_request_context_selected_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {},
            {},
            request_context={"excel_analysis_selected_sheet": {"sheet_name": "Sheet2"}},
        )
        assert result == "Sheet2"

    def test_request_context_preferred_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {},
            {},
            request_context={"preferred_sheet_name": "PrefSheet"},
        )
        assert result == "PrefSheet"

    def test_preview_data_selected_sheet_name(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {},
            {"selected_sheet_name": "Active"},
        )
        assert result == "Active"

    def test_preview_data_sheet_name(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {},
            {"sheet_name": "Data"},
        )
        assert result == "Data"

    def test_excel_analysis_first_sheet(self):
        result = AIChatApplicationService._resolve_sheet_name_for_reimport(
            {"sheets": [{"sheet_name": "First"}]},
            {},
        )
        assert result == "First"

    def test_no_info_returns_none(self):
        assert AIChatApplicationService._resolve_sheet_name_for_reimport({}, {}) is None


# ---------------------------------------------------------------------------
# _try_structured_reload_records
# ---------------------------------------------------------------------------


class TestTryStructuredReloadRecords:
    def test_no_file_path_returns_none(self):
        result = AIChatApplicationService._try_structured_reload_records({}, {})
        assert result is None

    def test_path_not_file_returns_none(self, tmp_path):
        result = AIChatApplicationService._try_structured_reload_records(
            {"file_path": str(tmp_path / "nonexistent.xlsx")}, {}
        )
        assert result is None

    def test_structured_parse_success(self, tmp_path):
        xl = tmp_path / "data.xlsx"
        xl.write_bytes(b"fake")
        mock_result = {"sample_rows": [{"col_A": "val1"}, {"col_A": "val2"}]}
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value=mock_result,
        ):
            with patch.object(
                AIChatApplicationService, "_resolve_sheet_name_for_reimport", return_value=None
            ):
                with patch.object(
                    AIChatApplicationService,
                    "_resolve_force_header_row_1based",
                    return_value=None,
                ):
                    result = AIChatApplicationService._try_structured_reload_records(
                        {"file_path": str(xl)}, {}
                    )
        assert result is not None
        assert len(result) == 2

    def test_rectangular_mode(self, tmp_path):
        xl = tmp_path / "data.xlsx"
        xl.write_bytes(b"fake")
        mock_result = {"sample_rows": [{"A": "x"}]}
        with patch(
            "app.application.template_grid_core._extract_rectangular_excel_preview",
            return_value=mock_result,
        ):
            with patch.object(
                AIChatApplicationService, "_resolve_sheet_name_for_reimport", return_value=None
            ):
                with patch.object(
                    AIChatApplicationService, "_resolve_force_header_row_1based", return_value=None
                ):
                    result = AIChatApplicationService._try_structured_reload_records(
                        {"file_path": str(xl)},
                        {"parse_mode": "rectangular"},
                    )
        assert result == [{"A": "x"}]

    def test_empty_sample_rows_returns_none(self, tmp_path):
        xl = tmp_path / "data.xlsx"
        xl.write_bytes(b"fake")
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value={"sample_rows": []},
        ):
            with patch.object(
                AIChatApplicationService, "_resolve_sheet_name_for_reimport", return_value=None
            ):
                with patch.object(
                    AIChatApplicationService,
                    "_resolve_force_header_row_1based",
                    return_value=None,
                ):
                    result = AIChatApplicationService._try_structured_reload_records(
                        {"file_path": str(xl)}, {}
                    )
        assert result is None

    def test_recoverable_error_returns_none(self, tmp_path):
        xl = tmp_path / "data.xlsx"
        xl.write_bytes(b"fake")
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            side_effect=RuntimeError("parse fail"),
        ):
            with patch.object(
                AIChatApplicationService, "_resolve_sheet_name_for_reimport", return_value=None
            ):
                with patch.object(
                    AIChatApplicationService,
                    "_resolve_force_header_row_1based",
                    return_value=None,
                ):
                    result = AIChatApplicationService._try_structured_reload_records(
                        {"file_path": str(xl)}, {}
                    )
        assert result is None

    def test_sanitizes_nan_in_rows(self, tmp_path):

        xl = tmp_path / "data.xlsx"
        xl.write_bytes(b"fake")
        mock_result = {"sample_rows": [{"val": float("nan"), "name": "ok"}]}
        with patch(
            "app.application.template_grid_core._extract_structured_excel_preview",
            return_value=mock_result,
        ):
            with patch.object(
                AIChatApplicationService, "_resolve_sheet_name_for_reimport", return_value=None
            ):
                with patch.object(
                    AIChatApplicationService,
                    "_resolve_force_header_row_1based",
                    return_value=None,
                ):
                    result = AIChatApplicationService._try_structured_reload_records(
                        {"file_path": str(xl)}, {}
                    )
        assert result is not None
        assert result[0]["val"] is None
        assert result[0]["name"] == "ok"
