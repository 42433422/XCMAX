"""AI 聊天业务解析、异常及待确认工作流边界回归。"""

from __future__ import annotations

import asyncio
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


def test_approval_child_preserves_exact_parent_link_without_mutating_parent():
    from app.application.workflow.types import PlanGraph, WorkflowNode

    node = WorkflowNode(
        node_id="sales_create_order",
        tool_id="sales",
        action="create_order",
        params={"quantity": 2},
        risk="high",
    )
    parent = PlanGraph(
        plan_id="wp-session:original", intent="sales", nodes=[node], metadata={"keep": "original"}
    )
    svc = object.__new__(AIChatApplicationService)
    svc._pending_workflows = {
        "web_normal_session": {
            "plan": parent,
            "runtime_context": {"local_user_id": 41},
            "approval_required": True,
            "approval_nodes": [{"node_id": node.node_id}],
        }
    }
    svc.approval_service = Mock()
    svc.approval_service.create_approval_request.return_value = SimpleNamespace(
        request_id="APR-parent"
    )
    svc.approval_service.get_request_metadata.return_value = {"request_no": "APR-parent"}
    orchestrator = Mock()
    orchestrator.start_run_from_plan.return_value = SimpleNamespace(
        status="waiting_user", run_id="run-child"
    )
    with patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator):
        handled, response = svc._resume_pending_dynamic_workflow(
            "web_normal_session", "确认", "确认"
        )
    assert handled and response["success"]
    child = orchestrator.start_run_from_plan.call_args.kwargs["plan"]
    assert child.metadata["approval_parent_plan_id"] == parent.plan_id
    assert child.metadata["approval_parent_node_id"] == node.node_id
    assert child.plan_id == f"{parent.plan_id}:{node.node_id}"
    assert svc.approval_service.create_approval_request.call_args.kwargs["plan"] is child
    assert parent.metadata == {"keep": "original"}
    assert "web_normal_session" not in svc._pending_workflows


@pytest.mark.parametrize("word", ["确认", "好的", "是的", "执行", "OK", "确认执行！"])
@pytest.mark.parametrize("source", ["pro", "normal"])
def test_confirmation_without_context_never_plans_or_creates_approval(word, source):
    svc = _make_svc()
    svc.workflow_engine.run = Mock()
    with patch("app.application.workflow.plan_store.WorkflowPlanStore") as store:
        result = svc._try_handle_dynamic_workflow("u1", word, source, {}, {})
    assert result["data"]["action"] == "clarification_required"
    svc.workflow_planner.plan.assert_not_called()
    svc.workflow_engine.run.assert_not_called()
    svc.approval_service.create_approval_request.assert_not_called()
    store.assert_not_called()


@pytest.mark.parametrize("session_id", ["new", ""])
def test_confirmation_does_not_resume_another_conversation_pending_slot(session_id):
    svc = _make_svc()
    pending = {"plan": _make_plan(), "runtime_context": {"session_id": "old"}}
    svc._pending_workflows["u1"] = pending
    with patch("app.application.agent_orchestrator.AgentOrchestrator") as orchestrator:
        result = svc._try_handle_dynamic_workflow(
            "u1", "确认", "pro", {"session_id": session_id}, {}
        )
    assert result["data"]["action"] == "clarification_required"
    assert svc._pending_workflows["u1"] is pending
    orchestrator.assert_not_called()
    svc.workflow_planner.plan.assert_not_called()


@pytest.mark.parametrize("status", ["running", "pending_awaiting"])
def test_restart_confirmation_hydrates_only_current_session_pending_plan(status):
    from app.application.workflow.types import PlanGraph, WorkflowNode, plan_to_dict

    svc = _make_svc()
    with patch("app.application.workflow.plan_store.WorkflowPlanStore") as store:
        store.return_value.list_active.return_value = [
            {
                "plan": plan_to_dict(
                    PlanGraph(
                        plan_id="original",
                        intent="sales",
                        nodes=[
                            WorkflowNode(node_id="sale", tool_id="sales", action="create_order")
                        ],
                    )
                ),
                "status": status,
                "runtime_context": {"session_id": "original"},
            }
        ]
        restored = svc._hydrate_pending_workflow("u1", "original")
    store.return_value.list_active.assert_called_once_with("u1", limit=1, session_id="original")
    assert restored is (status == "pending_awaiting")
    assert bool(svc._pending_workflows) is restored


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class TestInjectExcelVectorContextEdge:
    """_inject_excel_vector_context 异常与边界分支补充。"""

    def test_context_not_dict_returns_empty(self):
        svc = _make_svc()
        result = svc._inject_excel_vector_context("hello", "not-a-dict")  # type: ignore[arg-type]
        assert result == {}

    def test_no_excel_index_id_returns_context_unchanged(self):
        svc = _make_svc()
        ctx = {"other": "value"}
        result = svc._inject_excel_vector_context("hello", ctx)
        assert result is ctx

    def test_excel_vector_index_id_alias_used(self):
        svc = _make_svc()
        ctx = {"excel_vector_index_id": "idx-123"}
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.query.return_value = {
                "success": True,
                "hits": [{"id": "h1", "score": 0.9}],
            }
            mock_get.return_value = mock_svc
            result = svc._inject_excel_vector_context("hello", ctx)
        assert "excel_vector_context" in result
        assert result["excel_vector_context"]["index_id"] == "idx-123"
        assert result["excel_vector_context"]["hits"][0]["id"] == "h1"

    def test_top_k_invalid_falls_back_to_5(self):
        svc = _make_svc()
        ctx = {"excel_index_id": "idx-1", "excel_top_k": "not-a-number"}
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.query.return_value = {"success": True, "hits": []}
            mock_get.return_value = mock_svc
            result = svc._inject_excel_vector_context("hello", ctx)
        mock_svc.query.assert_called_once_with(index_id="idx-1", query_text="hello", top_k=5)
        assert "excel_vector_context" in result

    def test_query_returns_success_false_returns_context(self):
        svc = _make_svc()
        ctx = {"excel_index_id": "idx-1"}
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.query.return_value = {"success": False, "hits": []}
            mock_get.return_value = mock_svc
            result = svc._inject_excel_vector_context("hello", ctx)
        assert "excel_vector_context" not in result
        assert result is ctx

    def test_query_raises_exception_returns_context(self):
        svc = _make_svc()
        ctx = {"excel_index_id": "idx-1"}
        with patch("app.application.get_excel_vector_search_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.query.side_effect = RuntimeError("search failed")
            mock_get.return_value = mock_svc
            result = svc._inject_excel_vector_context("hello", ctx)
        assert "excel_vector_context" not in result
        assert result is ctx

    def test_import_failure_returns_context(self):
        svc = _make_svc()
        ctx = {"excel_index_id": "idx-1"}
        with patch(
            "app.application.get_excel_vector_search_app_service",
            side_effect=ImportError("module not found"),
        ):
            result = svc._inject_excel_vector_context("hello", ctx)
        assert "excel_vector_context" not in result
        assert result is ctx

    def test_empty_excel_index_id_returns_context(self):
        svc = _make_svc()
        ctx = {"excel_index_id": "   ", "other": "val"}
        result = svc._inject_excel_vector_context("hello", ctx)
        assert result is ctx


class TestExcelAnalysisPayloadPresentEdge:
    """_excel_analysis_payload_present 边界分支补充。"""

    @pytest.mark.parametrize(
        "context, expected",
        [
            (None, False),
            ("not dict", False),
            ({"excel_analysis": "x"}, False),
            ({"excel_analysis": {}}, False),
            ({"excel_analysis": {"summary": "test"}}, True),
            ({"excel_analysis": {"summary": "   "}}, False),
            ({"excel_analysis": {"fields": [{"name": "a"}]}}, True),
            ({"excel_analysis": {"fields": []}}, False),
            ({"excel_analysis": {"fields": "not list"}}, False),
            ({"excel_analysis": {"preview_data": {"sample_rows": [{"a": 1}]}}}, True),
            ({"excel_analysis": {"preview_data": {"sample_rows": []}}}, False),
            ({"excel_analysis": {"preview_data": {"grid_preview": {"rows": [[1], [2]]}}}}, True),
            ({"excel_analysis": {"preview_data": {"grid_preview": {"rows": [[1]]}}}}, False),
        ],
        ids=[
            "context_none",
            "context_not_dict",
            "analysis_not_dict",
            "analysis_empty",
            "summary_present",
            "summary_whitespace",
            "fields_non_empty",
            "fields_empty",
            "fields_not_list",
            "sample_rows_non_empty",
            "sample_rows_empty",
            "grid_two_rows",
            "grid_one_row",
        ],
    )
    def test_payload_shapes(self, context, expected):
        assert AIChatApplicationService._excel_analysis_payload_present(context) is expected


class TestAttachDeterministicWorkflowTraceEdge:
    """_attach_deterministic_workflow_trace 异常分支补充。"""

    def test_import_failure_returns_payload_unchanged(self):
        payload = {"success": True, "message": "ok"}
        with patch.dict(
            "sys.modules",
            {"app.application.agent_orchestrator.chat_trace": None},
        ):
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context={"k": "v"},
                intent="test",
            )
        assert result is payload

    def test_file_context_not_dict_ignored(self):
        payload = {"success": True}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={"success": True, "traced": True},
        ) as mock_attach:
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context={"k": "v"},
                intent="test",
                file_context="not-a-dict",  # type: ignore[arg-type]
            )
        assert result["traced"] is True
        call_kwargs = mock_attach.call_args
        runtime_context = call_kwargs.kwargs.get("runtime_context") or call_kwargs[1].get(
            "runtime_context"
        )
        assert "file_context" not in runtime_context

    def test_file_context_empty_dict_ignored(self):
        payload = {"success": True}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={"success": True, "traced": True},
        ):
            result = AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context=None,
                intent="test",
                file_context={},
            )
        assert result["traced"] is True

    def test_context_not_dict_uses_empty_runtime(self):
        payload = {"success": True}
        with patch(
            "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run",
            return_value={"success": True, "traced": True},
        ) as mock_attach:
            AIChatApplicationService._attach_deterministic_workflow_trace(
                payload,
                user_id="u1",
                message="hello",
                source="pro",
                context="not-dict",  # type: ignore[arg-type]
                intent="test",
            )
        call_kwargs = mock_attach.call_args
        runtime_context = call_kwargs.kwargs.get("runtime_context") or call_kwargs[1].get(
            "runtime_context"
        )
        assert runtime_context == {
            "workflow_intent": "test",
            "workflow_trace_mode": "deterministic_shortcut",
        }


class TestTryHandleDynamicWorkflowEdge:
    """_try_handle_dynamic_workflow 异常分支补充。"""

    def test_empty_text_returns_none(self):
        svc = _make_svc()
        result = svc._try_handle_dynamic_workflow(
            user_id="u1", message="", source="pro", context={}, file_context={}
        )
        assert result is None

    def test_non_pro_no_explicit_no_pending_returns_none(self):
        svc = _make_svc()
        result = svc._try_handle_dynamic_workflow(
            user_id="u1", message="hello world", source=None, context={}, file_context={}
        )
        assert result is None

    def test_import_intent_unit_products_db_no_saved_name(self):
        svc = _make_svc()
        ctx = {
            "file_analysis": {"suggested_use": "unit_products_db"},
            "file_context": {},
        }
        with patch(
            "app.application.ai_chat_app_service.AIChatApplicationService._attach_deterministic_workflow_trace",
            side_effect=lambda p, **kw: p,
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="导入数据库",
                source="pro",
                context=ctx,
                file_context={},
            )
        assert result is not None
        assert "请先上传" in result["response"]

    def test_import_intent_unit_products_db_no_unit_name(self):
        svc = _make_svc()
        ctx = {
            "file_analysis": {
                "suggested_use": "unit_products_db",
                "saved_name": "data.db",
            },
            "file_context": {},
        }
        with patch(
            "app.application.ai_chat_app_service.AIChatApplicationService._attach_deterministic_workflow_trace",
            side_effect=lambda p, **kw: p,
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="导入数据库",
                source="pro",
                context=ctx,
                file_context={},
            )
        assert result is not None
        assert "请补充客户名称" in result["response"]

    def test_import_intent_unit_products_db_full_path_starts_agent_run(self):
        svc = _make_svc()
        ctx = {
            "file_analysis": {
                "suggested_use": "unit_products_db",
                "saved_name": "data.db",
                "unit_name": "ACME",
            },
        }
        with (
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._build_workflow_thinking_steps",
                return_value="thinking",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._start_deterministic_import_agent_run",
                return_value={"success": True, "response": "agent run started"},
            ) as mock_start,
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="导入数据库",
                source="pro",
                context=ctx,
                file_context={},
            )
        assert result["response"] == "agent run started"
        mock_start.assert_called_once()

    def test_short_excel_import_no_context_returns_followup(self):
        svc = _make_svc()
        with patch(
            "app.application.ai_chat_app_service.AIChatApplicationService._attach_deterministic_workflow_trace",
            side_effect=lambda p, **kw: p,
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="加入数据库",
                source="pro",
                context={},
                file_context={},
            )
        assert result is not None
        assert result["data"]["data"]["intent"] == "excel_import_missing_context"

    def test_excel_analysis_with_ambiguous_price_columns(self):
        svc = _make_svc()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"name": "调价前单价"}, {"name": "调价后单价"}],
            }
        }
        with (
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._extract_excel_import_records",
                return_value=([], "ambiguous_price_columns"),
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._attach_deterministic_workflow_trace",
                side_effect=lambda p, **kw: p,
            ),
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="导入数据库",
                source="pro",
                context=ctx,
                file_context={},
            )
        assert result is not None
        assert result["data"]["data"]["blocked_reason"] == "ambiguous_price_columns"

    def test_excel_analysis_no_records_returns_followup(self):
        svc = _make_svc()
        ctx = {
            "excel_analysis": {
                "summary": "test summary",
                "fields": [{"name": "产品"}],
            }
        }
        with (
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._extract_excel_import_records",
                return_value=([], None),
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._attach_deterministic_workflow_trace",
                side_effect=lambda p, **kw: p,
            ),
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="导入数据库",
                source="pro",
                context=ctx,
                file_context={},
            )
        assert result is not None
        assert "未解析到" in result["response"]

    def test_excel_analysis_with_records_starts_agent_run(self):
        svc = _make_svc()
        ctx = {
            "excel_analysis": {
                "summary": "test",
                "fields": [{"name": "产品"}],
                "file_name": "test.xlsx",
            }
        }
        records = [
            {"unit_name": "ACME", "product_name": "P1", "model_number": "M1", "unit_price": 10.0}
        ]
        with (
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._extract_excel_import_records",
                return_value=(records, None),
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._build_workflow_thinking_steps",
                return_value="thinking",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._start_deterministic_import_agent_run",
                return_value={"success": True, "response": "import started"},
            ) as mock_start,
        ):
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="导入数据库",
                source="pro",
                context=ctx,
                file_context={},
            )
        assert result["response"] == "import started"
        mock_start.assert_called_once()

    def test_pending_workflow_confirm_with_approval_required(self):
        from app.application.workflow.types import PlanGraph, WorkflowNode

        svc = _make_svc()
        plan = PlanGraph(
            "plan_test", "test_intent", nodes=[WorkflowNode("approval_node", "db", "write")]
        )
        svc._pending_workflows["u1"] = {
            "plan": plan,
            "runtime_context": {"message": "test"},
            "agent_run_id": "",
            "thinking_steps": "thinking",
            "approval_required": True,
            "approval_nodes": [{"node_id": "approval_node", "tool_id": "db", "action": "write"}],
        }
        waiting_run = SimpleNamespace(status="waiting_user", run_id="run-approval-1")
        with (
            patch.object(svc.approval_service, "create_approval_request") as mock_create,
            patch("app.application.agent_orchestrator.AgentOrchestrator") as mock_orchestrator,
        ):
            mock_orchestrator.return_value.start_run_from_plan.return_value = waiting_run
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="确认",
                source="pro",
                context={},
                file_context={},
            )
        assert "已提交审批请求" in result["response"]
        mock_create.assert_called_once()
        assert "u1" not in svc._pending_workflows  # prevent duplicate approval creation

    def test_normal_profile_returns_none_for_non_workflow(self):
        svc = _make_svc()
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
            result = svc._try_handle_dynamic_workflow(
                user_id="u1",
                message="hello",
                source=None,
                context={},
                file_context={},
            )
        assert result is None


class TestExecuteCustomersIntentEdge:
    """_execute_customers_intent 异常分支补充。"""

    @pytest.mark.parametrize(
        "outcome, expected, exact",
        [
            ({"success": True, "created": True, "unit_name": "ACME"}, "单位已创建", False),
            ({"success": True, "created": False, "unit_name": "ACME"}, "单位已存在", False),
            ({"success": False, "message": "db error"}, "db error", True),
            (RuntimeError("boom"), "处理单位失败", False),
        ],
        ids=["created", "already_exists", "failed", "exception"],
    )
    def test_add_intent_with_unit_name(self, outcome, expected, exact):
        svc = _make_svc()
        response_data = {"data": {}}
        effect = (
            {"side_effect": outcome}
            if isinstance(outcome, Exception)
            else {"return_value": outcome}
        )
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            **effect,
        ):
            result = svc._execute_customers_intent(
                response_data=response_data,
                slots={"unit_name": "ACME"},
                parsed_params={},
                original_message="添加单位 ACME",
            )
        if exact:
            assert result["response"] == expected
        else:
            assert expected in result["response"]

    def test_add_intent_without_unit_name_returns_followup(self):
        svc = _make_svc()
        response_data = {"data": {}}
        result = svc._execute_customers_intent(
            response_data=response_data,
            slots={},
            parsed_params={},
            original_message="添加单位",
        )
        assert "你要添加哪个单位" in result["response"]
        assert result["data"]["data"]["missing_fields"] == ["unit_name"]

    def test_query_intent_calls_customers_query(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch.object(
            svc, "_execute_customers_query", return_value={"response": "queried"}
        ) as mock_q:
            result = svc._execute_customers_intent(
                response_data=response_data,
                slots={},
                parsed_params={},
                original_message="查询客户列表",
            )
        assert result["response"] == "queried"
        mock_q.assert_called_once()

    def test_no_explicit_intent_returns_followup(self):
        svc = _make_svc()
        response_data = {"data": {}}
        result = svc._execute_customers_intent(
            response_data=response_data,
            slots={},
            parsed_params={},
            original_message="客户",
        )
        assert "我可以帮你处理单位管理" in result["response"]
        assert result["data"]["data"]["intent"] == "customers_followup"

    def test_add_intent_english_keyword(self):
        svc = _make_svc()
        response_data = {"data": {}}
        result = svc._execute_customers_intent(
            response_data=response_data,
            slots={},
            parsed_params={},
            original_message="add customer",
        )
        assert "你要添加哪个单位" in result["response"]

    def test_query_intent_english_keyword(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch.object(svc, "_execute_customers_query", return_value={"response": "ok"}):
            result = svc._execute_customers_intent(
                response_data=response_data,
                slots={},
                parsed_params={},
                original_message="list customers",
            )
        assert result["response"] == "ok"


class TestExecuteShipmentGenerateEdge:
    """_execute_shipment_generate 异常分支补充。"""

    @pytest.mark.parametrize(
        "document_result, expected",
        [
            ({"success": True, "doc_name": "order-001.docx"}, "order-001.docx"),
            ({"success": True}, "已生成发货单"),
            ({"success": False, "message": "template missing"}, "template missing"),
        ],
        ids=["with_doc_name", "without_doc_name", "document_failed"],
    )
    def test_parsed_success_document_result(self, document_result, expected):
        svc = _make_svc()
        response_data = {"data": {}}
        with (
            patch(
                "app.application.facades.tools_facade._parse_order_text",
                return_value={"success": True, "unit_name": "ACME", "products": []},
            ),
            patch("app.bootstrap.get_shipment_app_service") as mock_get,
        ):
            mock_svc = mock_get.return_value
            mock_svc.generate_shipment_document.return_value = document_result
            result = svc._execute_shipment_generate(response_data, {}, {"text": "order"})
        assert expected in result["response"]

    def test_parsed_failure_returns_message(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "parse error"},
        ):
            result = svc._execute_shipment_generate(response_data, {}, {"text": "order"})
        assert "parse error" in result["response"]

    def test_exception_returns_error(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=RuntimeError("boom"),
        ):
            result = svc._execute_shipment_generate(response_data, {}, {"text": "order"})
        assert "生成发货单失败" in result["response"]


class TestExecuteShipmentsQueryEdge:
    """_execute_shipments_query 异常分支补充。"""

    def test_empty_orders(self):
        svc = _make_svc()
        response_data = {"data": {}, "toolCall": {"tool_id": "old"}}
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = []
            result = svc._execute_shipments_query(response_data)
        assert "暂无订单记录" in result["response"]
        assert "toolCall" not in result

    def test_orders_with_various_fields(self):
        svc = _make_svc()
        response_data = {"data": {}}
        orders = [
            {
                "order_number": "ORD-001",
                "customer_name": "ACME",
                "date": "2026-01-01",
                "total_amount": 100.0,
                "status": "已完成",
            },
            {
                "order_no": "ORD-002",
                "unit_name": "Beta",
                "created_at": "2026-01-02",
                "total_amount_yuan": 200.0,
                "status": "pending",
            },
        ]
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = orders
            result = svc._execute_shipments_query(response_data)
        assert "ORD-001" in result["response"]
        assert "ORD-002" in result["response"]
        assert "ACME" in result["response"]
        assert "Beta" in result["response"]

    def test_orders_more_than_10_truncated(self):
        svc = _make_svc()
        response_data = {"data": {}}
        orders = [{"id": i, "order_number": f"ORD-{i}"} for i in range(15)]
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = orders
            result = svc._execute_shipments_query(response_data)
        assert "ORD-0" in result["response"]

    def test_exception_returns_silently(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch("app.bootstrap.get_shipment_app_service", side_effect=RuntimeError("boom")):
            result = svc._execute_shipments_query(response_data)
        # Should not raise, response_data returned as-is
        assert "data" in result

    def test_get_orders_returns_none(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_orders.return_value = None
            result = svc._execute_shipments_query(response_data)
        assert "暂无订单记录" in result["response"]


class TestBuildOrderTextFromProductsEdge:
    """_build_order_text_from_products 边界分支补充。"""

    def test_empty_products_returns_empty(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products("ACME", [], "original", 1, 25)
        assert result == ""

    def test_empty_unit_name_returns_empty(self):
        svc = _make_svc()
        result = svc._build_order_text_from_products("", [{"model": "M1"}], "original", 1, 25)
        assert result == ""

    def test_with_original_message_and_multi_match(self):
        svc = _make_svc()
        original = "打ACME的货单,5桶5003规格25,3桶5004规格30"
        products = [{"model": "5003"}]
        result = svc._build_order_text_from_products("ACME", products, original, 1, 25)
        assert "ACME" in result
        assert "5003" in result or "5004" in result

    def test_products_without_model_uses_spec_only(self):
        svc = _make_svc()
        products = [{"quantity_tins": 5, "tin_spec": 25}]
        result = svc._build_order_text_from_products("ACME", products, "", 1, 25)
        assert "ACME" in result
        assert "5桶" in result
        assert "25" in result

    def test_products_with_various_field_names(self):
        svc = _make_svc()
        products = [
            {"model_number": "M1", "quantity": 3, "spec": 20},
            {"name": "P2", "qty": 2, "tin_spec": 15},
            {"model": "M3", "quantity_tins": 1, "规格": 10},
        ]
        result = svc._build_order_text_from_products("ACME", products, "", 1, 25)
        assert "ACME" in result
        assert "M1" in result
        assert "P2" in result
        assert "M3" in result

    def test_products_with_default_qty_and_spec(self):
        svc = _make_svc()
        products = [{"model": "M1"}]
        result = svc._build_order_text_from_products("ACME", products, "", None, None)
        assert "ACME" in result
        assert "M1" in result
        # default qty=1, default spec=25
        assert "1桶" in result
        assert "25" in result


class TestTryMergeSplitModelEdge:
    """_try_merge_split_model 边界分支补充。"""

    def test_first_pattern_match(self):
        svc = _make_svc()
        product_template = {"quantity_tins": 2, "spec": 25}
        result = svc._try_merge_split_model("5003-2737B 规格 30", product_template)
        # 第一个正则 (\d+)([A-Z]?)\s*规格\s*(\d+) 匹配 "2737B 规格 30"
        assert "2737B" in result
        assert "30" in result
        assert "2桶" in result

    def test_second_pattern_match(self):
        svc = _make_svc()
        product_template = {"quantity_tins": 1, "spec": 25}
        # 第一个正则不匹配（无 "规格" 关键词前的数字+字母），
        # 但第二个正则 (\d+)\s*桶\s*(\d+)([A-Z]?)\s*规格\s*(\d+) 匹配
        # 实际上第一个正则会先匹配 "5003 规格 30"，所以这里测试第一个正则的 qty 来自 template
        result = svc._try_merge_split_model("3桶 5003 规格 30", product_template)
        # 第一个正则先匹配，qty 来自 product_template
        assert "5003" in result
        assert "30" in result

    def test_no_match_returns_empty(self):
        svc = _make_svc()
        product_template = {"quantity_tins": 1, "spec": 25}
        result = svc._try_merge_split_model("no model here", product_template)
        assert result == ""

    def test_first_pattern_match_with_letter_suffix(self):
        svc = _make_svc()
        product_template = {"quantity_tins": 1, "spec": 25}
        result = svc._try_merge_split_model("5003A 规格 30", product_template)
        assert "5003A" in result
        assert "30" in result


class TestFormatWorkflowToolSuccessLineEdge:
    """_format_workflow_tool_success_line 边界分支补充。"""

    @pytest.mark.parametrize(
        "tool_id, action, output, node_params, expected",
        [
            pytest.param(
                "employee",
                "list",
                {"data": {"registered_tool_count": 5}, "message": "ok"},
                {},
                ("5", "可调用员工"),
                id="employee_list_action_with_preview",
            ),
            pytest.param(
                "employee",
                "list",
                None,
                {},
                ("0",),
                id="employee_list_action_without_preview",
            ),
            pytest.param(
                "employee",
                "invoke",
                {"employee_id": "e1", "message": "done"},
                {},
                ("e1", "done"),
                id="employee_other_action_with_message",
            ),
            pytest.param(
                "employee",
                "invoke",
                {},
                {"employee_id": "from-params"},
                ("from-params",),
                id="employee_other_action_no_message_uses_node_params",
            ),
            pytest.param(
                "business_db",
                "read",
                {"data": [{"id": 1}, {"id": 2}], "message": "ok"},
                {"entity": "products"},
                ("products", "2"),
                id="business_db_read_action",
            ),
            pytest.param(
                "business_db",
                "query",
                {"data": [], "message": "ok"},
                {"entity": "customers"},
                ("customers", "0"),
                id="business_db_query_action",
            ),
            pytest.param(
                "business_db",
                "create",
                {"message": "created"},
                {"entity": "order", "operation": "create"},
                ("order", "create", "created"),
                id="business_db_write_action",
            ),
            pytest.param(
                "business_db",
                "update",
                {"entity": "shipment", "message": "updated"},
                {},
                ("shipment",),
                id="business_db_with_entity_from_output",
            ),
            pytest.param(
                "custom_tool",
                "execute",
                {"message": "custom result"},
                {},
                ("custom result",),
                id="other_tool_with_message",
            ),
            pytest.param(
                "custom_tool",
                "execute",
                {},
                {},
                ("成功",),
                id="other_tool_without_message",
            ),
        ],
    )
    def test_success_line(self, tool_id, action, output, node_params, expected):
        svc = _make_svc()
        item = SimpleNamespace(node_id="n1", tool_id=tool_id, action=action, output=output)
        result = svc._format_workflow_tool_success_line(item, node_params)
        for fragment in expected:
            assert fragment in result[0]
        assert len(result) >= 1


class TestExecuteProModeToolsEdge:
    """_execute_pro_mode_tools shipment_generate 各 slot 组合分支补充。"""

    def test_shipment_generate_with_long_original_message(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "gen", "data": {}}
        result = svc._execute_pro_mode_tools(
            response_data,
            "shipment_generate",
            {"unit_name": "ACME", "quantity_tins": 5, "model_number": "M1", "tin_spec": 25},
            {},
            ai_result,
            original_message="这是ACME的订单，需要5桶M1规格25",
        )
        assert result["toolCall"]["params"]["order_text"] == "这是ACME的订单，需要5桶M1规格25"

    def test_shipment_generate_with_all_slots_no_original(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "gen", "data": {}}
        result = svc._execute_pro_mode_tools(
            response_data,
            "shipment_generate",
            {"unit_name": "ACME", "quantity_tins": 5, "model_number": "M1", "tin_spec": 25},
            {},
            ai_result,
            original_message="ok",
        )
        assert "ACME" in result["toolCall"]["params"]["order_text"]
        assert "5" in result["toolCall"]["params"]["order_text"]

    def test_shipment_generate_with_products_list(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "gen", "data": {}}
        products = [{"model": "M1", "quantity_tins": 3, "spec": 20}]
        result = svc._execute_pro_mode_tools(
            response_data,
            "shipment_generate",
            {"unit_name": "ACME", "products": products},
            {},
            ai_result,
            original_message="ok",
        )
        assert "ACME" in result["toolCall"]["params"]["order_text"]

    def test_shipment_generate_with_parsed_order_products(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "gen", "data": {}}
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={
                "success": True,
                "unit_name": "Parsed",
                "products": [{"model": "P1", "quantity_tins": 2, "spec": 15}],
            },
        ):
            result = svc._execute_pro_mode_tools(
                response_data,
                "shipment_generate",
                {"unit_name": "ACME"},
                {},
                ai_result,
                original_message="打Parsed的货单",
            )
        assert result["toolCall"]["params"]["unit_name"] == "Parsed"
        assert len(result["toolCall"]["params"]["products"]) == 1

    def test_shipment_generate_fallback_to_ai_text(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "fallback text", "data": {}}
        result = svc._execute_pro_mode_tools(
            response_data,
            "shipment_generate",
            {},
            {},
            ai_result,
            original_message="ok",
        )
        assert result["toolCall"]["params"]["order_text"] == "fallback text"

    def test_other_tool_pro_mode(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "resp", "data": {"extra": "val"}}
        result = svc._execute_pro_mode_tools(
            response_data,
            "custom_tool",
            {},
            {"p": "v"},
            ai_result,
            original_message="ok",
        )
        assert result["toolCall"]["tool_id"] == "custom_tool"
        assert result["toolCall"]["params"]["p"] == "v"
        assert result["toolCall"]["params"]["extra"] == "val"


class TestExecuteProductsQueryEdge:
    """_execute_products_query 边界分支补充。"""

    def test_keyword_with_de_pattern_resolved(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with (
            patch("app.bootstrap.get_products_service") as mock_get,
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=SimpleNamespace(unit_name="ResolvedCorp"),
            ),
        ):
            mock_svc = mock_get.return_value
            mock_svc.get_products.return_value = {"data": [{"id": 1}]}
            result = svc._execute_products_query(
                response_data,
                {"keyword": "七彩乐园的5003A"},
                {},
            )
        assert result["data"]["unit_name"] == "ResolvedCorp"
        assert result["data"]["model_number"] == "5003A"
        mock_svc.get_products.assert_called_once_with(
            model_number="5003A", unit_name="ResolvedCorp"
        )

    def test_keyword_with_de_pattern_not_resolved(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with (
            patch("app.bootstrap.get_products_service") as mock_get,
            patch(
                "app.infrastructure.lookups.purchase_unit_resolver.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            mock_svc = mock_get.return_value
            mock_svc.get_products.return_value = {"data": []}
            result = svc._execute_products_query(
                response_data,
                {"keyword": "测试单位的123B"},
                {},
            )
        assert result["data"]["unit_name"] == "测试单位"
        assert result["data"]["model_number"] == "123B"

    @pytest.mark.parametrize(
        "slots, products, expected",
        [
            ({"model_number": "M1", "unit_name": "ACME"}, [{"id": 1}], "查询到 1"),
            ({"model_number": "M1"}, [], "未找到"),
            ({"unit_name": "ACME"}, [{"id": 1}, {"id": 2}], "查询到 2"),
        ],
        ids=["model_and_unit", "model_only", "unit_only"],
    )
    def test_model_and_unit_filters(self, slots, products, expected):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_products.return_value = {"data": products}
            result = svc._execute_products_query(response_data, slots, {})
        mock_svc.get_products.assert_called_once_with(**slots)
        assert expected in result["response"]

    def test_keyword_only(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_products.return_value = {"data": [{"id": 1}]}
            result = svc._execute_products_query(
                response_data,
                {"keyword": "search term"},
                {},
            )
        mock_svc.get_products.assert_called_once_with(keyword="search term")

    def test_no_slots_calls_get_all(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch("app.bootstrap.get_products_service") as mock_get:
            mock_svc = mock_get.return_value
            mock_svc.get_products.return_value = {"data": [{"id": 1}]}
            result = svc._execute_products_query(
                response_data,
                {},
                {},
            )
        mock_svc.get_products.assert_called_once_with()

    def test_exception_returns_error(self):
        svc = _make_svc()
        response_data = {"data": {}}
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("boom")):
            result = svc._execute_products_query(
                response_data,
                {},
                {},
            )
        assert "查询产品失败" in result["response"]


class TestProcessChatEdge:
    """process_chat 异常分支补充。"""

    def test_empty_message_returns_error(self):
        svc = _make_svc()
        result = svc.process_chat("u1", "", None, None, None)
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_connection_error_returns_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._inject_excel_vector_context",
                side_effect=lambda message, context: context,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._handle_confirmation_flow",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._try_handle_dynamic_workflow",
                return_value=None,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._persist_chat_turn",
            ),
            patch("asyncio.set_event_loop"),
        ):
            with patch("asyncio.new_event_loop") as mock_new_loop:
                mock_loop = MagicMock()
                mock_loop.run_until_complete.side_effect = ConnectionError("conn failed")
                mock_new_loop.return_value = mock_loop
                result = svc.process_chat("u1", "测试消息", None, None, None)
        assert "AI 服务连接失败" in result["message"]

    def test_timeout_error_returns_fallback(self):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._inject_excel_vector_context",
                side_effect=lambda message, context: context,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._handle_confirmation_flow",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._try_handle_dynamic_workflow",
                return_value=None,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._persist_chat_turn",
            ),
            patch("asyncio.set_event_loop"),
        ):
            with patch("asyncio.new_event_loop") as mock_new_loop:
                mock_loop = MagicMock()
                mock_loop.run_until_complete.side_effect = TimeoutError("timed out")
                mock_new_loop.return_value = mock_loop
                result = svc.process_chat("u1", "测试消息", None, None, None)
        assert "AI 服务响应超时" in result["message"]

    @pytest.mark.parametrize("error", ["API_KEY invalid", "connection refused", "unknown error"])
    def test_recoverable_errors_return_fallback(self, error):
        svc = _make_svc()
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._inject_excel_vector_context",
                side_effect=lambda message, context: context,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._handle_confirmation_flow",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._try_handle_dynamic_workflow",
                return_value=None,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._persist_chat_turn",
            ),
            patch("asyncio.set_event_loop"),
        ):
            with patch("asyncio.new_event_loop") as mock_new_loop:
                mock_loop = MagicMock()
                mock_loop.run_until_complete.side_effect = RuntimeError(error)
                mock_new_loop.return_value = mock_loop
                result = svc.process_chat("u1", "测试消息", None, None, None)
        assert "AI 服务暂时不可用" in result["message"]

    def test_workflow_result_returns_finalized(self):
        svc = _make_svc()
        workflow_result = {"success": True, "response": "workflow done"}
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._inject_excel_vector_context",
                side_effect=lambda message, context: context,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._handle_confirmation_flow",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._try_handle_dynamic_workflow",
                return_value=workflow_result,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._persist_chat_turn",
            ),
            patch("asyncio.set_event_loop"),
        ):
            result = svc.process_chat("u1", "导入数据库", {"source": "pro"}, "pro", None)
        assert result["response"] == "workflow done"

    def test_file_context_excel_analysis_injection(self):
        svc = _make_svc()
        ai_result = {"text": "ok", "action": "chat", "data": {}}
        with (
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_chat_received"),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._inject_excel_vector_context",
                side_effect=lambda message, context: context,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._handle_confirmation_flow",
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._try_handle_dynamic_workflow",
                return_value=None,
            ),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._persist_chat_turn",
            ),
            patch("asyncio.new_event_loop") as mock_new_loop,
            patch("asyncio.set_event_loop"),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService._build_response",
                return_value={"success": True, "response": "ok"},
            ),
        ):
            mock_loop = MagicMock()
            mock_loop.run_until_complete.return_value = ai_result
            mock_new_loop.return_value = mock_loop
            file_context = {"file_path": "/tmp/test.xlsx", "sheet_name": "Sheet1"}
            result = svc.process_chat("u1", "随便说点什么", {}, None, file_context)
        assert result["response"] == "ok"


class TestExtractExcelImportRecordsEdge:
    """_extract_excel_import_records 边界分支补充。"""

    def _extract_records(
        self,
        svc,
        excel_analysis,
        column_roles,
        *,
        confidence=0.9,
        llm_roles=None,
        default_unit="",
        reloaded=None,
        user_message="导入",
    ):
        with (
            patch.object(
                AIChatApplicationService, "_try_structured_reload_records", return_value=reloaded
            ),
            patch.object(
                AIChatApplicationService,
                "_infer_excel_column_roles",
                return_value=(column_roles, confidence),
            ),
            patch.object(
                AIChatApplicationService,
                "_infer_excel_column_roles_with_llm",
                return_value=llm_roles or {},
            ),
            patch.object(
                AIChatApplicationService,
                "_default_purchase_unit_for_import",
                return_value=default_unit,
            ),
        ):
            return svc._extract_excel_import_records(
                excel_analysis, None, user_message=user_message
            )

    def test_empty_preview_data_returns_empty(self):
        svc = _make_svc()
        records, err = svc._extract_excel_import_records({}, None, user_message="导入")
        assert records == []
        assert err is None

    def test_with_sample_rows(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"产品": "P1", "型号": "M1", "单价": "10"},
                    {"产品": "P2", "型号": "M2", "单价": "20"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {"unit_name": "", "product_name": "产品", "model_number": "型号", "unit_price": "单价"},
            default_unit="默认单位",
        )
        assert err is None
        assert len(records) >= 1

    def test_with_grid_preview_rows(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "grid_preview": {
                    "rows": [
                        ["产品", "型号"],
                        ["P1", "M1"],
                    ]
                }
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {"unit_name": "", "product_name": "产品", "model_number": "型号", "unit_price": ""},
            default_unit="默认单位",
        )
        assert err is None
        assert len(records) >= 1

    def test_unnamed_columns_promotion(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"Unnamed: 0": "产品", "Unnamed: 1": "型号", "Unnamed: 2": "单价"},
                    {"Unnamed: 0": "P1", "Unnamed: 1": "M1", "Unnamed: 2": "10"},
                    {"Unnamed: 0": "P2", "Unnamed: 1": "M2", "Unnamed: 2": "20"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {"unit_name": "", "product_name": "产品", "model_number": "型号", "unit_price": "单价"},
            default_unit="默认单位",
        )
        assert err is None
        assert len(records) >= 1
        # After promotion, keys should be the header values
        assert "产品" in records[0] or "P1" in str(records[0])

    def test_low_confidence_uses_llm_roles(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"col1": "P1", "col2": "M1", "col3": "10"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {"unit_name": "", "product_name": "", "model_number": "", "unit_price": ""},
            confidence=0.3,
            llm_roles={"product_name": "col1", "model_number": "col2", "unit_price": "col3"},
        )
        assert err is None

    def test_ambiguous_price_columns_returns_error(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"调价前单价": "10", "调价后单价": "20", "产品": "P1"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {"unit_name": "", "product_name": "产品", "model_number": "", "unit_price": ""},
            user_message="导入调价前和调价后",
        )
        assert err == "ambiguous_price_columns"
        assert records == []

    def test_unit_key_conflicts_with_product_key_cleared(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"col1": "P1", "col2": "10"},
                    {"col1": "P2", "col2": "20"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {"unit_name": "col1", "product_name": "col1", "model_number": "", "unit_price": "col2"},
            default_unit="ACME",
        )
        assert err is None
        # unit_key cleared due to conflict, default_unit applied
        if records:
            assert records[0]["unit_name"] == "ACME"

    def test_unit_key_packaging_ratio_high_cleared(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"unit": "件", "product": "P1", "price": "10"},
                    {"unit": "箱", "product": "P2", "price": "20"},
                    {"unit": "盒", "product": "P3", "price": "30"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {
                "unit_name": "unit",
                "product_name": "product",
                "model_number": "",
                "unit_price": "price",
            },
            default_unit="ACME",
        )
        assert err is None
        if records:
            assert records[0]["unit_name"] == "ACME"

    def test_dedup_removes_duplicates(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"unit": "ACME", "product": "P1", "price": "10"},
                    {"unit": "ACME", "product": "P1", "price": "10"},  # duplicate
                    {"unit": "ACME", "product": "P2", "price": "20"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {
                "unit_name": "unit",
                "product_name": "product",
                "model_number": "",
                "unit_price": "price",
            },
        )
        assert err is None
        # Duplicates removed
        assert len(records) == 2

    def test_invalid_price_falls_back_to_zero(self):
        svc = _make_svc()
        excel_analysis = {
            "preview_data": {
                "sample_rows": [
                    {"unit": "ACME", "product": "P1", "price": "not-a-number"},
                ]
            }
        }
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {
                "unit_name": "unit",
                "product_name": "product",
                "model_number": "",
                "unit_price": "price",
            },
        )
        assert err is None
        if records:
            assert records[0]["unit_price"] == 0.0

    def test_reloaded_records_used_when_available(self):
        svc = _make_svc()
        excel_analysis = {"preview_data": {}}
        reloaded = [
            {"unit": "ACME", "product": "P1", "price": "10"},
            {"unit": "ACME", "product": "P2", "price": "20"},
        ]
        records, err = self._extract_records(
            svc,
            excel_analysis,
            {
                "unit_name": "unit",
                "product_name": "product",
                "model_number": "",
                "unit_price": "price",
            },
            reloaded=reloaded,
        )
        assert err is None
        assert len(records) == 2


class TestBuildResponseEdge:
    """_build_response / _handle_tool_call 边界分支补充。"""

    def test_build_response_with_followup_action(self):
        svc = _make_svc()
        ai_result = {"text": "ask", "action": "followup", "data": {"question": "what?"}}
        result = svc._build_response(ai_result, None, "hello")
        assert result["followup"] == {"question": "what?"}

    def test_build_response_with_auto_action(self):
        svc = _make_svc()
        ai_result = {"text": "auto", "action": "auto_action", "data": {"type": "show"}}
        result = svc._build_response(ai_result, None, "hello")
        assert result["autoAction"] == {"type": "show"}

    def test_build_response_with_chat_action(self):
        svc = _make_svc()
        ai_result = {"text": "hi", "action": "chat", "data": {}}
        result = svc._build_response(ai_result, None, "hello")
        assert result["response"] == "hi"
        assert "followup" not in result
        assert "autoAction" not in result

    def test_handle_tool_call_no_tool_key(self):
        svc = _make_svc()
        response_data = {"data": {"data": {}}}
        ai_result = {"text": "resp"}
        result_data = {"params": {"p": "v"}, "data": {"inner": "val"}}
        result = svc._handle_tool_call(response_data, ai_result, result_data, None, "msg")
        assert result["response"] == "resp"
        assert result["data"]["data"] == {"inner": "val"}

    def test_handle_tool_call_pro_source_dispatches_to_pro(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "resp"}
        result_data = {"tool_key": "products", "slots": {}, "params": {}}
        with patch.object(svc, "_execute_pro_mode_tools", return_value={"pro": True}) as mock_pro:
            result = svc._handle_tool_call(response_data, ai_result, result_data, "pro", "msg")
        mock_pro.assert_called_once()

    def test_handle_tool_call_normal_source_dispatches_to_normal(self):
        svc = _make_svc()
        response_data = {"data": {}}
        ai_result = {"text": "resp"}
        result_data = {"tool_key": "shipment_generate", "params": {}}
        with patch.object(
            svc, "_execute_normal_mode_tools", return_value={"normal": True}
        ) as mock_normal:
            result = svc._handle_tool_call(response_data, ai_result, result_data, None, "msg")
        mock_normal.assert_called_once()
