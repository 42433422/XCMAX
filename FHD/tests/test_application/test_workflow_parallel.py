"""Tests for parallel fan-out in WorkflowEngine._run_batch.

Covers:
  - 三个无依赖只读节点并发执行（可休眠的假工具模拟，断言并发生效）
  - 写/高风险节点不被并发执行（保持串行）
  - 并发结果正确合并到 runtime_context["node_outputs"]
  - parallel=False 回退串行，行为一致
"""

from __future__ import annotations

import threading
import time

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import PlanGraph, WorkflowNode


def _engine_with_dispatch(dispatch):
    return WorkflowEngine(tool_dispatcher=dispatch)


def _plan(nodes):
    return PlanGraph(
        plan_id="p1",
        intent="parallel_test",
        todo_steps=["t"],
        nodes=nodes,
        risk_level="low",
    )


def _read_node(node_id: str, marker: str = "", **kw) -> WorkflowNode:
    return WorkflowNode(
        node_id=node_id,
        tool_id="products",
        action="query",
        params={"marker": marker},
        risk="low",
        idempotent=True,
        **kw,
    )


class TestWorkflowParallel:
    def test_read_only_nodes_run_concurrently(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        def dispatch(tool_id, action, params):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            # 模拟耗时查询；串行约 0.6s，并发应显著更短
            time.sleep(0.2)
            with lock:
                active -= 1
            return {"success": True, "data": [tool_id]}

        engine = _engine_with_dispatch(dispatch)
        plan = _plan([_read_node("n1"), _read_node("n2"), _read_node("n3")])

        t0 = time.perf_counter()
        result = engine._run_batch(plan)
        elapsed = time.perf_counter() - t0

        assert result.success is True
        assert len(result.node_results) == 3
        # 三个只读节点确实并发执行（并发深度达到 3）
        assert max_active >= 3
        # 总耗时明显小于串行之和（0.6s）
        assert elapsed < 0.5

    def test_write_nodes_run_serially(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        def dispatch(tool_id, action, params):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"success": True}

        engine = _engine_with_dispatch(dispatch)
        nodes = [
            WorkflowNode(
                node_id="w1",
                tool_id="business_db",
                action="write",
                params={},
                risk="high",
                idempotent=False,
            ),
            WorkflowNode(
                node_id="w2",
                tool_id="business_db",
                action="write",
                params={},
                risk="high",
                idempotent=False,
            ),
        ]
        result = engine._run_batch(_plan(nodes))
        assert result.success is True
        # 写/高风险节点始终串行，同一时刻最多 1 个在执行
        assert max_active == 1

    def test_parallel_results_merged_into_node_outputs(self):
        def dispatch(tool_id, action, params):
            return {"success": True, "data": params.get("marker")}

        engine = _engine_with_dispatch(dispatch)
        nodes = [
            _read_node("n1", marker="a"),
            _read_node("n2", marker="b"),
            _read_node("n3", marker="c"),
        ]
        result = engine._run_batch(_plan(nodes))

        outputs = result.final_context["node_outputs"]
        assert outputs["n1"]["data"] == "a"
        assert outputs["n2"]["data"] == "b"
        assert outputs["n3"]["data"] == "c"
        assert len(result.final_context["workflow_trace"]) == 3

    def test_parallel_false_falls_back_to_serial(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        def dispatch(tool_id, action, params):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return {"success": True, "data": [tool_id]}

        engine = _engine_with_dispatch(dispatch)
        plan = _plan([_read_node("n1"), _read_node("n2")])
        result = engine._run_batch(plan, parallel=False)
        assert result.success is True
        # 关闭并行后即使只读节点也串行
        assert max_active == 1
        assert "n1" in result.final_context["node_outputs"]
        assert "n2" in result.final_context["node_outputs"]
