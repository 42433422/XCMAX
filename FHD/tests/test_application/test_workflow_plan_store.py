"""``WorkflowPlanStore`` + 跨会话续跑测试。

Cover:
  - plan_to_dict / plan_from_dict 往返一致（含条件边）；
  - WorkflowPlanStore save/load/load_plan/list_active/update_status；
  - 跨会话续跑：新 store 实例（模拟换会话/重启）载入计划后从 DB checkpoint 续跑，
    已完成节点不重复执行。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.workflow.checkpointer import DatabaseWorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.plan_store import WorkflowPlanStore
from app.application.workflow.types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    plan_from_dict,
    plan_to_dict,
)
from app.db.base import Base


@pytest.fixture()
def session_factory():
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


def _plan() -> PlanGraph:
    nodes = [
        WorkflowNode(
            node_id="n1", tool_id="inv", action="query", params={}, risk="low",
            idempotent=True, depends_on=[], branches=[
                Branch(target="n2", condition={"inv.low_stock": True}),
            ],
        ),
        WorkflowNode(
            node_id="n2", tool_id="po", action="suggest", params={}, risk="low",
            idempotent=True, depends_on=["n1"],
        ),
    ]
    return PlanGraph(
        plan_id="wp-sess-abc12345", intent="low_stock_suggest",
        todo_steps=["查库存", "采购建议"], nodes=nodes,
    )


def _engine_with_recording(recorder: list[str], fail_on: str | None = None):
    def dispatch(tool_id, action, params):
        key = f"{tool_id}.{action}"
        recorder.append(key)
        if fail_on is not None and key == fail_on:
            return {"success": False, "message": "interrupted"}
        return {"success": True, "data": key}

    return WorkflowEngine(tool_dispatcher=dispatch)


class TestPlanSerialization:
    def test_roundtrip_preserves_conditional_edges(self):
        original = _plan()
        restored = plan_from_dict(plan_to_dict(original))
        assert restored.plan_id == original.plan_id
        assert restored.intent == original.intent
        assert restored.todo_steps == original.todo_steps
        assert [n.node_id for n in restored.nodes] == ["n1", "n2"]
        assert restored.nodes[0].branches[0].target == "n2"
        assert restored.nodes[0].branches[0].condition == {"inv.low_stock": True}
        assert restored.nodes[1].depends_on == ["n1"]

    def test_from_dict_empty_returns_none(self):
        assert plan_from_dict(None) is None
        assert plan_from_dict({}) is None


class TestWorkflowPlanStore:
    def test_save_load_roundtrip(self, session_factory):
        store = WorkflowPlanStore(session_factory=session_factory)
        plan = _plan()
        store.save(
            plan=plan, runtime_context={"user_id": "u1", "message": "hi"},
            status="pending_awaiting", user_id="u1", session_id="sess",
        )
        data = store.load(plan.plan_id)
        assert data is not None
        assert data["status"] == "pending_awaiting"
        assert data["user_id"] == "u1"
        assert data["session_id"] == "sess"
        assert data["runtime_context"]["message"] == "hi"
        restored = store.load_plan(plan.plan_id)
        assert restored.intent == "low_stock_suggest"
        assert restored.nodes[0].tool_id == "inv"

    def test_list_active_and_update_status(self, session_factory):
        store = WorkflowPlanStore(session_factory=session_factory)
        plan = _plan()
        store.save(plan=plan, runtime_context={"user_id": "u1"}, status="pending_awaiting", user_id="u1")
        store.save(plan=plan_from_dict({**plan_to_dict(plan), "plan_id": "wp-other-1"}), runtime_context={"user_id": "u1"}, status="succeeded", user_id="u1")
        active = store.list_active("u1")
        assert [p["plan_id"] for p in active] == ["wp-sess-abc12345"]
        store.update_status(plan.plan_id, "cancelled")
        assert store.list_active("u1") == []
        assert store.load(plan.plan_id)["status"] == "cancelled"

    def test_upsert_same_plan_id_updates(self, session_factory):
        store = WorkflowPlanStore(session_factory=session_factory)
        plan = _plan()
        store.save(plan=plan, runtime_context={"v": 1}, status="running", user_id="u1")
        store.save(plan=plan, runtime_context={"v": 2}, status="succeeded", user_id="u1")
        data = store.load(plan.plan_id)
        assert data["status"] == "succeeded"
        assert data["runtime_context"] == {"v": 2}


class TestCrossSessionResume:
    def test_resume_with_new_store_instance(self, session_factory):
        cp = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        store = WorkflowPlanStore(session_factory=session_factory)
        plan = _sequential_plan()

        # 会话 A：运行到 n2 中断（n3 未执行），同时计划落库。
        first_calls: list[str] = []
        engine = _engine_with_recording(first_calls, fail_on="t3.tool")
        first = engine.run(plan, runtime_context={"user_id": "u1", "session_id": "sess"}, checkpointer=cp)
        assert first.success is False
        store.save(plan=plan, runtime_context={"user_id": "u1", "session_id": "sess"}, status="pending_awaiting", user_id="u1")

        # 会话 B：全新 store + checkpointer 实例，载入计划，从最新 checkpoint 续跑。
        store2 = WorkflowPlanStore(session_factory=session_factory)
        cp2 = DatabaseWorkflowCheckpointer(session_factory=session_factory)
        restored = store2.load_plan(plan.plan_id)
        assert restored is not None
        latest = cp2.latest_checkpoint(plan.plan_id)
        assert latest is not None

        resume_calls: list[str] = []
        resumer = _engine_with_recording(resume_calls)
        result = resumer.resume_run(restored, latest["checkpoint_id"], checkpointer=cp2)
        assert result.success is True
        executed = set(result.final_context["workflow_status"]["executed_nodes"])
        assert executed == {"n1", "n2", "n3"}
        # n1/n2 已完成不重复执行，仅执行 n3。
        assert "t1.tool" not in resume_calls
        assert "t2.tool" not in resume_calls
        assert "t3.tool" in resume_calls


def _sequential_plan() -> PlanGraph:
    nodes = [
        WorkflowNode(
            node_id=f"n{i}", tool_id=f"t{i}", action="tool", params={}, risk="low",
            idempotent=True, depends_on=[] if i == 1 else [f"n{i - 1}"],
        )
        for i in range(1, 4)
    ]
    return PlanGraph(plan_id="wp-sess-abc12345", intent="long_task", nodes=nodes)