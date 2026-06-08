"""工作流新节点类型测试。"""

import json
from unittest.mock import MagicMock, patch

import pytest

from modstore_server.workflow_engine import WorkflowEngine


def _make_node(node_type: str, config: dict, node_id: int = 1, name: str = "test"):
    node = MagicMock()
    node.id = node_id
    node.node_type = node_type
    node.name = name
    node.config = json.dumps(config)
    return node


class TestHttpRequestNode:
    def test_mock_returns_sandbox(self):
        engine = WorkflowEngine()
        node = _make_node("http_request", {"url": "https://example.com", "method": "GET"})
        result = engine._execute_http_request_mock(node, {}, {"url": "https://example.com"})
        assert "http_status" in result
        assert result["http_status"] == 200

    def test_missing_url_raises(self):
        engine = WorkflowEngine()
        node = _make_node("http_request", {"method": "GET"})
        with pytest.raises(ValueError, match="缺少 url"):
            engine._execute_http_request_node(node, {}, {"method": "GET"})


class TestCodeExecuteNode:
    def test_simple_code(self):
        engine = WorkflowEngine()
        node = _make_node("code_execute", {"code": "result = input.get('x', 0) + 1"})
        result = engine._execute_code_execute_node(
            node, {"x": 5}, {"code": "result = input.get('x', 0) + 1"}
        )
        assert result["code_result"] == 6

    def test_missing_code_raises(self):
        engine = WorkflowEngine()
        node = _make_node("code_execute", {})
        with pytest.raises(ValueError, match="缺少 code"):
            engine._execute_code_execute_node(node, {}, {})

    def test_mock_returns_sandbox(self):
        engine = WorkflowEngine()
        node = _make_node("code_execute", {"code": "pass"})
        result = engine._execute_code_execute_mock(node, {}, {})
        assert result["code_result"]["sandbox"] is True


class TestDataTransformNode:
    def test_field_map(self):
        engine = WorkflowEngine()
        config = {
            "transforms": [{"type": "field_map", "mapping": {"new_name": "old_name"}}],
            "output_var": "result",
        }
        result = engine._execute_data_transform_node(
            _make_node("data_transform", config),
            {"old_name": "hello"},
            config,
        )
        assert result["result"]["new_name"] == "hello"

    def test_type_cast(self):
        engine = WorkflowEngine()
        config = {
            "transforms": [{"type": "type_cast", "field": "count", "cast_to": "integer"}],
            "output_var": "result",
        }
        result = engine._execute_data_transform_node(
            _make_node("data_transform", config),
            {"count": "42"},
            config,
        )
        assert result["result"]["count"] == 42

    def test_mock_returns_sandbox(self):
        engine = WorkflowEngine()
        result = engine._execute_data_transform_mock(_make_node("data_transform", {}), {}, {})
        assert result["transform_result"]["sandbox"] is True


class TestLoopNode:
    def test_for_each(self):
        engine = WorkflowEngine()
        config = {
            "loop_type": "for_each",
            "items_path": "{{ items }}",
            "max_iterations": 100,
            "output_var": "loop_result",
        }
        result = engine._execute_loop_node(
            _make_node("loop", config),
            {"items": ["a", "b", "c"]},
            config,
        )
        assert result["loop_count"] == 3
        assert len(result["loop_result"]) == 3

    def test_for_each_respects_max_iterations(self):
        engine = WorkflowEngine()
        config = {
            "loop_type": "for_each",
            "items_path": "{{ items }}",
            "max_iterations": 2,
            "output_var": "loop_result",
        }
        result = engine._execute_loop_node(
            _make_node("loop", config),
            {"items": ["a", "b", "c", "d"]},
            config,
        )
        assert result["loop_count"] == 2

    def test_mock_returns_sandbox(self):
        engine = WorkflowEngine()
        result = engine._execute_loop_mock(_make_node("loop", {}), {}, {})
        assert result["loop_result"][0]["sandbox"] is True


class TestParallelNode:
    def test_pass_branch(self):
        engine = WorkflowEngine()
        config = {
            "branches": [{"name": "branch_a", "type": "pass"}],
            "output_var": "parallel_result",
        }
        result = engine._execute_parallel_node(
            _make_node("parallel", config),
            {"key": "value"},
            config,
        )
        assert "branch_a" in result["parallel_result"]
        assert result["parallel_result"]["branch_a"]["status"] == "completed"

    def test_mock_returns_sandbox(self):
        engine = WorkflowEngine()
        result = engine._execute_parallel_mock(_make_node("parallel", {}), {}, {})
        assert result["parallel_result"]["sandbox"]["status"] == "completed"


class TestSubWorkflowNode:
    def test_missing_workflow_id_raises(self):
        engine = WorkflowEngine()
        node = _make_node("sub_workflow", {})
        with pytest.raises(ValueError, match="缺少 workflow_id"):
            engine._execute_sub_workflow_node(node, {}, {})

    def test_depth_limit(self):
        engine = WorkflowEngine()
        config = {"workflow_id": 99, "max_depth": 1}
        node = _make_node("sub_workflow", config)
        with pytest.raises(RuntimeError, match="递归深度"):
            engine._execute_sub_workflow_node(node, {"_sub_workflow_depth": 1}, config)

    def test_mock_returns_sandbox(self):
        engine = WorkflowEngine()
        result = engine._execute_sub_workflow_mock(
            _make_node("sub_workflow", {"workflow_id": 99}), {}, {}
        )
        assert result["sub_workflow_result"]["sandbox"] is True
