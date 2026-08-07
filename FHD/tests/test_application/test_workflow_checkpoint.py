"""Tests for WorkflowCheckpointer + 断点续跑 + 重放/时间旅行。

Cover:
  - 多步顺序工作流在节点 4 中断后，``resume_run`` 从 checkpoint 续跑且不重复执行已完成节点；
  - ``replay_run`` 重放结果与原始运行一致（只读，不再执行工具）；
  - ``list_checkpoints`` 能看到逐步 checkpoint。
"""

from __future__ import annotations

from app.application.workflow.checkpointer import WorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import PlanGraph, WorkflowNode


def _sequential_plan(n: int = 5, plan_id: str = "p_cp") -> PlanGraph:
    """构造 n 个顺序节点（n_i 依赖 n_{i-1}），tool_id/action 唯一便于调度器识别。"""
    nodes: list[WorkflowNode] = []
    for i in range(1, n + 1):
        nodes.append(
            WorkflowNode(
                node_id=f"n{i}",
                tool_id=f"t{i}",
                action=f"a{i}",
                params={},
                risk="low",
                idempotent=True,
                depends_on=[] if i == 1 else [f"n{i - 1}"],
            )
        )
    return PlanGraph(plan_id=plan_id, intent="checkpoint_test", nodes=nodes)


def _plan():
    return _sequential_plan()


def _engine_with_recording(recorder: list[str], fail_on: str | None = None):
    def dispatch(tool_id, action, params):
        key = f"{tool_id}.{action}"
        recorder.append(key)
        if fail_on is not None and key == fail_on:
            return {"success": False, "message": "interrupted at " + key}
        return {"success": True, "data": key}

    return WorkflowEngine(tool_dispatcher=dispatch)


class TestCheckpointerStorage:
    def test_save_get_list_roundtrip(self):
        cp = WorkflowCheckpointer()
        cid = cp.save_checkpoint("p1", 2, {"node_outputs": {"a": 1}}, ["a", "b"])
        got = cp.get_checkpoint("p1", cid)
        assert got is not None
        assert got["plan_id"] == "p1"
        assert got["step_index"] == 2
        assert got["executed_nodes"] == ["a", "b"]
        assert got["runtime_context"]["node_outputs"] == {"a": 1}

        listed = cp.list_checkpoints("p1")
        assert len(listed) == 1
        assert listed[0]["checkpoint_id"] == cid

    def test_get_missing_returns_none(self):
        cp = WorkflowCheckpointer()
        assert cp.get_checkpoint("p1", "nope") is None
        assert cp.latest_checkpoint("p1") is None


class TestWorkflowCheckpointResume:
    def test_resume_after_interrupt_does_not_reexecute_done_nodes(self):
        # 第一次运行：n4 失败中断，checkpoint 保存在 n1..n3 之后。
        cp = WorkflowCheckpointer()
        first_calls: list[str] = []
        engine = _engine_with_recording(first_calls, fail_on="t4.a4")
        plan = _plan()
        first_result = engine.run(plan, checkpointer=cp)
        assert first_result.success is False
        assert "interrupted" in first_result.message

        checkpoints = cp.list_checkpoints(plan.plan_id)
        # n1/n2/n3 每步一个 checkpoint（n4 失败前未保存后续）。
        assert [c["step_index"] for c in checkpoints] == [1, 2, 3]
        resume_ckpt = checkpoints[-1]

        # 恢复：用全新调度器（记录调用），只应执行 n4..n5。
        resume_calls: list[str] = []
        resumer = _engine_with_recording(resume_calls)
        result = resumer.resume_run(plan, resume_ckpt["checkpoint_id"], checkpointer=cp)
        assert result.success is True
        executed = set(result.final_context["workflow_status"]["executed_nodes"])
        assert executed == {"n1", "n2", "n3", "n4", "n5"}
        # 已完成节点不重复执行。
        assert "t1.a1" not in resume_calls
        assert "t2.a2" not in resume_calls
        assert "t3.a3" not in resume_calls
        # 未完成节点执行。
        assert "t4.a4" in resume_calls
        assert "t5.a5" in resume_calls

    def test_resume_restores_runtime_context(self):
        cp = WorkflowCheckpointer()
        engine = _engine_with_recording([], fail_on="t4.a4")
        plan = _plan()
        engine.run(plan, runtime_context={"message": "hello"}, checkpointer=cp)
        resume_ckpt = cp.list_checkpoints(plan.plan_id)[-1]

        resumer = _engine_with_recording([])
        result = resumer.resume_run(plan, resume_ckpt["checkpoint_id"], checkpointer=cp)
        # 恢复的上下文保留 message。
        assert result.final_context["message"] == "hello"
        # 恢复后仍保留 n1..n3 的 node_outputs。
        for i in range(1, 4):
            assert f"n{i}" in result.final_context["node_outputs"]

    def test_resume_missing_checkpoint(self):
        cp = WorkflowCheckpointer()
        engine = _engine_with_recording([])
        result = engine.resume_run(_plan(), "cp-does-not-exist", checkpointer=cp)
        assert result.success is False
        assert "不存在" in result.message


class TestWorkflowCheckpointReplay:
    def test_replay_matches_original_run(self):
        cp = WorkflowCheckpointer()
        calls: list[str] = []
        engine = _engine_with_recording(calls)
        plan = _plan()
        original = engine.run(plan, checkpointer=cp)
        assert original.success is True

        replay = engine.replay_run(plan.plan_id, checkpointer=cp)
        assert replay.success is True
        assert [r.node_id for r in replay.node_results] == [
            r.node_id for r in original.node_results
        ]
        assert [r.output for r in replay.node_results] == [
            r.output for r in original.node_results
        ]
        assert replay.final_context["node_outputs"] == original.final_context["node_outputs"]

    def test_replay_does_not_execute_tools(self):
        cp = WorkflowCheckpointer()
        strikecalls: list[str] = []
        engine = _engine_with_recording(strikecalls)
        plan = _plan()
        engine.run(plan, checkpointer=cp)
        before = list(strikecalls)
        replay = engine.replay_run(plan.plan_id, checkpointer=cp)
        assert replay.success is True
        # 重放不应再调用任何工具。
        assert strikecalls == before


class TestWorkflowCheckpointList:
    def test_list_checkpoints_show_stepwise_progress(self):
        cp = WorkflowCheckpointer()
        engine = _engine_with_recording([])
        plan = _plan()
        engine.run(plan, checkpointer=cp)

        checkpoints = cp.list_checkpoints(plan.plan_id)
        # n1..n5 每步一个 + 最终 completed 一个。
        assert len(checkpoints) == 6
        step_indexes = [c["step_index"] for c in checkpoints]
        assert step_indexes == [1, 2, 3, 4, 5, 5]
        # 逐步 checkpoint 的 executed_nodes 单调增长。
        for c in checkpoints:
            assert c["plan_id"] == plan.plan_id
            assert c["executed_nodes"]