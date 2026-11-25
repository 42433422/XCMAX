"""Tests for app.application.ai_chat_app_service — deep coverage for remaining uncovered branches.

Focus: private methods, error branches, edge cases, and complex conditional logic
not covered by ext/ext2 test suites.
"""

from __future__ import annotations

import math
from contextlib import contextmanager as _shared_scope_contextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
)
from tests.test_application.ai_chat_test_helpers import (
    _make_svc as _make_service,
)


class TestProcessChatDeepErrors:
    def test_empty_message_returns_error(self):
        service = _make_service()
        result = service.process_chat("u1", "")
        assert result["success"] is False
        assert "不能为空" in result["message"]


class TestPersistChatTurnDeep:
    def test_no_session_id_skips(self):
        service = _make_service()
        # Should not raise
        service._persist_chat_turn("u1", "hello", {}, {"success": True})

    def test_with_session_id_persists(self):
        service = _make_service()
        mock_conv = Mock()
        with patch("app.services.get_conversation_service", return_value=mock_conv):
            service._persist_chat_turn(
                "u1",
                "hello",
                {"session_id": "sess1", "local_user_id": 17, "actor_id": 17},
                {
                    "success": True,
                    "response": "world",
                    "data": {"text": "world", "action": "reply", "data": {}},
                },
            )
        assert mock_conv.save_turn.call_count == 1
        assert all(call.kwargs["user_id"] == "17" for call in mock_conv.save_turn.call_args_list)

    def test_with_conversation_id_persists(self):
        service = _make_service()
        mock_conv = Mock()
        with patch("app.services.get_conversation_service", return_value=mock_conv):
            service._persist_chat_turn(
                "u1",
                "hello",
                {"conversation_id": "conv1", "local_user_id": 17, "actor_id": 17},
                {"success": True, "response": "world", "data": {}},
            )
        assert mock_conv.save_turn.call_count == 1
        assert all(call.kwargs["user_id"] == "17" for call in mock_conv.save_turn.call_args_list)

    def test_with_tool_call_data(self):
        service = _make_service()
        mock_conv = Mock()
        with patch("app.services.get_conversation_service", return_value=mock_conv):
            service._persist_chat_turn(
                "u1",
                "hello",
                {"session_id": "sess1", "local_user_id": 17, "actor_id": 17},
                {
                    "success": True,
                    "response": "done",
                    "data": {
                        "text": "done",
                        "action": "tool_call",
                        "data": {"tool_key": "products"},
                    },
                    "toolCall": {"tool_id": "products"},
                },
            )
        assert mock_conv.save_turn.call_count == 1
        assert all(call.kwargs["user_id"] == "17" for call in mock_conv.save_turn.call_args_list)


class TestInjectExcelVectorContextDeep:
    def test_successful_query(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": [{"score": 0.9}]}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" in result
        assert result["excel_vector_context"]["hits"] == [{"score": 0.9}]

    def test_custom_top_k(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context(
                "hello", {"excel_index_id": "idx1", "excel_top_k": 10}
            )
        mock_svc.query.assert_called_once_with(index_id="idx1", query_text="hello", top_k=10)

    def test_invalid_top_k_defaults_to_5(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context(
                "hello", {"excel_index_id": "idx1", "excel_top_k": "abc"}
            )
        mock_svc.query.assert_called_once_with(index_id="idx1", query_text="hello", top_k=5)

    def test_vector_index_id_alias(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context(
                "hello", {"excel_vector_index_id": "vidx1"}
            )
        mock_svc.query.assert_called_once()


@pytest.mark.parametrize(
    "message",
    [
        "你好",
        "您好",
        "hi",
        "hello",
        "嗨",
        "hi there",
        "查询产品",
        "加入数据库",
        "导入数据库",
        "入库",
        "请导入数据库",
        "A" * 41,
        "生成发货单",
        "查询发货记录",
        "查询甲公司的5003",
        "运行custom_tool",
    ],
)
@pytest.mark.parametrize("source", ["basic", "pro", None])
def test_unqualified_fixed_runtime_never_falls_back_to_local_reply_or_tool(message, source):
    """All source labels and utterances require the same qualified executor."""
    from app.infrastructure.xiaox.policy import RuntimeSettings

    service = _make_service()
    with (
        patch(
            "app.application.agent_runtime.gateway.runtime_settings", return_value=RuntimeSettings()
        ),
        patch.object(service, "_persist_chat_turn"),
        patch.object(service, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
    ):
        result = service.process_chat("unified-failure", message, source=source)
    assert not hasattr(service, "workflow_planner")
    assert result["success"] is False
    assert result["runtime"] == "xiaox"
    assert result["data"]["error_code"] == "runtime_policy_blocked"
    assert result["data"]["business_receipts"] == []
    assert result["data"]["tool_calls"] == []
    assert not result.get("toolCall")
    assert not hasattr(service, "_pending_workflows")


@pytest.mark.parametrize("message", ["", None])
def test_empty_input_stops_before_unified_model(message):
    service = _make_service()
    result = service.process_chat("empty", message)
    assert result == {"success": False, "message": "消息内容不能为空"}
    assert not hasattr(service, "workflow_planner")


def test_unsigned_context_cannot_supply_business_owner():
    from app.application.agent_runtime.gateway import _trusted_context
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError

    with pytest.raises(AgentModAuthorizationError, match="登录|身份"):
        _trusted_context({"tenant_id": "999", "local_user_id": 7, "source": "admin"})


@pytest.mark.parametrize(
    "file_context",
    [
        {"file_path": "/test.xlsx", "sheet_name": "Sheet1"},
        {"suggested_use": "unit_products_db", "saved_name": "", "unit_name": "甲"},
        {"suggested_use": "unit_products_db", "saved_name": "f.db", "unit_name": ""},
        {"suggested_use": "unit_products_db", "saved_name": "data.db", "unit_name": "甲公司"},
    ],
)
def test_file_context_reaches_model_without_direct_import(file_context):
    from app.infrastructure.xiaox.policy import RuntimeSettings

    service = _make_service()
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
        patch("app.application.get_unit_products_import_app_service") as direct_import,
    ):
        result = service.process_chat(
            "file-context", "请分析这个文件", source="pro", file_context=file_context
        )
    execute.assert_called_once()
    assert execute.call_args.kwargs["input_data"]["file_context"] == file_context
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert not hasattr(service, "workflow_planner")
    direct_import.assert_not_called()
    assert result["success"] is False
    assert result["business_completed"] is False


@pytest.mark.parametrize(
    "reason",
    ["connection refused", "timed out", "api_key=private-test-secret", "unknown internal error"],
)
def test_runtime_policy_failure_is_safe_and_does_not_call_legacy_chat(reason):
    from app.infrastructure.xiaox.policy import RuntimePolicyError

    service = _make_service()
    with (
        patch(
            "app.application.agent_runtime.gateway.run_runtime_task",
            side_effect=RuntimePolicyError(reason),
        ),
        patch.object(service, "_persist_chat_turn"),
        patch.object(service, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
    ):
        result = service.process_chat("transport-failure", "解释一下库存查询")
    assert not hasattr(service, "workflow_planner")
    assert result["success"] is False
    assert result["data"]["error_code"] == "runtime_not_qualified"
    assert result["data"]["business_receipts"] == []
    assert result["data"]["tool_calls"] == []
    assert "private-test-secret" not in str(result)


@pytest.mark.parametrize("source", ["basic", "pro", "xcagi-pro", "PRO_MODE", "professional"])
def test_all_source_labels_execute_the_same_fixed_runtime(source):
    from app.infrastructure.xiaox.policy import RuntimeSettings

    service = _make_service()
    with (
        patch(
            "app.application.agent_runtime.gateway.runtime_settings", return_value=RuntimeSettings()
        ),
        patch(
            "app.application.agent_runtime.gateway.run_runtime_task",
            return_value={
                "ok": True,
                "run_id": "fixed-parent",
                "exit_status": "reply_completed",
                "output": "这是模型生成的说明",
            },
        ) as execute,
        patch.object(service, "_persist_chat_turn"),
        patch.object(service, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
    ):
        result = service.process_chat("unified-reply", "解释一下工作方式", source=source)
    execute.assert_called_once()
    assert execute.call_args.kwargs["task"] == "解释一下工作方式"
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert not hasattr(service, "workflow_planner")
    assert result["success"] is True
    assert result["response"] == "这是模型生成的说明"
    assert result["runtime"] == "xiaox"
    assert result["run_id"] == "fixed-parent"
    assert not result.get("toolCall")
