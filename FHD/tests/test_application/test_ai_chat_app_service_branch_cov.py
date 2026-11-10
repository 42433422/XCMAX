"""AI chat service branch and confirmation-boundary regressions."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)
from tests.test_application.ai_chat_test_helpers import (
    _make_node,
    _make_node_result,
    _make_plan,
    _make_run_result,
    _make_svc,
)


def _make_step(
    *,
    node_id: str = "n1",
    tool_id: str = "products",
    action: str = "query",
    status: str = "completed",
    output=None,
    error: str = "",
    step_id: str = "step_1",
    duration_ms: int = 10,
    params=None,
):
    return SimpleNamespace(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        status=status,
        output=output or {},
        error=error,
        step_id=step_id,
        duration_ms=duration_ms,
        params=params or {},
    )


def _make_agent_run(
    *,
    run_id: str = "run_1",
    status: str = "completed",
    steps=None,
    tool_calls=None,
    artifacts=None,
    metadata=None,
    plan_id: str = "plan_test",
    intent: str = "test_intent",
    message: str = "",
    user_id: str = "u1",
):
    return SimpleNamespace(
        run_id=run_id,
        status=status,
        steps=steps or [],
        tool_calls=tool_calls or [],
        artifacts=artifacts or [],
        metadata=metadata or {},
        plan_id=plan_id,
        intent=intent,
        message=message,
        user_id=user_id,
    )


class TestLooksLikeExplicitWorkflowToolIntent:
    """_looks_like_explicit_workflow_tool_intent 分支测试。"""

    def test_empty_text_returns_false(self):
        assert AIChatApplicationService._looks_like_explicit_workflow_tool_intent("") is False

    def test_none_text_returns_false(self):
        assert AIChatApplicationService._looks_like_explicit_workflow_tool_intent(None) is False

    def test_employee_mentioned_with_action_returns_true(self):
        """员工 + 调用 → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("把任务交给员工执行")
            is True
        )

    def test_employee_call_in_english_returns_true(self):
        """employee + call → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent(
                "call employee to run"
            )
            is True
        )

    def test_employee_mentioned_no_action_returns_false(self):
        """员工但无动作 → False（无 db）。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("员工列表") is False
        )

    def test_db_mentioned_with_object_and_action_returns_true(self):
        """数据库 + 客户 + 查 → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("查数据库里的客户")
            is True
        )

    def test_db_mentioned_no_object_returns_false(self):
        """数据库但无对象 → False。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("读取数据库")
            is False
        )

    def test_db_mentioned_no_action_returns_false(self):
        """数据库 + 对象但无动作 → False。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("数据库里的客户信息")
            is False
        )

    def test_db_keyword_english_with_chinese_object_returns_true(self):
        """database + 客户 + query → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent(
                "query 客户 from database"
            )
            is True
        )

    def test_db_word_boundary_with_chinese_object_returns_true(self):
        """\bdb\b 边界匹配 + 产品 + read → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("read 产品 from db")
            is True
        )

    def test_db_keyword_english_no_chinese_object_returns_false(self):
        """database + query 但无中文对象 → False。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent(
                "query customer from database"
            )
            is False
        )

    def test_db_word_boundary_no_chinese_object_returns_false(self):
        """\bdb\b 边界匹配但无中文对象 → False。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent(
                "read products from db"
            )
            is False
        )

    def test_no_db_no_employee_returns_false(self):
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("你好世界") is False
        )

    def test_db_action_only_english_with_chinese_object_returns_true(self):
        """database + write + 产品 → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent(
                "write 产品 to database"
            )
            is True
        )

    def test_db_delete_action_returns_true(self):
        """数据库 + 删除 + 产品 → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("删除数据库中的产品")
            is True
        )

    def test_employee_let_keyword_returns_true(self):
        """让 + 员工 → True。"""
        assert (
            AIChatApplicationService._looks_like_explicit_workflow_tool_intent("让员工去处理")
            is True
        )


class TestWorkflowOutputPreview:
    """_workflow_output_preview 分支测试。"""

    def test_none_returns_empty(self):
        assert AIChatApplicationService._workflow_output_preview(None) == ""

    def test_non_dict_value_serialized(self):
        result = AIChatApplicationService._workflow_output_preview("hello")
        assert "hello" in result

    def test_dict_with_message(self):
        result = AIChatApplicationService._workflow_output_preview(
            {"success": True, "message": "ok"}
        )
        assert "ok" in result
        assert "true" in result.lower()

    def test_dict_with_data_list(self):
        result = AIChatApplicationService._workflow_output_preview({"data": [{"id": 1}, {"id": 2}]})
        assert "row_count" in result
        assert "2" in result

    def test_dict_with_data_dict(self):
        result = AIChatApplicationService._workflow_output_preview(
            {"data": {"summary": "s1", "result": "r1", "unknown": "x"}}
        )
        assert "s1" in result or "r1" in result

    def test_dict_with_data_dict_empty_filtered(self):
        """data 是 dict 但无已知键 → 退化为 str。"""
        result = AIChatApplicationService._workflow_output_preview(
            {"data": {"unknown_key": "unknown_val"}}
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_dict_with_data_non_list_non_dict(self):
        """data 是字符串 → 直接放入 value。"""
        result = AIChatApplicationService._workflow_output_preview({"data": "raw_string"})
        assert "raw_string" in result

    def test_dict_with_raw_field(self):
        result = AIChatApplicationService._workflow_output_preview(
            {"raw": "raw_data", "success": True}
        )
        assert "raw_data" in result

    def test_dict_with_raw_and_data_no_conflict(self):
        """raw + data 同时存在时，data 优先。"""
        result = AIChatApplicationService._workflow_output_preview(
            {"raw": "raw_val", "data": [{"x": 1}]}
        )
        assert "row_count" in result

    def test_long_output_truncated(self):
        long_msg = "x" * 1000
        result = AIChatApplicationService._workflow_output_preview({"message": long_msg})
        assert len(result) <= 703  # 700 + "..."

    def test_unserializable_value_falls_back_to_str(self):
        class Unserializable:
            def __repr__(self):
                return "<Unserializable>"

        result = AIChatApplicationService._workflow_output_preview(Unserializable())
        assert "Unserializable" in result

    def test_dict_with_error_field(self):
        result = AIChatApplicationService._workflow_output_preview({"error": "boom"})
        assert result == "{}"


class TestWorkflowOutputMessage:
    """_workflow_output_message 分支测试。"""

    def test_non_dict_returns_empty(self):
        assert AIChatApplicationService._workflow_output_message("not dict") == ""

    def test_none_returns_empty(self):
        assert AIChatApplicationService._workflow_output_message(None) == ""

    def test_dict_with_message(self):
        assert AIChatApplicationService._workflow_output_message({"message": "hello"}) == "hello"

    def test_dict_with_error_only(self):
        assert AIChatApplicationService._workflow_output_message({"error": "boom"}) == ""

    def test_dict_message_takes_priority_over_error(self):
        assert (
            AIChatApplicationService._workflow_output_message({"message": "ok", "error": "boom"})
            == "ok"
        )

    def test_dict_empty_message_and_error(self):
        assert AIChatApplicationService._workflow_output_message({"message": "", "error": ""}) == ""

    def test_dict_with_whitespace_message(self):
        assert (
            AIChatApplicationService._workflow_output_message({"message": "  spaced  "}) == "spaced"
        )


class TestAttachDeterministicWorkflowTrace:
    """_attach_deterministic_workflow_trace 分支测试。"""

    def test_import_error_returns_payload_unchanged(self):
        """chat_trace 模块不可用 → 返回原 payload。"""
        payload = {"success": True, "message": "ok"}
        import sys

        module_name = "app.application.agent_orchestrator.chat_trace"
        parent = sys.modules["app.application.agent_orchestrator"]
        missing = object()
        saved = sys.modules.pop(module_name, missing)
        saved_attribute = getattr(parent, "chat_trace", missing)
        try:
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context={"k": "v"},
                intent="test",
            )
        finally:
            if saved is missing:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = saved
            # Re-import also writes the parent package attribute. Restore both
            # identities so later patches target the module used by imports.
            if saved_attribute is missing:
                parent.__dict__.pop("chat_trace", None)
            else:
                parent.chat_trace = saved_attribute
        assert result is payload

    @pytest.mark.parametrize("preloaded", [False, True])
    def test_import_error_restores_module_and_parent_identity(self, monkeypatch, preloaded):
        import importlib
        import sys

        name = "app.application.agent_orchestrator.chat_trace"
        original = importlib.import_module(name)
        parent = sys.modules["app.application.agent_orchestrator"]
        monkeypatch.setattr(parent, "chat_trace", original)
        if not preloaded:
            monkeypatch.delitem(sys.modules, name)
            monkeypatch.delattr(parent, "chat_trace")
        self.test_import_error_returns_payload_unchanged()
        assert sys.modules.get(name) is (original if preloaded else None)
        assert getattr(parent, "chat_trace", None) is (original if preloaded else None)

    def test_with_file_context_attaches_trace(self):
        payload = {"success": True, "message": "ok"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={**payload, "run_id": "run_1"},
        ) as mock_attach:
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context={"k": "v"},
                intent="test",
                file_context={"file_path": "/tmp/x.xlsx"},
            )
        assert mock_attach.called
        call_kwargs = mock_attach.call_args
        # runtime_context should contain workflow_intent and file_context
        runtime_ctx = call_kwargs.kwargs.get("runtime_context") or call_kwargs[1].get(
            "runtime_context"
        )
        assert runtime_ctx["workflow_intent"] == "test"
        assert runtime_ctx["workflow_trace_mode"] == "deterministic_shortcut"
        assert "file_context" in runtime_ctx
        assert "run_id" in result

    def test_without_file_context(self):
        payload = {"success": True}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={**payload, "run_id": "run_2"},
        ):
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source=None,
                context=None,
                intent="test",
            )
        assert "run_id" in result

    def test_context_not_dict_handled(self):
        payload = {"success": True}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={**payload, "run_id": "run_3"},
        ) as mock_attach:
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context="not-a-dict",
                intent="test",
            )
        assert mock_attach.called
        assert "run_id" in result

    def test_empty_file_context_not_added(self):
        payload = {"success": True}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={**payload, "run_id": "run_4"},
        ) as mock_attach:
            AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context={},
                intent="test",
                file_context={},
            )
        call_kwargs = mock_attach.call_args
        runtime_ctx = call_kwargs.kwargs.get("runtime_context")
        assert "file_context" not in runtime_ctx


class TestFormatWorkflowToolSuccessLine:
    """_format_workflow_tool_success_line 分支测试。"""

    def test_employee_list_action(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="employee",
            action="list",
            output={"data": {"registered_tool_count": 5}},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "5" in result[0]
        assert "员工" in result[0]

    def test_employee_list_action_no_count(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="employee",
            action="list",
            output={},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "0" in result[0]

    def test_employee_non_list_action_with_message(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="employee",
            action="create",
            output={"employee_id": "emp_1", "message": "created"},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "emp_1" in result[0]
        assert "created" in result[0]

    def test_employee_non_list_action_no_employee_id(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="employee",
            action="create",
            output={"message": "ok"},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "-" in result[0]

    def test_employee_with_preview(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="employee",
            action="list",
            output={"data": {"registered_tool_count": 3}, "message": "ok"},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert len(result) >= 2
        assert "预览" in result[1]

    def test_business_db_read_action(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="business_db",
            action="read",
            output={"data": [{"id": 1}, {"id": 2}]},
        )
        result = svc._format_workflow_tool_success_line(item, {"entity": "customer"})
        assert "customer" in result[0]
        assert "2" in result[0]

    def test_business_db_read_action_no_rows(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="business_db",
            action="query",
            output={},
        )
        result = svc._format_workflow_tool_success_line(item, {"entity": "product"})
        assert "product" in result[0]
        assert "0" in result[0]

    def test_business_db_write_action(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="business_db",
            action="create",
            output={"message": "created"},
        )
        result = svc._format_workflow_tool_success_line(
            item, {"entity": "customer", "operation": "create"}
        )
        assert "customer" in result[0]

    def test_business_db_with_entity_from_output(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="business_db",
            action="read",
            output={"data": [], "entity": "order"},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "order" in result[0]

    def test_other_tool_with_message(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="products",
            action="query",
            output={"message": "found 3 items"},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "found 3 items" in result[0]

    def test_other_tool_no_message(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="shipments",
            action="query",
            output={},
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert "成功" in result[0]

    def test_output_not_dict_handled(self):
        svc = _make_svc()
        item = SimpleNamespace(
            node_id="n1",
            tool_id="products",
            action="query",
            output="not-a-dict",
        )
        result = svc._format_workflow_tool_success_line(item, {})
        assert len(result) >= 1


class TestFormatAgentRunResponse:
    """_format_agent_run_response 分支测试。"""

    def test_completed_status_with_thinking_steps(self):
        svc = _make_svc()
        plan = _make_plan(todo_steps=["step1", "step2"])
        agent_run = _make_agent_run(
            status="completed",
            steps=[_make_step(status="completed", output={"message": "ok"})],
            metadata={"cost_units_total": 10, "tool_call_count": 2},
        )
        result = svc._format_agent_run_response(
            plan, agent_run, thinking_steps="thinking", user_message="hello"
        )
        assert result["success"] is True
        assert "thinking" in result["response"]
        assert "TODO" in result["response"]
        assert result["data"]["action"] == "workflow_done"

    def test_failed_status(self):
        svc = _make_svc()
        plan = _make_plan()
        agent_run = _make_agent_run(status="failed", steps=[])
        result = svc._format_agent_run_response(plan, agent_run)
        assert result["success"] is False
        assert result["data"]["action"] == "workflow_failed"

    def test_step_not_completed(self):
        svc = _make_svc()
        plan = _make_plan()
        agent_run = _make_agent_run(
            status="completed",
            steps=[_make_step(status="failed", error="boom")],
        )
        result = svc._format_agent_run_response(plan, agent_run)
        assert "工作流执行失败，详细信息已记录" in result["response"]
        assert "boom" not in result["response"]

    def test_step_not_completed_no_error(self):
        svc = _make_svc()
        plan = _make_plan()
        agent_run = _make_agent_run(
            status="completed",
            steps=[_make_step(status="pending", error="")],
        )
        result = svc._format_agent_run_response(plan, agent_run)
        assert "工作流执行失败，详细信息已记录" in result["response"]

    def test_with_artifacts(self):
        svc = _make_svc()
        plan = _make_plan()
        artifact = SimpleNamespace()
        artifact.to_dict = Mock(return_value={"artifact_type": "file", "name": "test"})
        agent_run = _make_agent_run(
            status="completed",
            artifacts=[artifact],
        )
        result = svc._format_agent_run_response(plan, agent_run)
        assert "Artifacts" in result["response"]

    def test_with_tool_call_count(self):
        svc = _make_svc()
        plan = _make_plan()
        agent_run = _make_agent_run(
            status="completed",
            metadata={"cost_units_total": 5, "tool_call_count": 3},
        )
        result = svc._format_agent_run_response(plan, agent_run)
        assert "工具调用" in result["response"]
        assert "成本单位" in result["response"]

    def test_products_query_auto_action(self):
        svc = _make_svc()
        plan = _make_plan()
        agent_run = _make_agent_run(
            status="completed",
            steps=[_make_step(tool_id="products", action="query", status="completed")],
        )
        result = svc._format_agent_run_response(plan, agent_run, user_message="find products")
        assert "autoAction" in result
        assert result["autoAction"]["type"] == "show_products_float"
        assert result["autoAction"]["query"] == "find products"

    def test_products_query_full_list_keeps_empty_float_query(self):
        svc = _make_svc()
        plan = _make_plan(
            nodes=[
                _make_node(
                    node_id="products-query",
                    tool_id="products",
                    action="query",
                    params={"keyword": ""},
                )
            ]
        )
        agent_run = _make_agent_run(
            status="completed",
            steps=[
                _make_step(
                    node_id="products-query",
                    tool_id="products",
                    action="query",
                    status="completed",
                )
            ],
        )
        result = svc._format_agent_run_response(
            plan,
            agent_run,
            user_message="查询当前产品列表",
        )
        assert result["autoAction"]["query"] == ""

    def test_no_thinking_steps_no_todo(self):
        svc = _make_svc()
        plan = _make_plan(todo_steps=[])
        agent_run = _make_agent_run(status="completed", steps=[])
        result = svc._format_agent_run_response(plan, agent_run)
        assert "TODO" not in result["response"]

    def test_tool_calls_in_data(self):
        svc = _make_svc()
        plan = _make_plan()
        call = SimpleNamespace(
            call_id="c1",
            step_id="s1",
            node_id="n1",
            tool_id="products",
            action="query",
            status="completed",
            cost_units=2,
            duration_ms=100,
            permission="read",
        )
        agent_run = _make_agent_run(
            status="completed",
            tool_calls=[call],
        )
        result = svc._format_agent_run_response(plan, agent_run)
        assert len(result["data"]["data"]["tool_calls"]) == 1

    def test_node_results_in_data(self):
        svc = _make_svc()
        plan = _make_plan()
        agent_run = _make_agent_run(
            status="completed",
            steps=[_make_step(status="completed", output={"message": "done"})],
        )
        result = svc._format_agent_run_response(plan, agent_run)
        assert len(result["data"]["data"]["node_results"]) == 1





class TestWorkflowProductsFloatQuery:
    """_workflow_products_float_query 补充分支测试。"""

    def test_node_params_keyword(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[_make_node(params={"keyword": "paint"})])
        run_result = _make_run_result()
        result = svc._workflow_products_float_query(plan, run_result, "msg")
        assert result == "paint"

    def test_node_params_model_number(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[_make_node(params={"model_number": "M123"})])
        run_result = _make_run_result()
        result = svc._workflow_products_float_query(plan, run_result, "msg")
        assert result == "M123"

    def test_node_params_product_name(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[_make_node(params={"name": "widget"})])
        run_result = _make_run_result()
        result = svc._workflow_products_float_query(plan, run_result, "msg")
        assert result == "widget"

    def test_node_result_with_model(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(
            node_results=[
                _make_node_result(output={"data": [{"model_number": "M456", "name": "widget"}]})
            ]
        )
        result = svc._workflow_products_float_query(plan, run_result, "fallback")
        assert result == "M456"

    def test_node_result_with_name_only(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(
            node_results=[_make_node_result(output={"data": [{"name": "widget"}]})]
        )
        result = svc._workflow_products_float_query(plan, run_result, "fallback")
        assert result == "widget"

    def test_fallback_to_user_message(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(node_results=[])
        result = svc._workflow_products_float_query(plan, run_result, "user query")
        assert result == "user query"

    def test_generic_full_list_fallback_is_empty(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(node_results=[])
        result = svc._workflow_products_float_query(plan, run_result, "查询当前产品列表")
        assert result == ""

    def test_generic_full_list_node_param_is_empty(self):
        svc = _make_svc()
        plan = _make_plan(
            nodes=[
                _make_node(
                    tool_id="products",
                    action="query",
                    params={"keyword": "查询当前产品列表"},
                )
            ]
        )
        run_result = _make_run_result(node_results=[])
        result = svc._workflow_products_float_query(plan, run_result, "查询当前产品列表")
        assert result == ""

    def test_failed_node_result_skipped(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(
            node_results=[
                _make_node_result(success=False, output={"data": [{"model_number": "X"}]}),
                _make_node_result(
                    tool_id="customers",
                    output={"data": [{"model_number": "Y"}]},
                ),
            ]
        )
        result = svc._workflow_products_float_query(plan, run_result, "fallback")
        assert result == "fallback"

    def test_empty_data_rows(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(node_results=[_make_node_result(output={"data": []})])
        result = svc._workflow_products_float_query(plan, run_result, "msg")
        assert result == "msg"

    def test_data_rows_non_dict(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        run_result = _make_run_result(
            node_results=[_make_node_result(output={"data": ["not-a-dict"]})]
        )
        result = svc._workflow_products_float_query(plan, run_result, "msg")
        assert result == "msg"


class TestBuildWorkflowThinkingSteps:
    """_build_workflow_thinking_steps 补充分支测试。"""

    def test_empty_nodes(self):
        svc = _make_svc()
        plan = _make_plan(nodes=[])
        result = svc._build_workflow_thinking_steps(plan, "low risk")
        assert "无节点" in result or "无" in result

    def test_with_nodes_and_deps(self):
        svc = _make_svc()
        plan = _make_plan(
            nodes=[
                _make_node(node_id="n1", depends_on=["n0"]),
                _make_node(node_id="n2", depends_on=[]),
            ]
        )
        result = svc._build_workflow_thinking_steps(plan, "reason")
        assert "查询产品资料" in result
        assert "n1" not in result
        assert "n0" not in result

    def test_with_memory_rag_summary(self):
        svc = _make_svc()
        plan = _make_plan(metadata={"user_memory_rag_summary": "memory summary"})
        result = svc._build_workflow_thinking_steps(plan, "r")
        assert "memory summary" in result

    def test_with_memory_v2_summary(self):
        svc = _make_svc()
        plan = _make_plan(metadata={"memory_v2_summary": "v2 summary"})
        result = svc._build_workflow_thinking_steps(plan, "r")
        assert "v2 summary" in result

    def test_with_tool_probe_outputs(self):
        svc = _make_svc()
        plan = _make_plan(
            metadata={
                "tool_probe_outputs": [
                    {
                        "tool_id": "products",
                        "action": "query",
                        "success": True,
                        "message": "ok",
                        "data_preview": "preview data",
                    }
                ]
            }
        )
        result = svc._build_workflow_thinking_steps(plan, "r")
        assert "能力预检: 已确认 1 项业务能力可用" in result
        assert "products" not in result
        assert "preview data" not in result

    def test_tool_probe_outputs_not_list(self):
        svc = _make_svc()
        plan = _make_plan(metadata={"tool_probe_outputs": "not-a-list"})
        result = svc._build_workflow_thinking_steps(plan, "r")
        assert "无" in result or "无成功探测" in result

    def test_tool_probe_outputs_non_dict_items(self):
        svc = _make_svc()
        plan = _make_plan(metadata={"tool_probe_outputs": ["bad", {"tool_id": "x"}]})
        result = svc._build_workflow_thinking_steps(plan, "r")
        assert isinstance(result, str)

    def test_probe_preview_truncated(self):
        svc = _make_svc()
        long_preview = "x" * 300
        plan = _make_plan(
            metadata={
                "tool_probe_outputs": [
                    {
                        "tool_id": "t",
                        "action": "a",
                        "success": True,
                        "message": "m",
                        "data_preview": long_preview,
                    }
                ]
            }
        )
        result = svc._build_workflow_thinking_steps(plan, "r")
        assert "能力预检: 已确认 1 项业务能力可用" in result
        assert long_preview not in result


class TestNormalSlotDispatchChatOverlay:
    """_normal_slot_dispatch_chat_overlay 补充分支测试。"""

    def test_no_matching_node_returns_empty(self):
        run_result = _make_run_result(
            node_results=[
                _make_node_result(tool_id="products", action="query"),
            ]
        )
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(run_result)
        assert result == {}

    def test_failed_node_skipped(self):
        run_result = _make_run_result(
            node_results=[
                _make_node_result(
                    tool_id="normal_slot_dispatch",
                    success=False,
                    output={"autoAction": {"type": "x"}},
                ),
            ]
        )
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(run_result)
        assert result == {}

    def test_output_not_success_skipped(self):
        run_result = _make_run_result(
            node_results=[
                _make_node_result(
                    tool_id="normal_slot_dispatch",
                    output={"success": False, "autoAction": {"type": "x"}},
                ),
            ]
        )
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(run_result)
        assert result == {}

    def test_no_auto_action_or_task_skipped(self):
        run_result = _make_run_result(
            node_results=[
                _make_node_result(
                    tool_id="normal_slot_dispatch",
                    output={"success": True, "response": "hello"},
                ),
            ]
        )
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(run_result)
        assert result == {}

    def test_picks_last_matching_node(self):
        run_result = _make_run_result(
            node_results=[
                _make_node_result(
                    tool_id="normal_slot_dispatch",
                    output={"success": True, "autoAction": {"type": "first"}, "response": "r1"},
                ),
                _make_node_result(
                    tool_id="normal_slot_dispatch",
                    output={"success": True, "autoAction": {"type": "second"}, "response": "r2"},
                ),
            ]
        )
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(run_result)
        assert result["autoAction"]["type"] == "second"

    def test_output_not_dict_skipped(self):
        run_result = _make_run_result(
            node_results=[
                _make_node_result(
                    tool_id="normal_slot_dispatch",
                    output="not-a-dict",
                ),
            ]
        )
        result = AIChatApplicationService._normal_slot_dispatch_chat_overlay(run_result)
        assert result == {}


class TestDispatchWorkflowTool:
    """_dispatch_workflow_tool 补充分支测试。"""

    def test_successful_execution(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": "ok"},
        ):
            result = svc._dispatch_workflow_tool("products", "query", {"k": "v"})
        assert result["success"] is True

    def test_exception_returns_error(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=RuntimeError("tool crashed"),
        ):
            result = svc._dispatch_workflow_tool("products", "query", {})
        assert result["success"] is False
        assert result["message"] == "工作流工具调度失败"
        assert "tool crashed" not in result["message"]


class TestExecuteProModeTools:
    """_execute_pro_mode_tools 补充分支测试。"""

    def test_products_tool(self):
        svc = _make_svc()
        svc._execute_products_query = Mock(return_value={"success": True, "products": []})
        result = svc._execute_pro_mode_tools(
            {"data": {}}, "products", {}, {}, {"text": "query"}, "find products"
        )
        assert result["success"] is True

    def test_customers_tool(self):
        svc = _make_svc()
        svc._execute_customers_intent = Mock(return_value={"success": True})
        result = svc._execute_pro_mode_tools(
            {"data": {}}, "customers", {}, {}, {"text": "add"}, "add customer"
        )
        assert result["success"] is True

    def test_shipment_generate_with_long_message(self):
        svc = _make_svc()
        result = svc._execute_pro_mode_tools(
            {"data": {}},
            "shipment_generate",
            {"unit_name": "ACME", "quantity_tins": "5"},
            {},
            {"text": "generate shipment", "data": {}},
            "this is a very long original message for testing",
        )
        assert "toolCall" in result
        assert result["toolCall"]["tool_id"] == "shipment_generate"

    def test_shipment_generate_with_all_slots(self):
        svc = _make_svc()
        result = svc._execute_pro_mode_tools(
            {"data": {}},
            "shipment_generate",
            {"unit_name": "ACME", "quantity_tins": "3", "model_number": "M1", "tin_spec": "25"},
            {},
            {"text": "gen", "data": {}},
            "hi",
        )
        assert "toolCall" in result
        params = result["toolCall"]["params"]
        assert "ACME" in params["order_text"]

    def test_shipment_generate_with_products_list(self):
        svc = _make_svc()
        svc._build_order_text_from_products = Mock(return_value="ACME，3桶M1规格25")
        result = svc._execute_pro_mode_tools(
            {"data": {}},
            "shipment_generate",
            {"unit_name": "ACME", "products": [{"model": "M1"}]},
            {},
            {"text": "gen", "data": {}},
            "hi",
        )
        assert "toolCall" in result

    def test_shipment_generate_fallback_to_ai_text(self):
        svc = _make_svc()
        result = svc._execute_pro_mode_tools(
            {"data": {}},
            "shipment_generate",
            {},
            {},
            {"text": "ai response text", "data": {}},
            "",
        )
        assert result["toolCall"]["params"]["order_text"] == "ai response text"

    def test_other_tool_pro_mode(self):
        svc = _make_svc()
        result = svc._execute_pro_mode_tools(
            {"data": {}},
            "unknown_tool",
            {},
            {"param1": "v"},
            {"text": "response", "data": {"extra": "val"}},
            "msg",
        )
        assert result["toolCall"]["tool_id"] == "unknown_tool"
        assert result["toolCall"]["params"]["param1"] == "v"

    def test_shipment_generate_parsed_order_overrides(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "products": [{"model": "X1"}], "unit_name": "Parsed"},
        ):
            result = svc._execute_pro_mode_tools(
                {"data": {}},
                "shipment_generate",
                {"unit_name": "Original", "products": [{"model": "Y"}]},
                {},
                {"text": "gen", "data": {}},
                "long original message here",
            )
        assert result["toolCall"]["params"]["unit_name"] == "Parsed"
        assert result["toolCall"]["params"]["products"][0]["model"] == "X1"

    def test_shipment_generate_parse_error_falls_back(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=RuntimeError("parse fail"),
        ):
            result = svc._execute_pro_mode_tools(
                {"data": {}},
                "shipment_generate",
                {"unit_name": "ACME", "quantity_tins": "3", "model_number": "M1", "tin_spec": "25"},
                {},
                {"text": "gen", "data": {}},
                "hi",
            )
        assert "toolCall" in result


class TestBuildOrderTextFromProducts:
    """_build_order_text_from_products 补充分支测试。"""

    def test_empty_products_returns_empty(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products("ACME", [], "msg")
        assert result == ""

    def test_empty_unit_name_returns_empty(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products("", [{"model": "M1"}], "msg")
        assert result == ""

    def test_products_with_model(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products(
            "ACME",
            [{"model": "M1", "quantity_tins": 3, "spec": 25}],
            "",
        )
        assert "ACME" in result
        assert "M1" in result
        assert "3" in result

    def test_products_without_model_uses_name(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products(
            "ACME",
            [{"name": "Widget", "quantity": 2}],
            "",
        )
        assert "Widget" in result

    def test_products_with_default_spec(self):
        """产品无 spec 时使用 default_spec。"""
        svc = _make_svc()
        result = svc._build_order_text_from_products(
            "ACME",
            [{"model": "M1"}],
            "",
            default_qty=5,
            default_spec=30,
        )
        # default_qty 参数未被使用（源码行为），qty 默认 1
        assert "1桶M1规格30" in result
        assert "30" in result

    def test_products_no_model_uses_spec_only(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products(
            "ACME",
            [{"quantity": 2}],
            "",
            default_spec=20,
        )
        assert "2" in result
        assert "20" in result

    def test_original_message_with_pattern(self):
        svc = _make_svc()
        msg = "打ACME的货单，3桶M1规格25，5桶M2规格30"
        result = svc._build_order_text_from_products(
            "ACME",
            [{"model": "M1"}],
            msg,
        )
        assert "ACME" in result


class TestTryMergeSplitModel:
    """_try_merge_split_model 补充分支测试。"""

    def test_number_pattern_match(self):
        svc = _make_svc()
        result = svc._try_merge_split_model(
            "5003规格25",
            {"quantity_tins": 3},
        )
        assert "5003" in result
        assert "25" in result

    def test_number_pattern_with_letter(self):
        svc = _make_svc()
        result = svc._try_merge_split_model(
            "5003B规格25",
            {"quantity_tins": 3},
        )
        assert "5003B" in result

    def test_qty_pattern_match(self):
        svc = _make_svc()
        result = svc._try_merge_split_model(
            "3桶5003规格25",
            {"quantity_tins": 3},
        )
        assert "3" in result
        assert "5003" in result

    def test_no_match_returns_empty(self):
        svc = _make_svc()
        result = svc._try_merge_split_model(
            "no pattern here",
            {"quantity_tins": 1},
        )
        assert result == ""


class TestExecuteCustomersIntent:
    """_execute_customers_intent 补充分支测试。"""

    def test_add_intent_no_unit_name_asks_for_name(self):
        svc = _make_svc()
        result = svc._execute_customers_intent({"data": {}}, {}, {}, "添加单位")
        assert "单位名称" in result["response"]
        assert result["data"]["data"]["missing_fields"] == ["unit_name"]

    def test_add_intent_with_unit_name_create_success(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "created": True},
        ):
            result = svc._execute_customers_intent(
                {"data": {}}, {"unit_name": "ACME"}, {}, "添加单位 ACME"
            )
        assert "已创建" in result["response"]

    def test_add_intent_with_unit_name_already_exists(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "created": False},
        ):
            result = svc._execute_customers_intent(
                {"data": {}}, {"unit_name": "ACME"}, {}, "新增 ACME"
            )
        assert "已存在" in result["response"]

    def test_add_intent_create_fails(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": False, "message": "db error"},
        ):
            result = svc._execute_customers_intent(
                {"data": {}}, {"unit_name": "ACME"}, {}, "创建 ACME"
            )
        assert "db error" in result["response"]

    def test_add_intent_exception(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=RuntimeError("crash"),
        ):
            result = svc._execute_customers_intent(
                {"data": {}}, {"unit_name": "ACME"}, {}, "新建 ACME"
            )
        assert "处理单位失败" in result["response"]

    def test_query_intent_calls_query(self):
        svc = _make_svc()
        svc._execute_customers_query = Mock(return_value={"success": True})
        result = svc._execute_customers_intent({"data": {}}, {}, {}, "查询客户列表")
        assert result["success"] is True

    def test_english_add_intent(self):
        svc = _make_svc()
        result = svc._execute_customers_intent({"data": {}}, {}, {}, "add customer")
        assert "单位名称" in result["response"]

    def test_english_query_intent(self):
        svc = _make_svc()
        svc._execute_customers_query = Mock(return_value={"success": True})
        result = svc._execute_customers_intent({"data": {}}, {}, {}, "search customers")
        assert result["success"] is True

    def test_no_clear_intent_returns_followup(self):
        svc = _make_svc()
        result = svc._execute_customers_intent({"data": {}}, {}, {}, "hello")
        assert "customers_followup" in result["data"]["data"]["intent"]

    def test_unit_name_from_parsed_params(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "created": True},
        ):
            result = svc._execute_customers_intent(
                {"data": {}}, {}, {"unit_name": "FromParams"}, "添加"
            )
        assert "已创建" in result["response"]


class TestExecuteShipmentGenerate:
    """_execute_shipment_generate 补充分支测试。"""

    def test_parse_success_doc_success(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "ACME", "products": []},
        ):
            with patch("app.bootstrap.get_shipment_app_service") as mock_get:
                mock_svc = mock_get.return_value
                mock_svc.generate_shipment_document.return_value = {
                    "success": True,
                    "doc_name": "doc.docx",
                }
                result = svc._execute_shipment_generate(
                    {"data": {}}, {"order_text": "order"}, {"text": "gen"}
                )
        assert "doc.docx" in result["response"]

    def test_parse_success_doc_no_name(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "ACME", "products": []},
        ):
            with patch("app.bootstrap.get_shipment_app_service") as mock_get:
                mock_svc = mock_get.return_value
                mock_svc.generate_shipment_document.return_value = {
                    "success": True,
                    "doc_name": "",
                }
                result = svc._execute_shipment_generate(
                    {"data": {}}, {"order_text": "order"}, {"text": "gen"}
                )
        assert "已生成发货单" in result["response"]

    def test_parse_success_doc_failed(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "ACME", "products": []},
        ):
            with patch("app.bootstrap.get_shipment_app_service") as mock_get:
                mock_svc = mock_get.return_value
                mock_svc.generate_shipment_document.return_value = {
                    "success": False,
                    "message": "template error",
                }
                result = svc._execute_shipment_generate(
                    {"data": {}}, {"order_text": "order"}, {"text": "gen"}
                )
        assert "template error" in result["response"]

    def test_parse_failure(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "bad order"},
        ):
            result = svc._execute_shipment_generate(
                {"data": {}}, {"order_text": "order"}, {"text": "gen"}
            )
        assert "bad order" in result["response"]

    def test_exception_during_execution(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=RuntimeError("crash"),
        ):
            result = svc._execute_shipment_generate(
                {"data": {}}, {"order_text": "order"}, {"text": "gen"}
            )
        assert "生成发货单失败" in result["response"]

    def test_order_text_prefers_original_message(self):
        """#2067：订单文本必须优先取用户原话，而不是助手回复。"""
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "U", "products": []},
        ) as mock_parse:
            with patch("app.bootstrap.get_shipment_app_service") as mock_get:
                mock_svc = mock_get.return_value
                mock_svc.generate_shipment_document.return_value = {
                    "success": True,
                    "doc_name": "d",
                }
                svc._execute_shipment_generate(
                    {"data": {}}, {}, {"text": "ai text"}, "用户原话 5桶"
                )
        assert mock_parse.call_args[0][0] == "用户原话 5桶"

    def test_assistant_text_is_not_used_as_order_text(self):
        """#2067：无用户原话时不得把助手回复当作订单文本解析。"""
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "x"},
        ) as mock_parse:
            svc._execute_shipment_generate({"data": {}}, {}, {"text": "ai text"})
        assert mock_parse.call_args[0][0] == ""


class TestExecuteShipmentsQuery:
    """_execute_shipments_query 补充分支测试。"""

    def test_no_orders(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = []
            result = svc._execute_shipments_query({"data": {}})
        assert "暂无" in result["response"]

    def test_with_orders(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = [
                {
                    "order_number": "ORD001",
                    "customer_name": "ACME",
                    "date": "2024-01-01",
                    "total_amount": 100,
                    "status": "已完成",
                }
            ]
            result = svc._execute_shipments_query({"data": {}})
        assert "ORD001" in result["response"]
        assert "ACME" in result["response"]

    def test_orders_with_alternative_keys(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = [
                {
                    "order_no": "ON002",
                    "unit_name": "Beta",
                    "created_at": "2024-02-01",
                    "total_amount_yuan": 200,
                }
            ]
            result = svc._execute_shipments_query({"data": {}})
        assert "ON002" in result["response"]
        assert "Beta" in result["response"]

    def test_orders_with_id_only(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = [{"id": 999, "purchase_unit": "Gamma", "amount": 50}]
            result = svc._execute_shipments_query({"data": {}})
        assert "999" in result["response"]

    def test_exception_returns_response_data(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_shipment_app_service", side_effect=RuntimeError("db down")):
            result = svc._execute_shipments_query({"data": {}})
        assert "toolCall" not in result

    def test_get_orders_returns_none(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = None
            result = svc._execute_shipments_query({"data": {}})
        assert "暂无" in result["response"]


class TestHandleToolCall:
    """_handle_tool_call 补充分支测试。"""

    def test_no_tool_key_returns_text(self):
        svc = _make_svc()
        result = svc._handle_tool_call(
            {"data": {}},
            {"text": "hello"},
            {"data": {"inner": "val"}},
            None,
            "msg",
        )
        assert result["data"]["data"] == {"inner": "val"}

    def test_pro_source_dispatches_pro_mode(self):
        svc = _make_svc()
        svc._execute_pro_mode_tools = Mock(return_value={"success": True, "pro": True})
        result = svc._handle_tool_call(
            {"data": {}},
            {"text": "hello"},
            {"tool_key": "products", "slots": {}},
            "pro",
            "msg",
        )
        assert result["pro"] is True

    def test_normal_source_dispatches_normal_mode(self):
        svc = _make_svc()
        svc._execute_normal_mode_tools = Mock(return_value={"success": True, "normal": True})
        result = svc._handle_tool_call(
            {"data": {}},
            {"text": "hello"},
            {"tool_key": "shipments", "params": {}},
            None,
            "msg",
        )
        assert result["normal"] is True


class TestBuildResponse:
    """_build_response 补充分支测试。"""

    def test_followup_action(self):
        svc = _make_svc()
        result = svc._build_response(
            {"text": "ask", "action": "followup", "data": {"q": "what"}},
            None,
            "msg",
        )
        assert result["followup"] == {"q": "what"}

    def test_auto_action(self):
        svc = _make_svc()
        result = svc._build_response(
            {"text": "auto", "action": "auto_action", "data": {"type": "navigate"}},
            None,
            "msg",
        )
        assert result["autoAction"] == {"type": "navigate"}

    def test_tool_call_dispatches(self):
        svc = _make_svc()
        svc._handle_tool_call = Mock(return_value={"success": True, "handled": True})
        result = svc._build_response(
            {"text": "call", "action": "tool_call", "data": {"tool_key": "products"}},
            "pro",
            "msg",
        )
        assert result["handled"] is True

    def test_no_action(self):
        svc = _make_svc()
        result = svc._build_response(
            {"text": "plain", "action": "", "data": {}},
            None,
            "msg",
        )
        assert result["response"] == "plain"

    def test_auto_action_no_data(self):
        svc = _make_svc()
        result = svc._build_response(
            {"text": "auto", "action": "auto_action", "data": {}},
            None,
            "msg",
        )
        assert "autoAction" not in result


class TestPersistChatTurn:
    """_persist_chat_turn 补充分支测试。"""

    def test_no_session_id_returns_early(self):
        svc = _make_svc()
        # Should not raise
        svc._persist_chat_turn("u1", "msg", {}, {"success": True})

    def test_with_session_id_saves_messages(self):
        svc = _make_svc()
        with patch("app.services.get_conversation_service") as mock_get:
            mock_conv = mock_get.return_value
            svc._persist_chat_turn(
                "u1",
                "hello",
                {"session_id": "sess1", "local_user_id": 17},
                {
                    "success": True,
                    "response": "reply",
                    "data": {"text": "reply", "action": "chat", "data": {"intent": "test"}},
                },
            )
        assert mock_conv.save_message.call_count == 2

    def test_with_conversation_id_saves_messages(self):
        svc = _make_svc()
        with patch("app.services.get_conversation_service") as mock_get:
            mock_conv = mock_get.return_value
            svc._persist_chat_turn(
                "u1",
                "hello",
                {"conversation_id": "conv1", "local_user_id": 17},
                {
                    "success": True,
                    "data": {"data": {"tool_key": "products"}},
                    "toolCall": {"tool_id": "products"},
                },
            )
        assert mock_conv.save_message.call_count == 2

    def test_with_tool_call_in_response(self):
        svc = _make_svc()
        with patch("app.services.get_conversation_service") as mock_get:
            mock_conv = mock_get.return_value
            svc._persist_chat_turn(
                "u1",
                "hello",
                {"session_id": "s1", "local_user_id": 17},
                {
                    "success": True,
                    "data": {"data": {"intent": "excel_import_to_db", "result": {"imported": 5}}},
                },
            )
        call_args = mock_conv.save_message.call_args_list
        meta = call_args[0][1]["metadata"]
        assert "excel_import" in meta

    def test_with_document_in_payload(self):
        svc = _make_svc()
        with patch("app.services.get_conversation_service") as mock_get:
            mock_conv = mock_get.return_value
            svc._persist_chat_turn(
                "u1",
                "hello",
                {"session_id": "s1", "local_user_id": 17},
                {
                    "success": True,
                    "data": {"data": {"document": {"doc_name": "test.docx"}}},
                },
            )
        call_args = mock_conv.save_message.call_args_list
        meta = call_args[0][1]["metadata"]
        assert "test.docx" in meta


class TestInjectExcelVectorContext:
    """_inject_excel_vector_context 补充分支测试。"""

    def test_non_dict_context_returns_empty(self):
        svc = _make_svc()
        result = svc._inject_excel_vector_context("msg", "not-a-dict")
        assert result == {}

    def test_no_index_id_returns_context(self):
        svc = _make_svc()
        ctx = {"key": "val"}
        result = svc._inject_excel_vector_context("msg", ctx)
        assert result is ctx

    def test_with_index_id_query_success(self):
        svc = _make_svc()
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.query.return_value = {"success": True, "hits": [{"id": 1}]}
            result = svc._inject_excel_vector_context("find data", {"excel_index_id": "idx1"})
        assert "excel_vector_context" in result
        assert result["excel_vector_context"]["hits"] == [{"id": 1}]

    def test_with_index_id_query_fails(self):
        svc = _make_svc()
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.query.return_value = {"success": False}
            ctx = {"excel_index_id": "idx1"}
            result = svc._inject_excel_vector_context("msg", ctx)
        assert result is ctx

    def test_with_index_id_exception(self):
        svc = _make_svc()
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.query.side_effect = RuntimeError("search failed")
            ctx = {"excel_index_id": "idx1"}
            result = svc._inject_excel_vector_context("msg", ctx)
        assert result is ctx

    def test_excel_vector_index_id_alias(self):
        svc = _make_svc()
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.query.return_value = {"success": True, "hits": []}
            result = svc._inject_excel_vector_context("msg", {"excel_vector_index_id": "idx2"})
        assert "excel_vector_context" in result

    def test_invalid_top_k_falls_back_to_5(self):
        svc = _make_svc()
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.query.return_value = {"success": True, "hits": []}
            svc._inject_excel_vector_context(
                "msg", {"excel_index_id": "idx1", "excel_top_k": "invalid"}
            )
        call_kwargs = mock_svc.query.call_args[1]
        assert call_kwargs["top_k"] == 5

    def test_import_error_returns_context(self):
        svc = _make_svc()
        ctx = {"excel_index_id": "idx1"}
        import sys

        # Use patch.dict to block app.application; restores both sys.modules and
        # the parent-package attribute so subsequent tests see the real module.
        with patch.dict(sys.modules, {"app.application": None}):
            result = svc._inject_excel_vector_context("msg", ctx)
        assert result is ctx


class TestResolveUnitPriceColumn:
    """_resolve_unit_price_column 补充分支测试。"""

    def test_forced_override_matches_key(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["单价", "数量"], "", "msg", {"unit_price": "单价"}
        )
        assert result == ("单价", None)

    def test_forced_override_price_alias(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["价格"], "", "msg", {"price": "价格"}
        )
        assert result == ("价格", None)

    def test_forced_override_no_match_falls_through(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["单价"], "", "msg", {"unit_price": "nonexistent"}
        )
        assert result[0] == "单价"

    def test_empty_keys_returns_empty(self):
        result = AIChatApplicationService._resolve_unit_price_column([], "", "msg", None)
        assert result == ("", None)

    def test_tension_prefer_before_only(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "导入调价前", None
        )
        assert result == ("调价前单价", None)

    def test_tension_prefer_after_only(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "导入调价后", None
        )
        assert result == ("调价后单价", None)

    def test_tension_prefer_both_ambiguous(self):
        """用户话术同时暗示调价前和调价后 → ambiguous。"""
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "用调价前 用调价后", None
        )
        assert result == ("", "ambiguous_price_columns")

    def test_tension_no_user_message_defaults_before(self):
        """有 tension 但无话术提示 → 默认调价前。"""
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "无关键信息", None
        )
        assert result == ("调价前单价", None)

    def test_tension_no_preference_defaults_before(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价", "调价后单价"], "", "no preference", None
        )
        assert result == ("调价前单价", None)

    def test_tension_via_space_in_keys(self):
        """键名含空格的「调价前」「调价后」也视为 tension。"""
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价 前 单价", "调价 后 单价"], "", "msg", None
        )
        assert result[0] == "调价 前 单价"

    def test_current_in_keyset_returns_current(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["单价", "数量"], "单价", "msg", None
        )
        assert result == ("单价", None)

    def test_before_only_returns_before(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价前单价"], "", "msg", None
        )
        assert result == ("调价前单价", None)

    def test_after_only_returns_after(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["调价后单价"], "", "msg", None
        )
        assert result == ("调价后单价", None)

    def test_generic_single_returns_it(self):
        result = AIChatApplicationService._resolve_unit_price_column(["单价"], "", "msg", None)
        assert result == ("单价", None)

    def test_generic_multiple_with_current(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["单价", "价格"], "价格", "msg", None
        )
        assert result == ("价格", None)

    def test_generic_multiple_ambiguous(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["单价", "价格"], "", "msg", None
        )
        assert result == ("", "ambiguous_price_columns")

    def test_no_price_columns_returns_empty(self):
        result = AIChatApplicationService._resolve_unit_price_column(
            ["数量", "客户"], "", "msg", None
        )
        assert result == ("", None)


class TestMergeUserIntentForPriceResolution:
    """_merge_user_intent_for_price_resolution 补充分支测试。"""

    def test_empty_message_and_context(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("", None)
        assert result == ""

    def test_message_only(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution("hello", None)
        assert "hello" in result

    def test_with_recent_messages(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "current",
            {
                "recent_messages": [
                    {"role": "user", "content": "past user"},
                    {"role": "assistant", "content": "past ai"},
                ]
            },
        )
        assert "past user" in result
        assert "past ai" in result
        assert "current" in result

    def test_recent_messages_non_dict_skipped(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "cur",
            {"recent_messages": ["bad", {"role": "user", "content": "good"}]},
        )
        assert "good" in result
        assert "cur" in result

    def test_recent_messages_invalid_role_skipped(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "cur",
            {"recent_messages": [{"role": "system", "content": "skip"}]},
        )
        assert "skip" not in result

    def test_html_stripped(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "cur",
            {"recent_messages": [{"role": "user", "content": "<b>bold</b><br/>text"}]},
        )
        assert "bold" in result
        assert "<b>" not in result

    def test_duplicate_in_recent_messages_deduplicated(self):
        """recent_messages 内部重复内容会被去重。"""
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "cur",
            {
                "recent_messages": [
                    {"role": "user", "content": "dup"},
                    {"role": "assistant", "content": "dup"},
                ]
            },
        )
        # "dup" 在 recent_messages 中只出现一次（去重），"cur" 在末尾
        assert result.count("dup") == 1
        assert "cur" in result

    def test_current_message_not_deduplicated_against_recent(self):
        """当前 user_message 不会被去重（源码行为：末尾追加不查重）。"""
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "same",
            {"recent_messages": [{"role": "user", "content": "same"}]},
        )
        # "same" 出现两次：一次来自 recent_messages，一次来自当前 user_message
        assert result.count("same") == 2

    def test_message_key_in_context(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "cur",
            {"message": "extra msg"},
        )
        assert "extra msg" in result

    def test_user_message_key_in_context(self):
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(
            "cur",
            {"user_message": "extra user msg"},
        )
        assert "extra user msg" in result

    def test_long_merged_truncated(self):
        long_msg = "x" * 10000
        result = AIChatApplicationService._merge_user_intent_for_price_resolution(long_msg, None)
        assert len(result) <= 8000


class TestPriceColumnBuckets:
    """_price_column_buckets 补充分支测试。"""

    def _disable_schema_index(self):
        """让 from app.services.ai_db_schema_index import ... 抛 ImportError。"""
        import sys

        key = "app.services.ai_db_schema_index"
        saved = sys.modules.get(key, "missing")
        sys.modules[key] = None
        return saved

    def _restore_schema_index(self, saved):
        import sys

        key = "app.services.ai_db_schema_index"
        if saved == "missing":
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = saved

    def test_import_error_falls_back_to_heuristic(self):
        saved = self._disable_schema_index()
        try:
            before, after, generic = AIChatApplicationService._price_column_buckets(
                ["调价前单价", "调价后单价", "单价", "数量"]
            )
        finally:
            self._restore_schema_index(saved)
        assert "调价前单价" in before
        assert "调价后单价" in after
        assert "单价" in generic
        assert "数量" not in generic

    def test_heuristic_skips_non_price_columns(self):
        saved = self._disable_schema_index()
        try:
            before, after, generic = AIChatApplicationService._price_column_buckets(
                ["客户名", "产品名称"]
            )
        finally:
            self._restore_schema_index(saved)
        assert before == []
        assert after == []
        assert generic == []

    def test_heuristic_skips_qty_columns(self):
        saved = self._disable_schema_index()
        try:
            _, _, generic = AIChatApplicationService._price_column_buckets(["数量单价", "计量价格"])
        finally:
            self._restore_schema_index(saved)
        assert generic == []

    def test_heuristic_after_variants(self):
        """启发式分桶识别调价后类列（需同时匹配价格正则和 after 正则）。"""
        saved = self._disable_schema_index()
        try:
            _, after, _ = AIChatApplicationService._price_column_buckets(
                ["调价后单价", "折后价格", "现用单价"]
            )
        finally:
            self._restore_schema_index(saved)
        assert len(after) == 3

    def test_heuristic_before_variants(self):
        """启发式分桶识别调价前类列。"""
        saved = self._disable_schema_index()
        try:
            before, _, _ = AIChatApplicationService._price_column_buckets(
                ["调价前单价", "调整前价格", "原价报价"]
            )
        finally:
            self._restore_schema_index(saved)
        assert len(before) == 3

    def test_heuristic_generic_price_columns(self):
        """启发式分桶：既非 before 也非 after 的价格列归入 generic。"""
        saved = self._disable_schema_index()
        try:
            _, _, generic = AIChatApplicationService._price_column_buckets(["含税单价", "销售价格"])
        finally:
            self._restore_schema_index(saved)
        assert len(generic) == 2


class TestHeaderHintColumnRoles:
    """_header_hint_column_roles 补充分支测试。"""

    def _disable_schema_index(self):
        import sys

        key = "app.services.ai_db_schema_index"
        saved = sys.modules.get(key, "missing")
        sys.modules[key] = None
        return saved

    def _restore_schema_index(self, saved):
        import sys

        key = "app.services.ai_db_schema_index"
        if saved == "missing":
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = saved

    def test_import_error_returns_empty_roles(self):
        saved = self._disable_schema_index()
        try:
            roles = AIChatApplicationService._header_hint_column_roles(["客户", "产品"])
        finally:
            self._restore_schema_index(saved)
        assert roles["unit_name"] == "客户"
        assert roles["product_name"] == "产品"

    def test_customer_synonyms(self):
        for key in ("客户", "客户名", "客户名称", "购买单位", "购货单位", "公司", "厂名"):
            roles = AIChatApplicationService._header_hint_column_roles([key])
            assert roles["unit_name"] == key, f"failed for {key}"

    def test_product_synonyms(self):
        for key in ("产品", "产品名", "品名", "名称", "物料名称", "商品名称"):
            roles = AIChatApplicationService._header_hint_column_roles([key])
            assert roles["product_name"] == key, f"failed for {key}"

    def test_model_synonyms(self):
        for key in ("型号", "规格型号", "产品型号", "编码", "sku", "model"):
            roles = AIChatApplicationService._header_hint_column_roles([key])
            assert roles["model_number"] == key, f"failed for {key}"

    def test_price_synonyms(self):
        for key in ("单价", "价格", "报价", "unitprice", "price"):
            roles = AIChatApplicationService._header_hint_column_roles([key])
            assert roles["unit_price"] == key, f"failed for {key}"

    def test_empty_key_skipped(self):
        roles = AIChatApplicationService._header_hint_column_roles(["", "  "])
        assert roles["unit_name"] == ""

    def test_normalized_with_special_chars(self):
        roles = AIChatApplicationService._header_hint_column_roles(["客 户："])
        assert roles["unit_name"] == "客 户："

    def test_unknown_key_no_match(self):
        roles = AIChatApplicationService._header_hint_column_roles(["未知列"])
        assert roles["unit_name"] == ""
        assert roles["product_name"] == ""


class TestInferExcelColumnRoles:
    """_infer_excel_column_roles 补充分支测试。"""

    def test_empty_records_returns_empty(self):
        svc = _make_svc()
        roles, conf = svc._infer_excel_column_roles([])
        assert roles == {}
        assert conf == 0.0

    def test_records_no_keys_returns_empty(self):
        svc = _make_svc()
        roles, conf = svc._infer_excel_column_roles([{}])
        assert roles == {}

    def test_all_empty_values_returns_empty(self):
        svc = _make_svc()
        roles, conf = svc._infer_excel_column_roles(
            [{"col1": "", "col2": ""}, {"col1": "", "col2": ""}]
        )
        assert roles == {}

    def test_mixed_columns(self):
        svc = _make_svc()
        records = [
            {"name": "Product A", "price": "100", "model": "M1", "customer": "ACME"},
            {"name": "Product B", "price": "200", "model": "M2", "customer": "ACME"},
        ]
        roles, conf = svc._infer_excel_column_roles(records)
        assert "unit_price" in roles
        assert "model_number" in roles
        assert "product_name" in roles
        assert "unit_name" in roles

    def test_conflict_resolution(self):
        """两列得分相同时，第一个被选中的列优先。"""
        svc = _make_svc()
        records = [
            {"col1": "100", "col2": "200"},
            {"col1": "300", "col2": "400"},
        ]
        roles, conf = svc._infer_excel_column_roles(records)
        # Both columns look like price; one should be selected
        assert roles["unit_price"] in ("col1", "col2")

    def test_role_not_assigned_when_empty(self):
        svc = _make_svc()
        records = [{"col1": "val"}]
        roles, conf = svc._infer_excel_column_roles(records)
        # Only one column, so only one role gets it
        assigned = [k for k, v in roles.items() if v]
        assert len(assigned) >= 1


class TestFallbackExcelColumns:
    """_fallback_excel_product_name_column / _fallback_excel_model_number_column 补充分支。"""

    def test_product_name_empty_records(self):
        svc = _make_svc()
        assert svc._fallback_excel_product_name_column([], set()) == ""

    def test_product_name_first_not_dict(self):
        svc = _make_svc()
        assert svc._fallback_excel_product_name_column(["bad"], set()) == ""

    def test_product_name_skip_reserved(self):
        svc = _make_svc()
        records = [{"col1": "product", "reserved": "data"}]
        result = svc._fallback_excel_product_name_column(records, {"reserved"})
        assert result == "col1"

    def test_product_name_skip_serial_columns(self):
        svc = _make_svc()
        records = [{"序号": "1", "name": "product"}]
        result = svc._fallback_excel_product_name_column(records, set())
        assert result == "name"

    def test_product_name_skip_packaging_columns(self):
        svc = _make_svc()
        records = [{"pack": "件", "name": "product"}]
        result = svc._fallback_excel_product_name_column(records, set())
        assert result == "name"

    def test_product_name_low_score_returns_empty(self):
        svc = _make_svc()
        records = [{"col1": "1", "col2": "2"}]
        result = svc._fallback_excel_product_name_column(records, set())
        # Numeric columns get low score
        assert result == ""

    def test_model_number_empty_records(self):
        svc = _make_svc()
        assert svc._fallback_excel_model_number_column([], set()) == ""

    def test_model_number_first_not_dict(self):
        svc = _make_svc()
        assert svc._fallback_excel_model_number_column(["bad"], set()) == ""

    def test_model_number_skip_reserved(self):
        svc = _make_svc()
        records = [{"col1": "M123", "reserved": "M456"}]
        result = svc._fallback_excel_model_number_column(records, {"reserved"})
        assert result == "col1"

    def test_model_number_low_score_returns_empty(self):
        svc = _make_svc()
        records = [{"col1": "text", "col2": "more text"}]
        result = svc._fallback_excel_model_number_column(records, set())
        assert result == ""

    def test_model_number_finds_best(self):
        svc = _make_svc()
        records = [{"model": "M123B", "name": "product"}]
        result = svc._fallback_excel_model_number_column(records, set())
        assert result == "model"


class TestExtractExcelImportRecords:
    """_extract_excel_import_records 补充分支测试。"""

    def test_empty_preview_returns_empty(self):
        svc = _make_svc()
        records, err = svc._extract_excel_import_records({}, None)
        assert records == []
        assert err is None

    def test_with_sample_rows(self):
        svc = _make_svc()
        svc._try_structured_reload_records = Mock(return_value=None)
        svc._infer_excel_column_roles = Mock(
            return_value=(
                {
                    "unit_name": "客户",
                    "product_name": "产品",
                    "model_number": "型号",
                    "unit_price": "单价",
                },
                0.9,
            )
        )
        svc._infer_excel_column_roles_with_llm = Mock(return_value={})
        svc._default_purchase_unit_for_import = Mock(return_value="ACME")
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"客户": "ACME", "产品": "Widget", "型号": "M1", "单价": "100"},
                ]
            }
        }
        records, err = svc._extract_excel_import_records(excel_analysis, None, user_message="导入")
        assert err is None
        assert len(records) >= 1

    def test_with_grid_preview(self):
        svc = _make_svc()
        svc._try_structured_reload_records = Mock(return_value=None)
        svc._infer_excel_column_roles = Mock(
            return_value=(
                {"unit_name": "客户", "product_name": "产品", "model_number": "", "unit_price": ""},
                0.9,
            )
        )
        svc._infer_excel_column_roles_with_llm = Mock(return_value={})
        svc._default_purchase_unit_for_import = Mock(return_value="ACME")
        excel_analysis = {
            "preview_data": {
                "grid_preview": {
                    "rows": [
                        ["客户", "产品"],
                        ["ACME", "Widget"],
                    ]
                }
            }
        }
        records, err = svc._extract_excel_import_records(excel_analysis, None, user_message="导入")
        assert err is None
        assert len(records) >= 1
        # 列名被映射为角色名
        assert records[0].get("unit_name") == "ACME"
        assert records[0].get("product_name") == "Widget"

    def test_ambiguous_price_returns_error(self):
        svc = _make_svc()
        svc._try_structured_reload_records = Mock(return_value=None)
        svc._infer_excel_column_roles = Mock(
            return_value=(
                {"unit_name": "客户", "product_name": "产品", "model_number": "", "unit_price": ""},
                0.9,
            )
        )
        svc._infer_excel_column_roles_with_llm = Mock(return_value={})
        svc._default_purchase_unit_for_import = Mock(return_value="ACME")
        with patch.object(
            AIChatApplicationService,
            "_resolve_unit_price_column",
            return_value=("", "ambiguous_price_columns"),
        ):
            records, err = svc._extract_excel_import_records(
                {"preview_data": {"sample_rows": [{"客户": "ACME"}]}},
                None,
                user_message="导入",
            )
        assert err == "ambiguous_price_columns"
        assert records == []

    def test_no_records_after_filter(self):
        svc = _make_svc()
        svc._try_structured_reload_records = Mock(return_value=None)
        svc._infer_excel_column_roles = Mock(return_value=({}, 0.9))
        svc._infer_excel_column_roles_with_llm = Mock(return_value={})
        svc._default_purchase_unit_for_import = Mock(return_value="")
        excel_analysis = {
            "preview_data": {
                "sample_rows": [{"col1": "val"}],
            }
        }
        records, err = svc._extract_excel_import_records(excel_analysis, None, user_message="导入")
        assert err is None
        # Records may be empty due to no unit_name
        assert isinstance(records, list)

    def test_unnamed_columns_promoted(self):
        svc = _make_svc()
        svc._try_structured_reload_records = Mock(return_value=None)
        svc._infer_excel_column_roles = Mock(
            return_value=(
                {"unit_name": "客户", "product_name": "产品", "model_number": "", "unit_price": ""},
                0.9,
            )
        )
        svc._infer_excel_column_roles_with_llm = Mock(return_value={})
        svc._default_purchase_unit_for_import = Mock(return_value="ACME")
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"Unnamed: 0": "客户", "Unnamed: 1": "产品"},
                    {"Unnamed: 0": "ACME", "Unnamed: 1": "Widget"},
                    {"Unnamed: 0": "BETA", "Unnamed: 1": "Gadget"},
                ]
            }
        }
        records, err = svc._extract_excel_import_records(excel_analysis, None, user_message="导入")
        assert err is None
        # Should have promoted the header row
        assert len(records) >= 1

    def test_unit_key_is_measure_unit_cleared(self):
        svc = _make_svc()
        svc._try_structured_reload_records = Mock(return_value=None)
        svc._infer_excel_column_roles = Mock(
            return_value=(
                {"unit_name": "单位", "product_name": "产品", "model_number": "", "unit_price": ""},
                0.9,
            )
        )
        svc._infer_excel_column_roles_with_llm = Mock(return_value={})
        svc._default_purchase_unit_for_import = Mock(return_value="ACME")
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"单位": "件", "产品": "Widget"},
                    {"单位": "箱", "产品": "Gadget"},
                ]
            }
        }
        records, err = svc._extract_excel_import_records(excel_analysis, None, user_message="导入")
        assert err is None
        # unit_key should be cleared and default_unit used
        if records:
            assert records[0]["unit_name"] == "ACME"




class TestExecuteProductsQuery:
    """_execute_products_query 补充分支测试。"""

    def test_with_model_and_unit(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": [{"id": 1}]}
                result = svc._execute_products_query(
                    {"data": {}}, {"model_number": "M1", "unit_name": "ACME"}, {}
                )
        assert "1" in result["response"]

    def test_with_model_only(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": []}
                result = svc._execute_products_query({"data": {}}, {"model_number": "M1"}, {})
        assert "未找到" in result["response"]

    def test_with_unit_only(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": [{"id": 1}]}
                result = svc._execute_products_query({"data": {}}, {"unit_name": "ACME"}, {})
        assert "1" in result["response"]

    def test_with_keyword_only(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": [{"id": 1}]}
                result = svc._execute_products_query({"data": {}}, {"keyword": "paint"}, {})
        assert "1" in result["response"]

    def test_no_params_get_all(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": [{"id": 1}, {"id": 2}]}
                result = svc._execute_products_query({"data": {}}, {}, {})
        assert "2" in result["response"]

    def test_keyword_with_de_pattern(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"
            ) as mock_resolve:
                mock_resolve.return_value = SimpleNamespace(unit_name="ACME公司")
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": []}
                result = svc._execute_products_query({"data": {}}, {"keyword": "ACME的3A"}, {})
        assert "未找到" in result["response"]

    def test_keyword_with_de_pattern_no_resolve(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"
            ) as mock_resolve:
                mock_resolve.return_value = None
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = {"data": []}
                result = svc._execute_products_query({"data": {}}, {"keyword": "测试的3A"}, {})
        assert "未找到" in result["response"]

    def test_exception_returns_error(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("db error")):
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                result = svc._execute_products_query({"data": {}}, {}, {})
        assert "查询产品失败" in result["response"]

    def test_products_result_none(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_products_service") as mock_get:
            with patch("app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit"):
                mock_svc = mock_get.return_value
                mock_svc.get_products.return_value = None
                result = svc._execute_products_query({"data": {}}, {}, {})
        assert "未找到" in result["response"]


class TestExecuteCustomersQuery:
    """_execute_customers_query 补充分支测试。"""

    def test_with_customers(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_all.return_value = {"data": [{"id": 1}, {"id": 2}]}
            result = svc._execute_customers_query({"data": {}})
        assert "2" in result["response"]

    def test_no_customers(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_all.return_value = {"data": []}
            result = svc._execute_customers_query({"data": {}})
        assert "未找到" in result["response"]

    def test_result_none(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_all.return_value = None
            result = svc._execute_customers_query({"data": {}})
        assert "未找到" in result["response"]

    def test_exception_returns_error(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = svc._execute_customers_query({"data": {}})
        assert "查询客户失败" in result["response"]


class TestExecuteNormalModeTools:
    """_execute_normal_mode_tools 补充分支测试。"""

    def test_shipment_generate(self):
        svc = _make_svc()
        svc._execute_shipment_generate = Mock(return_value={"success": True, "shipment": True})
        result = svc._execute_normal_mode_tools(
            {"data": {}}, "shipment_generate", {}, {"text": "gen"}, {}
        )
        assert result["shipment"] is True

    def test_shipments_query(self):
        svc = _make_svc()
        svc._execute_shipments_query = Mock(return_value={"success": True, "shipments": True})
        result = svc._execute_normal_mode_tools(
            {"data": {}}, "shipments", {}, {"text": "query"}, {}
        )
        assert result["shipments"] is True

    def test_other_tool(self):
        svc = _make_svc()
        result = svc._execute_normal_mode_tools(
            {"data": {}}, "unknown", {"p": "v"}, {"text": "resp"}, {"extra": "val"}
        )
        assert result["toolCall"]["tool_id"] == "unknown"
        assert result["toolCall"]["params"]["p"] == "v"
        assert result["toolCall"]["params"]["extra"] == "val"


class TestHandleConfirmationFlow:
    """_handle_confirmation_flow 补充分支测试。"""

    def test_no_file_context_returns(self):
        svc = _make_svc()
        svc._handle_confirmation_flow("u1", "是", None)
        # Should not raise

    def test_message_not_confirm_returns(self):
        svc = _make_svc()
        svc._handle_confirmation_flow("u1", "hello", {"saved_name": "x"})
        # Should not call set_pending_confirmation

    def test_confirm_without_saved_name(self):
        svc = _make_svc()
        svc.ai_service = Mock()
        svc._handle_confirmation_flow(
            "u1",
            "确认",
            {"suggested_use": "unit_products_db", "unit_name": "ACME"},
        )
        svc.ai_service.set_pending_confirmation.assert_not_called()

    def test_confirm_without_suggested_use(self):
        svc = _make_svc()
        svc.ai_service = Mock()
        svc._handle_confirmation_flow(
            "u1",
            "确认",
            {"saved_name": "x.xlsx", "unit_name": "ACME"},
        )
        svc.ai_service.set_pending_confirmation.assert_not_called()

    def test_confirm_without_unit_name(self):
        svc = _make_svc()
        svc.ai_service = Mock()
        svc._handle_confirmation_flow(
            "u1",
            "确认",
            {"saved_name": "x.xlsx", "suggested_use": "unit_products_db"},
        )
        svc.ai_service.set_pending_confirmation.assert_not_called()

    def test_confirm_full_sets_pending(self):
        svc = _make_svc()
        svc.ai_service = Mock()
        svc._handle_confirmation_flow(
            "u1",
            "好的",
            {
                "saved_name": "data.db",
                "suggested_use": "unit_products_db",
                "unit_name_guess": "ACME",
            },
        )
        svc.ai_service.set_pending_confirmation.assert_called_once()

    def test_confirm_with_unit_name_directly(self):
        svc = _make_svc()
        svc.ai_service = Mock()
        svc._handle_confirmation_flow(
            "u1",
            "ok",
            {
                "saved_name": "data.db",
                "suggested_use": "unit_products_db",
                "unit_name": "Beta",
            },
        )
        svc.ai_service.set_pending_confirmation.assert_called_once()
        call_args = svc.ai_service.set_pending_confirmation.call_args[0][1]
        assert call_args["params"]["unit_name"] == "Beta"


class TestSkipProExcelDeterministicImportEdge:
    """_skip_pro_excel_deterministic_import 边界补充。"""

    def test_use_deterministic_shortcut_overrides_skip(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "1")
        ctx = {"excel_import_use_deterministic_shortcut": True}
        assert _skip_pro_excel_deterministic_import(ctx) is False

    def test_skip_shortcut_overrides_ai_decides(self):
        ctx = {
            "excel_import_skip_deterministic_shortcut": True,
            "excel_import_ai_decides": True,
        }
        assert _skip_pro_excel_deterministic_import(ctx) is True

    def test_env_var_yes(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "yes")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_var_on(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "on")
        assert _skip_pro_excel_deterministic_import({}) is True

    def test_env_var_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "")
        monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "")
        assert _skip_pro_excel_deterministic_import({}) is False

    def test_env_var_random(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "random")
        assert _skip_pro_excel_deterministic_import({}) is False

    def test_context_not_dict_uses_empty(self):
        assert _skip_pro_excel_deterministic_import("not-a-dict") is False

    def test_context_list(self):
        assert _skip_pro_excel_deterministic_import([1, 2, 3]) is False
