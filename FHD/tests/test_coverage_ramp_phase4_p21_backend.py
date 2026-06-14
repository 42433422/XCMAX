"""COVERAGE_RAMP Phase 4 round 21: workflow v1_builtin_nodes (0%→)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.workflow import v1_builtin_nodes as vb
from app.application.workflow.types import PlanGraph, WorkflowNode


# ---------------------------------------------------------------------------
# template resolution + runtime ctx
# ---------------------------------------------------------------------------


def test_resolve_template_string_and_miss() -> None:
    assert vb._resolve_template("hi {{ name }}", {"name": "Bob"}) == "hi Bob"
    # missing path keeps original token
    assert vb._resolve_template("{{ a.b }}", {"a": {}}) == "{{ a.b }}"


def test_resolve_template_dict_list_passthrough() -> None:
    out = vb._resolve_template({"u": "{{ x }}", "n": [1, "{{ x }}"]}, {"x": "Z"})
    assert out == {"u": "Z", "n": [1, "Z"]}
    assert vb._resolve_template(42, {}) == 42


def test_runtime_ctx() -> None:
    assert vb._runtime_ctx({"_runtime_context": {"a": 1}}) == {"a": 1}
    assert vb._runtime_ctx({}) == {}


# ---------------------------------------------------------------------------
# http_request node
# ---------------------------------------------------------------------------


def test_http_missing_url() -> None:
    out = vb.execute_http_request_node({})
    assert out["error_code"] == "missing_url"


def test_http_invalid_url() -> None:
    out = vb.execute_http_request_node({"url": "ftp://x"})
    assert out["error_code"] == "invalid_url"


def test_http_not_allowed_plain_http() -> None:
    out = vb.execute_http_request_node({"url": "http://example.com/api"})
    assert out["error_code"] == "http_not_allowed"


def _mock_client(resp) -> MagicMock:
    client = MagicMock()
    client.request.return_value = resp
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    return cm


def test_http_success_json() -> None:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": 1}
    with patch.object(vb.httpx, "Client", return_value=_mock_client(resp)):
        out = vb.execute_http_request_node({"url": "https://api.test/x", "method": "post"})
    assert out["success"] is True
    assert out["status_code"] == 200
    assert out["data"] == {"ok": 1}


def test_http_localhost_allowed_and_raw_body() -> None:
    resp = MagicMock()
    resp.status_code = 201
    resp.json.side_effect = ValueError("not json")
    resp.text = "plain"
    with patch.object(vb.httpx, "Client", return_value=_mock_client(resp)):
        out = vb.execute_http_request_node({"url": "http://localhost:8000/x"})
    assert out["data"] == {"raw": "plain"}


def test_http_failure_after_retries() -> None:
    client = MagicMock()
    client.request.side_effect = httpx.HTTPError("conn fail")
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    with patch.object(vb.httpx, "Client", return_value=cm):
        out = vb.execute_http_request_node({"url": "https://api.test/x", "retries": 1})
    assert out["error_code"] == "http_failed"
    assert client.request.call_count == 2


# ---------------------------------------------------------------------------
# data_transform node + path helpers
# ---------------------------------------------------------------------------


def test_data_transform_missing_input() -> None:
    out = vb.execute_data_transform_node({})
    assert out["error_code"] == "missing_input"


def test_data_transform_json_string_input_and_mappings() -> None:
    out = vb.execute_data_transform_node(
        {"input": '{"a": {"b": 5}}', "mappings": [{"from": "$.a.b", "to": "x.y"}]}
    )
    assert out["success"] is True
    assert out["data"] == {"x": {"y": 5}}


def test_data_transform_input_from_ctx_with_default() -> None:
    out = vb.execute_data_transform_node(
        {"mappings": [{"from": "missing", "to": "z", "default": 99}]},
        runtime_context={"transform_input": {"a": 1}},
    )
    assert out["data"] == {"z": 99}


def test_data_transform_list_filter() -> None:
    out = vb.execute_data_transform_node(
        {
            "input": [{"v": 1}, {"v": 5}, {"v": 9}],
            "condition": {"op": "gt", "field": "v", "value": 4},
        }
    )
    assert out["data"] == [{"v": 5}, {"v": 9}]


def test_get_by_path_variants() -> None:
    assert vb._get_by_path({"a": [10, 20]}, "a.1") == 20
    assert vb._get_by_path({"a": 1}, "") == {"a": 1}
    assert vb._get_by_path({"a": 1}, "missing") is None
    assert vb._get_by_path([1, 2], "9") is None


def test_set_by_path_nested() -> None:
    obj: dict = {}
    vb._set_by_path(obj, "a.b.c", 7)
    assert obj == {"a": {"b": {"c": 7}}}


def test_eval_condition_ops() -> None:
    assert vb._eval_condition(5, "eq", 5) is True
    assert vb._eval_condition(5, "neq", 4) is True
    assert vb._eval_condition(5, "gt", 4) is True
    assert vb._eval_condition(3, "lt", 4) is True
    assert vb._eval_condition(5, "gte", 5) is True
    assert vb._eval_condition(5, "lte", 5) is True
    assert vb._eval_condition("hello", "contains", "ell") is True
    assert vb._eval_condition(None, "gt", 1) is False  # TypeError -> False
    assert vb._eval_condition(5, "unknown_op", 1) is False


# ---------------------------------------------------------------------------
# loop node
# ---------------------------------------------------------------------------


def _body_plan() -> dict:
    return {
        "nodes": [
            {
                "tool_id": "data_transform",
                "params": {"input": {"x": 1}, "mappings": [{"from": "x", "to": "y"}]},
            }
        ]
    }


def test_loop_missing_body_plan() -> None:
    out = vb.execute_loop_node({"mode": "for_each"})
    assert out["error_code"] == "missing_body_plan"


def test_loop_for_each_invalid_items() -> None:
    out = vb.execute_loop_node({"mode": "for_each", "items": "notalist", "body_plan": _body_plan()})
    assert out["error_code"] == "invalid_items"


def test_loop_for_each_success() -> None:
    out = vb.execute_loop_node(
        {"mode": "for_each", "items": [1, 2], "body_plan": _body_plan()}
    )
    assert out["success"] is True
    assert out["iterations"] == 2


def test_loop_while_runs_until_false() -> None:
    out = vb.execute_loop_node(
        {
            "mode": "while",
            "condition": {"op": "lt", "field": "counter", "value": 2},
            "body_plan": _body_plan(),
        }
    )
    assert out["iterations"] == 2


def test_loop_while_immediately_false() -> None:
    out = vb.execute_loop_node(
        {
            "mode": "while",
            "condition": {"op": "lt", "field": "counter", "value": 0},
            "body_plan": _body_plan(),
        }
    )
    assert out["iterations"] == 0


def test_loop_invalid_mode() -> None:
    out = vb.execute_loop_node({"mode": "bogus", "body_plan": _body_plan()})
    assert out["error_code"] == "invalid_mode"


# ---------------------------------------------------------------------------
# _execute_body_plan + _dispatch_builtin
# ---------------------------------------------------------------------------


def test_execute_body_plan_invalid() -> None:
    out = vb._execute_body_plan("notaplan", {})
    assert out["error_code"] == "invalid_body_plan"


def test_execute_body_plan_empty() -> None:
    out = vb._execute_body_plan({"nodes": []}, {})
    assert out["error_code"] == "empty_body_plan"


def test_dispatch_builtin_workflow_node_object() -> None:
    node = WorkflowNode(
        node_id="n1", tool_id="data_transform", action="x", params={"input": {"a": 1}}
    )
    out = vb._dispatch_builtin(node, {})
    assert out["success"] is True


def test_dispatch_builtin_unsupported() -> None:
    out = vb._dispatch_builtin({"tool_id": "no_such"}, {})
    assert out["error_code"] == "unsupported_builtin"


def test_dispatch_builtin_error(monkeypatch) -> None:
    def _boom(params, ctx):  # noqa: ANN001
        raise ValueError("kaboom")

    monkeypatch.setitem(vb._V1_BUILTIN_NODES, "boom", _boom)
    out = vb._dispatch_builtin({"tool_id": "boom"}, {})
    assert out["error_code"] == "builtin_error"


# ---------------------------------------------------------------------------
# sub_workflow node
# ---------------------------------------------------------------------------


def test_sub_workflow_missing_inline_plan() -> None:
    out = vb.execute_sub_workflow_node({})
    assert out["error_code"] == "missing_inline_plan"


def test_sub_workflow_max_depth() -> None:
    plan = PlanGraph(plan_id="p", intent="i")
    out = vb.execute_sub_workflow_node(
        {"inline_plan": plan, "max_depth": 3}, runtime_context={"sub_workflow_depth": 3}
    )
    assert out["error_code"] == "max_depth"


def test_sub_workflow_invalid_plan() -> None:
    out = vb.execute_sub_workflow_node({"inline_plan": {"not": "a plan"}})
    assert out["error_code"] == "invalid_plan"


def test_sub_workflow_missing_dispatcher() -> None:
    plan = PlanGraph(plan_id="p", intent="i")
    out = vb.execute_sub_workflow_node({"inline_plan": plan})
    assert out["error_code"] == "missing_dispatcher"


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_get_v1_builtin_node_types() -> None:
    types = vb.get_v1_builtin_node_types()
    assert set(types) == {"http_request", "data_transform", "loop", "sub_workflow"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
