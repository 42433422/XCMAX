"""Active Excel helpers and unified model-plan contracts; no retired dispatch brain.

Removed internal source classifiers are covered through process_chat, model admission,
registered authenticated tools and the durable approval/session regression suites.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# AIChatApplicationService._is_pro_source


# AIChatApplicationService._is_number_text


class TestIsNumberText:
    def test_integer_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("42")
        assert result is True

    def test_float_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("3.14")
        assert result is True

    def test_non_number_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("hello")
        assert result is False

    def test_empty_string(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("")
        assert result is False

    def test_negative_number(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._is_number_text("-5")
        assert result is True


# AIChatApplicationService._sanitize_import_scalar


class TestSanitizeImportScalar:
    def test_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar(None)
        assert result is None or result == ""

    def test_string(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar("hello")
        assert result == "hello"

    def test_number(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar(42)
        assert result == 42 or result == "42"

    def test_nan(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._sanitize_import_scalar(float("nan"))
        assert result is None or isinstance(result, (str, float))


# AIChatApplicationService._excel_analysis_payload_present


class TestExcelAnalysisPayloadPresent:
    def test_none_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_analysis_payload_present(None)
        assert result is False

    def test_empty_context(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_analysis_payload_present({})
        assert result is False

    def test_with_excel_analysis(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        # The implementation considers excel_analysis "present" when it has a
        # non-empty `summary`, a non-empty `fields` list, `preview_data.sample_rows`,
        # or `preview_data.grid_preview.rows` with >= 2 entries.
        context = {"excel_analysis": {"summary": "found columns A, B"}}
        result = AIChatApplicationService._excel_analysis_payload_present(context)
        assert result is True


# AIChatApplicationService._looks_like_short_excel_import_command


# AIChatApplicationService._build_fallback_response


# _skip_pro_excel_deterministic_import


class TestSkipProExcelDeterministicImport:
    def test_none_context(self):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        result = _skip_pro_excel_deterministic_import(None)
        assert isinstance(result, bool)

    def test_empty_context(self):
        from app.application.ai_chat_app_service import _skip_pro_excel_deterministic_import

        result = _skip_pro_excel_deterministic_import({})
        assert isinstance(result, bool)


# AIChatApplicationService._row_values_look_like_table_headers


class TestRowValuesLookLikeTableHeaders:
    def test_header_like_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        values = ["产品名称", "型号", "数量", "单价"]
        result = AIChatApplicationService._row_values_look_like_table_headers(values)
        assert isinstance(result, bool)

    def test_numeric_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        values = ["100", "200", "300"]
        result = AIChatApplicationService._row_values_look_like_table_headers(values)
        assert result is False

    def test_empty_values(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._row_values_look_like_table_headers([])
        assert result is False


# AIChatApplicationService._excel_cell_looks_like_product_measure_unit


class TestExcelCellLooksLikeProductMeasureUnit:
    def test_common_unit(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_cell_looks_like_product_measure_unit("kg")
        assert isinstance(result, bool)

    def test_non_unit(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_cell_looks_like_product_measure_unit("产品A")
        assert result is False

    def test_none(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._excel_cell_looks_like_product_measure_unit(None)
        assert result is False


# AIChatApplicationService._model_like_score


class TestModelLikeScore:
    def test_model_number(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._model_like_score("ABC-123")
        assert isinstance(result, float)
        assert result >= 0

    def test_plain_text(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._model_like_score("产品名称")
        assert isinstance(result, float)

    def test_empty(self):
        from app.application.ai_chat_app_service import AIChatApplicationService

        result = AIChatApplicationService._model_like_score("")
        assert isinstance(result, float)


# Public replacement of removed source/short-command/fallback classifiers.
# Sources never select a second brain and import words never grant write authority.
@pytest.mark.parametrize("source", ["pro", "normal", None])
@pytest.mark.parametrize("message", ["导入Excel", "你好", "确认", "取消", "测试消息"])
def test_public_chat_model_failure_has_no_local_success_or_implicit_import(source, message):
    from unittest.mock import Mock

    from app.application.workflow.planner import LLMWorkflowPlanner
    from tests.test_application.ai_chat_test_helpers import _make_svc

    service = _make_svc()
    completion = Mock(return_value=None)
    service.workflow_planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    with (
        patch.object(service, "_persist_chat_turn"),
        patch.object(service, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
    ):
        result = service.process_chat("single-brain", message, source=source)
    if message in {"确认", "取消"}:
        completion.assert_not_called()
        assert result["data"]["action"] == "clarification_required"
        assert "没有待确认" in result["response"]
        assert not result.get("toolCall")
        assert not service._pending_workflows
        return
    completion.assert_called_once()
    assert result["success"] is False
    assert result["data"]["execution_started"] is False
    assert not result.get("toolCall")
    assert not service._pending_workflows


def test_public_chat_empty_input_never_calls_model():
    from tests.test_application.ai_chat_test_helpers import _make_svc

    service = _make_svc()
    assert service.process_chat("empty", "")["success"] is False
    service.workflow_planner.plan.assert_not_called()
