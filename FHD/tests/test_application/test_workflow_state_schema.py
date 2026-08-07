"""Tests for typed StateSchema + reducer in app.application.workflow.

Covers:
  - apply_state_schema: cross-node typed state passing,
  - invalid type raises a clear error (no silent data loss),
  - "append" merge accumulates a list,
  - "merge_dict" merge merges dicts,
  - engine integration: default schema validation round-trips through _run_batch.
"""

from __future__ import annotations

import pytest

from app.application.workflow.engine import DEFAULT_STATE_SCHEMA, WorkflowEngine
from app.application.workflow.types import (
    PlanGraph,
    StateSchema,
    WorkflowNode,
    apply_state_schema,
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
                params={},
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


# ===========================================================================
# apply_state_schema — 类型校验 + 合并语义
# ===========================================================================


class TestApplyStateSchema:
    def test_cross_node_type_passing_success(self):
        schema = (
            StateSchema()
            .declare("count", type=int, merge="set")
            .declare("tags", type=list, merge="append")
            .declare("meta", type=dict, merge="merge_dict")
        )

        # 节点 A 写入 count
        context = apply_state_schema({}, schema, writes={"count": 5})
        assert context["count"] == 5

        # 节点 B 读取上一节点写入的 count，并追加 tags
        assert context["count"] == 5
        context = apply_state_schema(context, schema, writes={"tags": "a"})
        assert context["tags"] == ["a"]

        # 节点 C 继续追加 tags，累积成列表
        context = apply_state_schema(context, schema, writes={"tags": "b"})
        assert context["tags"] == ["a", "b"]

        # 节点 D 合并字典
        context = apply_state_schema(context, schema, writes={"meta": {"a": 1}})
        context = apply_state_schema(context, schema, writes={"meta": {"b": 2}})
        assert context["meta"] == {"a": 1, "b": 2}

    def test_invalid_type_raises_clear_error(self):
        schema = StateSchema().declare("count", type=int, merge="set")
        with pytest.raises(ValueError) as exc_info:
            apply_state_schema({}, schema, writes={"count": "not-an-int"})
        msg = str(exc_info.value)
        assert "count" in msg
        assert "类型不符" in msg
        assert "int" in msg
        assert "str" in msg

    def test_invalid_type_without_writes_raises(self):
        schema = StateSchema().declare("count", type=int, merge="set")
        with pytest.raises(ValueError):
            apply_state_schema({"count": "x"}, schema)

    def test_append_accumulates_list(self):
        schema = StateSchema().declare("history", type=list, merge="append")
        context = apply_state_schema({}, schema, writes={"history": "first"})
        assert context["history"] == ["first"]
        context = apply_state_schema(context, schema, writes={"history": "second"})
        assert context["history"] == ["first", "second"]

    def test_append_on_non_list_raises(self):
        schema = StateSchema().declare("history", type=list, merge="append")
        context = apply_state_schema({}, schema, writes={"history": "first"})
        with pytest.raises(ValueError):
            apply_state_schema({"history": {"not": "a list"}}, schema, writes={"history": "x"})

    def test_merge_dict_merges(self):
        schema = StateSchema().declare("meta", type=dict, merge="merge_dict")
        context = apply_state_schema({}, schema, writes={"meta": {"a": 1}})
        assert context["meta"] == {"a": 1}
        context = apply_state_schema(context, schema, writes={"meta": {"b": 2}})
        assert context["meta"] == {"a": 1, "b": 2}

    def test_merge_dict_with_non_dict_value_raises(self):
        schema = StateSchema().declare("meta", type=dict, merge="merge_dict")
        with pytest.raises(ValueError) as exc_info:
            apply_state_schema({}, schema, writes={"meta": [1, 2]})
        assert "merge_dict" in str(exc_info.value)

    def test_undeclared_key_defaults_to_set_without_type_check(self):
        schema = StateSchema().declare("count", type=int, merge="set")
        context = apply_state_schema({}, schema, writes={"other": "anything"})
        assert context["other"] == "anything"

    def test_default_merge_is_set(self):
        schema = StateSchema().declare("value", type=str)
        context = apply_state_schema({}, schema, writes={"value": "a"})
        context = apply_state_schema(context, schema, writes={"value": "b"})
        assert context["value"] == "b"

    def test_bool_vs_int_distinguished(self):
        schema = StateSchema().declare("flag", type=bool, merge="set")
        assert apply_state_schema({}, schema, writes={"flag": True})["flag"] is True
        with pytest.raises(ValueError):
            apply_state_schema({}, schema, writes={"flag": 1})


# ===========================================================================
# WorkflowEngine 集成 —— 默认 StateSchema
# ===========================================================================


class TestWorkflowEngineStateSchema:
    def test_default_schema_round_trips_through_batch(self):
        engine = _make_engine({"success": True, "data": [{"name": "P1"}]})
        result = engine.run(_simple_plan(), runtime_context={"message": "hello"})
        assert result.success is True
        assert "node_outputs" in result.final_context
        assert isinstance(result.final_context["node_outputs"], dict)
        assert isinstance(result.final_context["workflow_trace"], list)
        assert result.final_context["workflow_status"]["state"] == "completed"

    def test_inject_schema_validation_failure_records_to_node_result(self):
        engine = _make_engine({"success": True, "data": []})
        # node_outputs 被声明为 int，但节点写入的是 dict → 校验失败
        bad_schema = StateSchema().declare("node_outputs", type=int, merge="set")
        result = engine.run(_simple_plan(), state_schema=bad_schema)
        assert result.success is True
        assert result.node_results[0].error
        assert "node_outputs" in result.node_results[0].error

    def test_default_schema_covers_common_keys(self):
        for key in ("node_outputs", "workflow_status", "workflow_trace", "message"):
            assert key in DEFAULT_STATE_SCHEMA.fields
