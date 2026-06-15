"""Tests for app.application.workflow.engine — coverage ramp."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)


def _make_engine(dispatch_result=None):
    if dispatch_result is None:
        dispatch_result = {"success": True, "data": []}

    def mock_dispatch(tool_id, action, params):
        return dispatch_result

    return WorkflowEngine(tool_dispatcher=mock_dispatch)


def _simple_plan(nodes=None, plan_id="p1"):
    if nodes is None:
        nodes = [
            WorkflowNode(
                node_id="n1",
                tool_id="products",
                action="query",
                params={"keyword": "test"},
                risk="low",
                idempotent=True,
            )
        ]
    return PlanGraph(
        plan_id=plan_id,
        intent="test_workflow",
        todo_steps=["step1"],
        nodes=nodes,
        risk_level="low",
    )


# ========================= _run_batch ====================================


class TestWorkflowEngineRunBatch:
    def test_single_node_success(self):
        engine = _make_engine({"success": True, "data": [{"name": "P1"}]})
        plan = _simple_plan()
        result = engine.run(plan)
        assert result.success is True
        assert len(result.node_results) == 1
        assert result.node_results[0].success is True

    def test_single_node_failure(self):
        engine = _make_engine({"success": False, "message": "not found"})
        plan = _simple_plan()
        result = engine.run(plan)
        assert result.success is False
        assert "n1" in result.message

    def test_sequential_nodes(self):
        engine = _make_engine({"success": True, "data": []})
        nodes = [
            WorkflowNode(node_id="n1", tool_id="products", action="query", params={}, risk="low"),
            WorkflowNode(
                node_id="n2",
                tool_id="customers",
                action="query",
                params={},
                risk="low",
                depends_on=["n1"],
            ),
        ]
        plan = _simple_plan(nodes=nodes)
        result = engine.run(plan)
        assert result.success is True
        assert len(result.node_results) == 2

    def test_circular_dependency_stalls(self):
        engine = _make_engine({"success": True})
        nodes = [
            WorkflowNode(node_id="n1", tool_id="a", action="x", params={}, depends_on=["n2"]),
            WorkflowNode(node_id="n2", tool_id="b", action="y", params={}, depends_on=["n1"]),
        ]
        plan = _simple_plan(nodes=nodes)
        result = engine.run(plan)
        assert result.success is False
        assert "依赖无法继续解析" in result.message

    def test_runtime_context_propagation(self):
        engine = _make_engine({"success": True, "data": []})
        plan = _simple_plan()
        result = engine.run(plan, runtime_context={"message": "hello"})
        assert "node_outputs" in result.final_context

    def test_empty_plan(self):
        engine = _make_engine()
        plan = _simple_plan(nodes=[])
        result = engine.run(plan)
        assert result.success is True
        assert result.node_results == []


# ========================= _run_node =====================================


class TestWorkflowEngineRunNode:
    def test_success_on_first_try(self):
        engine = _make_engine({"success": True})
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {})
        assert result.success is True
        assert result.retries == 0

    def test_retry_on_failure(self):
        call_count = 0

        def flaky_dispatch(tool_id, action, params):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return {"success": False, "message": "temp error"}
            return {"success": True}

        engine = WorkflowEngine(tool_dispatcher=flaky_dispatch)
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {}, max_retries=2)
        assert result.success is True
        assert result.retries == 1

    def test_all_retries_exhausted(self):
        engine = _make_engine({"success": False, "message": "permanent error"})
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {}, max_retries=1)
        assert result.success is False
        assert result.error == "permanent error"

    def test_exception_in_dispatch(self):
        def bad_dispatch(tool_id, action, params):
            raise RuntimeError("boom")

        engine = WorkflowEngine(tool_dispatcher=bad_dispatch)
        plan = _simple_plan()
        result = engine._run_node(plan.nodes[0], {}, max_retries=0)
        assert result.success is False
        assert "boom" in result.error


# ========================= _summarize_output =============================


class TestSummarizeOutput:
    def test_success_with_message(self):
        assert "ok" in WorkflowEngine._summarize_output({"success": True, "message": "ok"})

    def test_success_with_data_list(self):
        result = WorkflowEngine._summarize_output({"success": True, "data": [1, 2, 3]})
        assert "3 条数据" in result

    def test_failure_output(self):
        result = WorkflowEngine._summarize_output({"success": False, "error": "bad"})
        assert "错误" in result

    def test_non_dict(self):
        result = WorkflowEngine._summarize_output("plain text")
        assert "plain text" in result


# ========================= _has_non_empty_param ==========================


class TestHasNonEmptyParam:
    def test_has_param(self):
        assert WorkflowEngine._has_non_empty_param({"keyword": "test"}, ("keyword",)) is True

    def test_empty_param(self):
        assert WorkflowEngine._has_non_empty_param({"keyword": ""}, ("keyword",)) is False

    def test_none_param(self):
        assert WorkflowEngine._has_non_empty_param({"keyword": None}, ("keyword",)) is False

    def test_missing_key(self):
        assert WorkflowEngine._has_non_empty_param({}, ("keyword",)) is False


# ========================= _merge_runtime_fallback_params ================


class TestMergeRuntimeFallbackParams:
    def test_products_query_empty_params(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="products", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "hello"})
        assert params["keyword"] == "hello"

    def test_products_query_with_keyword(self):
        engine = _make_engine()
        node = WorkflowNode(
            node_id="n1", tool_id="products", action="query", params={"keyword": "x"}
        )
        params = {"keyword": "x"}
        engine._merge_runtime_fallback_params(node, params, {"message": "hello"})
        assert params["keyword"] == "x"

    def test_customers_query_empty_params(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="customers", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "find customer"})
        assert params["keyword"] == "find customer"

    def test_no_message(self):
        engine = _make_engine()
        node = WorkflowNode(node_id="n1", tool_id="products", action="query", params={})
        params = {}
        engine._merge_runtime_fallback_params(node, params, {})
        assert "keyword" not in params


# ========================= _run_single_tool ==============================


class TestRunSingleTool:
    def test_success(self):
        engine = _make_engine({"success": True, "data": []})
        result = engine._run_single_tool("products", "query", {}, {}, 0)
        assert result.success is True

    def test_failure_with_retries(self):
        engine = _make_engine({"success": False, "message": "err"})
        result = engine._run_single_tool("products", "query", {}, {}, 1)
        assert result.success is False

    def test_exception(self):
        def bad_dispatch(tool_id, action, params):
            raise ValueError("bad")

        engine = WorkflowEngine(tool_dispatcher=bad_dispatch)
        result = engine._run_single_tool("products", "query", {}, {}, 0)
        assert result.success is False
        assert "bad" in result.error


# ========================= agentic_loop ==================================


class TestWorkflowEngineAgenticLoop:
    def test_agentic_loop_done_immediately(self):
        engine = _make_engine()
        with patch.object(engine, "_llm_decide_next_step", return_value={"action": "done"}):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True

    def test_agentic_loop_no_api_key(self):
        engine = _make_engine()
        with patch.object(engine, "_llm_decide_next_step", return_value=None):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True
        assert len(result.node_results) == 0

    def test_agentic_loop_execute_then_done(self):
        engine = _make_engine({"success": True, "data": []})
        call_count = 0

        def mock_decide(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "action": "execute",
                    "tool_id": "products",
                    "action_name": "query",
                    "params": {},
                    "reasoning": "test",
                }
            return {"action": "done"}

        with patch.object(engine, "_llm_decide_next_step", side_effect=mock_decide):
            plan = _simple_plan()
            result = engine.run(
                plan,
                runtime_context={"message": "test"},
                agentic_loop=True,
                tool_registry={"products": {"actions": {"query": {"risk": "low"}}}},
            )
        assert result.success is True
        assert len(result.node_results) == 1
