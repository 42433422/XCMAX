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


# AIChatApplicationService._sanitize_import_scalar


# AIChatApplicationService._excel_analysis_payload_present


# AIChatApplicationService._looks_like_short_excel_import_command


# AIChatApplicationService._build_fallback_response


# _skip_pro_excel_deterministic_import


# AIChatApplicationService._row_values_look_like_table_headers


# AIChatApplicationService._excel_cell_looks_like_product_measure_unit


# AIChatApplicationService._model_like_score


# Public replacement of removed source/short-command/fallback classifiers.
# Sources never select a second brain and import words never grant write authority.
@pytest.mark.parametrize("source", ["pro", "normal", None])
@pytest.mark.parametrize("message", ["导入Excel", "你好", "确认", "取消", "测试消息"])
def test_public_chat_model_failure_has_no_local_success_or_implicit_import(source, message):
    from app.infrastructure.codex.policy import RuntimeSettings
    from tests.test_application.ai_chat_test_helpers import _make_svc

    service = _make_svc()
    with (
        patch(
            "app.application.agent_runtime.gateway.runtime_settings", return_value=RuntimeSettings()
        ),
        patch(
            "app.application.agent_runtime.gateway.run_runtime_task",
            return_value={
                "ok": False,
                "exit_status": "planning_failed",
                "business_completed": False,
            },
        ) as execute,
        patch.object(service, "_persist_chat_turn"),
        patch.object(service, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
    ):
        result = service.process_chat("single-brain", message, source=source)
    execute.assert_called_once()
    assert execute.call_args.kwargs["task"] == message
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert not hasattr(service, "workflow_planner")
    assert result["success"] is False
    assert result["business_completed"] is False
    assert not result.get("toolCall")
    assert not hasattr(service, "_pending_workflows")


def test_public_chat_empty_input_never_calls_model():
    from tests.test_application.ai_chat_test_helpers import _make_svc

    service = _make_svc()
    assert service.process_chat("empty", "")["success"] is False
    assert not hasattr(service, "workflow_planner")
