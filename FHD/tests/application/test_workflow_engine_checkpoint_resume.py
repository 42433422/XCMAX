"""WorkflowEngine checkpoint/resume 与失败节点不入 executed。"""

from __future__ import annotations

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import PlanGraph, WorkflowNode


def test_failed_node_not_in_executed_and_resume_skips_done():
    calls: list[str] = []

    def dispatch(*, tool_id: str, action: str, params: dict, **_kw):
        calls.append(tool_id)
        if tool_id == "b":
            return {"success": False, "error": "boom"}
        return {"success": True, "data": {"node_id": tool_id}}

    plan = PlanGraph(
        plan_id="p-checkpoint",
        intent="test",
        todo_steps=["a", "b", "c"],
        nodes=[
            WorkflowNode(node_id="a", tool_id="a", action="run", depends_on=[]),
            WorkflowNode(node_id="b", tool_id="b", action="run", depends_on=["a"]),
            WorkflowNode(node_id="c", tool_id="c", action="run", depends_on=["b"]),
        ],
    )
    engine = WorkflowEngine(tool_dispatcher=dispatch, parallel_ready_max_workers=1)
    ctx: dict = {}
    first = engine.run(plan, runtime_context=ctx)
    assert first.success is False
    executed = set((first.final_context.get("workflow_status") or {}).get("executed_nodes") or [])
    assert "a" in executed
    assert "b" not in executed

    resumed = engine.resume(plan, first.final_context)
    assert resumed.success is False
    assert calls.count("a") == 1
    assert calls.count("b") >= 2
