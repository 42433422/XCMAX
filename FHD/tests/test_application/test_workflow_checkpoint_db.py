"""``DatabaseWorkflowCheckpointer`` 单元测试 — 数据库持久化 Checkpoint。

Cover:
  - save/get/list/latest 走 ``workflow_checkpoints`` 表往返；
  - 用「全新 checkpointer 实例」续跑（模拟跨进程），已完成节点不重复执行；
  - replay 从 DB checkpoint 只读重放且不再执行工具。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.workflow.checkpointer import DatabaseWorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.db.base import Base


@pytest.fixture()
def session_factory():
    """内存 SQLite + 全量 metadata（StaticPool 共享单连接）。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _sequential_plan(n: int = 5, plan_id: str = "p_cp_db") -> PlanGraph:
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
    return PlanGraph(plan_id=plan_id, intent="checkpoint_db_test", nodes=nodes)


def _engine_with_recording(recorder: list[str], fail_on: str | None = None):
    def dispatch(tool_id, action, params):
        key = f"{tool_id}.{action}"
        recorder.append(key)
        if fail_on is not None and key == fail_on:
            return {"success": False, "message": "interrupted at " + key}
        return {"success": True, "data": key}

    return WorkflowEngine(tool_dispatcher=dispatch)


class TestDatabaseCheckpointerStorage:
    def test_save_get_list_roundtrip(self, session_factory):
        cp = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        cid = cp.save_checkpoint("p1", 2, {"node_outputs": {"a": 1}}, ["a", "b"], blocked=["c"])
        got = cp.get_checkpoint("p1", cid)
        assert got is not None
        assert got["plan_id"] == "p1"
        assert got["step_index"] == 2
        assert got["executed_nodes"] == ["a", "b"]
        assert got["blocked"] == ["c"]
        assert got["runtime_context"]["node_outputs"] == {"a": 1}

        listed = cp.list_checkpoints("p1")
        assert len(listed) == 1
        assert listed[0]["checkpoint_id"] == cid

    def test_get_missing_returns_none(self, session_factory):
        cp = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        assert cp.get_checkpoint("p1", "nope") is None
        assert cp.latest_checkpoint("p1") is None

    def test_latest_orders_by_step_index(self, session_factory):
        cp = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        cp.save_checkpoint("p1", 1, {"k": 1}, ["a"])
        cp.save_checkpoint("p1", 3, {"k": 3}, ["a", "b", "c"])
        cp.save_checkpoint("p1", 2, {"k": 2}, ["a", "b"])
        assert cp.latest_checkpoint("p1")["step_index"] == 3
        assert [c["step_index"] for c in cp.list_checkpoints("p1")] == [1, 2, 3]


class TestDatabaseWorkflowCheckpointResume:
    def test_resume_with_new_instance_does_not_reexecute_done_nodes(self, session_factory):
        cp = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        first_calls: list[str] = []
        engine = _engine_with_recording(first_calls, fail_on="t4.a4")
        plan = _plan()
        first_result = engine.run(plan, runtime_context={"message": "hello"}, checkpointer=cp)
        assert first_result.success is False
        assert "interrupted" in first_result.message

        checkpoints = cp.list_checkpoints(plan.plan_id)
        assert [c["step_index"] for c in checkpoints] == [1, 2, 3]
        resume_ckpt = checkpoints[-1]

        # 用全新 checkpointer 实例（模拟跨进程）续跑，不重复执行已完成节点。
        cp2 = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        saved = cp2.get_checkpoint(plan.plan_id, resume_ckpt["checkpoint_id"])
        assert saved is not None

        resume_calls: list[str] = []
        resumer = _engine_with_recording(resume_calls)
        result = resumer.resume_run(plan, resume_ckpt["checkpoint_id"], checkpointer=cp2)
        assert result.success is True
        executed = set(result.final_context["workflow_status"]["executed_nodes"])
        assert executed == {"n1", "n2", "n3", "n4", "n5"}
        assert "t1.a1" not in resume_calls
        assert "t2.a2" not in resume_calls
        assert "t3.a3" not in resume_calls
        assert "t4.a4" in resume_calls
        assert "t5.a5" in resume_calls
        # 恢复的 runtime_context 保留 message。
        assert result.final_context["message"] == "hello"


class TestDatabaseWorkflowCheckpointReplay:
    def test_replay_from_db_checkpoint_matches_original(self, session_factory):
        cp = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        calls: list[str] = []
        engine = _engine_with_recording(calls)
        plan = _plan()
        original = engine.run(plan, checkpointer=cp)
        assert original.success is True

        # 全新实例只读重放，结果与原始一致且不再执行工具。
        cp2 = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        before = list(calls)
        replay = engine.replay_run(plan.plan_id, checkpointer=cp2)
        assert replay.success is True
        assert [r.node_id for r in replay.node_results] == [
            r.node_id for r in original.node_results
        ]
        assert [r.output for r in replay.node_results] == [
            r.output for r in original.node_results
        ]
        assert replay.final_context["node_outputs"] == original.final_context["node_outputs"]
        assert calls == before


def _plan():
    return _sequential_plan()