"""Workflow read concurrency, authenticated scope and serial writes."""

from __future__ import annotations

import threading
import time

import pytest

from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime as WorkflowEngine


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
        rendezvous = threading.Barrier(3, timeout=3)
        active = 0
        max_active = 0

        def dispatch(tool_id, action, params):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            rendezvous.wait()
            with lock:
                active -= 1
            return {"success": True, "data": [tool_id]}

        engine = _engine_with_dispatch(dispatch)
        plan = _plan([_read_node("n1"), _read_node("n2"), _read_node("n3")])

        result = engine.run(plan)

        assert result.success is True
        assert len(result.node_results) == 3
        assert max_active >= 3

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
        result = engine.run(_plan(nodes))
        assert result.success is True
        assert max_active == 1

    @pytest.mark.parametrize("tenant_id", [None, 41, 42])
    def test_parallel_results_merged_into_node_outputs(self, tenant_id):
        def dispatch(tool_id, action, params):
            return {"success": True, "data": params.get("marker"), "tenant": current_tenant_id()}

        engine = _engine_with_dispatch(dispatch)
        nodes = [
            _read_node("n1", marker="a"),
            _read_node("n2", marker="b"),
            _read_node("n3", marker="c"),
        ]
        with tenant_scope(tenant_id):
            result = engine.run(_plan(nodes))

        outputs = result.final_context["node_outputs"]
        assert outputs["n1"]["data"] == "a"
        assert outputs["n2"]["data"] == "b"
        assert outputs["n3"]["data"] == "c"
        assert {output["tenant"] for output in outputs.values()} == {tenant_id}
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
        result = engine.run(plan, parallel=False)
        assert result.success is True
        assert max_active == 1
        assert "n1" in result.final_context["node_outputs"]
        assert "n2" in result.final_context["node_outputs"]


@pytest.mark.parametrize("tool,action", [("products", "delete"), ("unknown_tool", "query")])
def test_model_read_flags_cannot_grant_parallel_mutation(tool, action):
    from app.infrastructure.workflow.langgraph_runtime import _ReadersWriterGate

    forged = WorkflowNode(
        node_id="forged", tool_id=tool, action=action, risk="low", idempotent=True
    )
    assert _ReadersWriterGate.is_reader(forged) is False
    assert _ReadersWriterGate.is_reader(_read_node("legitimate")) is True


@pytest.mark.parametrize("parallel", [False, True])
def test_failed_employee_read_only_blocks_its_dependency_branch(parallel):
    calls = []
    nodes = [
        WorkflowNode(
            node_id=node_id,
            tool_id="employee",
            action="context",
            params={"employee_id": node_id, "task": "review"},
            risk="low",
            idempotent=True,
            depends_on=deps,
        )
        for node_id, deps in (
            ("failed", []),
            ("dependent", ["failed"]),
            ("descendant", ["dependent"]),
            ("independent", []),
            ("independent_child", ["independent"]),
        )
    ]

    def dispatch(_tool, _action, params):
        node_id = params["employee_id"]
        calls.append(node_id)
        return {"success": node_id != "failed", "employee_id": node_id}

    result = WorkflowEngine(dispatch).run(_plan(nodes), parallel=parallel)
    assert result.success is False
    assert set(calls) == {"failed", "independent", "independent_child"}
    assert set(result.final_context["blocked"]) == {"dependent", "descendant"}
    status = result.final_context["workflow_status"]
    assert status["partial_completion"] is True
    assert status["completed_nodes"] == ["independent", "independent_child"]
    assert status["failed_nodes"] == ["failed"]
    assert status["remaining_nodes"] == ["dependent", "descendant", "failed"]


@pytest.mark.parametrize(
    "failure",
    [
        {"success": False, "outcome": "unknown", "reconciliation_required": True},
        {"success": True, "requires_approval": True},
        {"success": False, "execution_state": "paused"},
        {"success": False, "execution_state": "cancelled"},
        {"success": False, "error_code": "tool_permission_denied", "retryable": False},
        {"success": False, "error_code": "budget_exceeded"},
        {"success": False, "error_code": "result_verification_required"},
        pytest.param(
            {"success": True, "verification": {"accepted": False, "status": "unverified"}},
            id="verification_fence",
        ),
        pytest.param(
            {
                "success": True,
                "artifact_postcondition": {"accepted": False, "status": "inconclusive"},
            },
            id="artifact_verification_fence",
        ),
        {"success": False, "error_code": "unknown_failure_class"},
        {"success": False, "error_code": {"code": "tool_timeout"}},
        {"success": False, "error_code": []},
        {"success": False, "error_code": 0},
    ],
)
def test_control_and_unsettled_failures_do_not_release_independent_work(failure):
    calls = []

    def dispatch(_tool, _action, params):
        calls.append(params["marker"])
        return failure if params["marker"] == "failed" else {"success": True}

    result = WorkflowEngine(dispatch).run(
        _plan([_read_node("failed", "failed"), _read_node("independent", "independent")]),
        parallel=False,
    )
    assert result.success is False
    assert calls == ["failed"]


def test_low_risk_idempotent_artifact_writes_are_exclusive():
    active = maximum = 0
    lock = threading.Lock()

    def dispatch(_tool, _action, _params):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {"success": True}

    nodes = [
        WorkflowNode(
            node_id=node_id,
            tool_id="excel_analyzer",
            action="analyze",
            params={"file_path": "input.xlsx", "output_json": "same-output.json"},
            risk="low",
            idempotent=True,
        )
        for node_id in ("one", "two")
    ]
    assert WorkflowEngine(dispatch).run(_plan(nodes)).success is True
    assert maximum == 1
