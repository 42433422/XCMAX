"""Workflow plans persist and resume safely across sessions."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.workflow.checkpointer import DatabaseWorkflowCheckpointer
from app.application.workflow.plan_store import WorkflowPlanStore
from app.application.workflow.workflow_types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    plan_from_dict,
    plan_to_dict,
)
from app.db.db_base import Base
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime as WorkflowEngine


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
    return PlanGraph(
        "wp-sess-abc12345",
        "low_stock_suggest",
        todo_steps=["查库存", "采购建议"],
        nodes=[
            WorkflowNode(
                "n1",
                "inv",
                "query",
                risk="low",
                idempotent=True,
                branches=[Branch(target="n2", condition={"inv.low_stock": True})],
            ),
            WorkflowNode("n2", "po", "suggest", risk="low", idempotent=True, depends_on=["n1"]),
        ],
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
            plan=plan,
            runtime_context={"user_id": "u1", "message": "hi"},
            status="pending_awaiting",
            user_id="u1",
            session_id="sess",
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
        store.save(
            plan=plan,
            runtime_context={"user_id": "u1"},
            status="pending_awaiting",
            user_id="u1",
        )
        store.save(
            plan=plan_from_dict({**plan_to_dict(plan), "plan_id": "wp-other-1"}),
            runtime_context={"user_id": "u1"},
            status="succeeded",
            user_id="u1",
        )
        active = store.list_active("u1")
        assert [p["plan_id"] for p in active] == ["wp-sess-abc12345"]
        store.update_status(plan.plan_id, "cancelled")
        assert store.list_active("u1") == []
        assert store.load(plan.plan_id)["status"] == "cancelled"

    def test_session_filter_preserves_other_sessions_and_user_ownership(self, session_factory):
        store = WorkflowPlanStore(session_factory=session_factory)
        for owner, session in [("u1", "old"), ("u1", "new"), ("u2", "new")]:
            plan = plan_from_dict({**plan_to_dict(_plan()), "plan_id": f"{owner}-{session}"})
            store.save(plan=plan, status="pending_awaiting", user_id=owner, session_id=session)
        assert [row["plan_id"] for row in store.list_active("u1", session_id="new")] == ["u1-new"]
        assert len(store.list_active("u1")) == 2

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
        first = engine.run(
            plan,
            runtime_context={"user_id": "u1", "session_id": "sess"},
            checkpointer=cp,
        )
        assert first.success is False
        store.save(
            plan=plan,
            runtime_context={"user_id": "u1", "session_id": "sess"},
            status="pending_awaiting",
            user_id="u1",
        )

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
            node_id=f"n{i}",
            tool_id=f"t{i}",
            action="tool",
            params={},
            risk="low",
            idempotent=True,
            depends_on=[] if i == 1 else [f"n{i - 1}"],
        )
        for i in range(1, 4)
    ]
    return PlanGraph(plan_id="wp-sess-abc12345", intent="long_task", nodes=nodes)


@pytest.mark.parametrize("required", [False, True])
def test_real_integrity_failure_without_committed_row_has_no_strict_receipt(
    session_factory, monkeypatch, required
):
    from sqlalchemy.exc import IntegrityError

    store = WorkflowPlanStore(session_factory=session_factory)

    def fail(self):
        raise IntegrityError("commit", {}, RuntimeError("controlled insert race"))

    monkeypatch.setattr(session_factory.class_, "commit", fail)
    if required:
        with pytest.raises(RuntimeError, match="did not commit"):
            store.save(plan=_plan(), require_commit=True)
    else:
        assert store.save(plan=_plan()) == _plan().plan_id
    assert store.load(_plan().plan_id) is None


@pytest.mark.parametrize("status", ["pending_awaiting", "cancelled", "succeeded"])
def test_session_persistence_reports_real_commit_failure(session_factory, monkeypatch, status):
    from sqlalchemy.exc import OperationalError

    store = WorkflowPlanStore(session_factory=session_factory)

    def fail(_self):
        raise OperationalError("commit", {}, RuntimeError("controlled commit failure"))

    monkeypatch.setattr(session_factory.class_, "commit", fail)
    with pytest.raises(OperationalError, match="controlled commit failure"):
        store.save(
            plan=_plan(), runtime_context={"user_id": "u1"}, status=status, require_commit=True
        )
    assert store.load(_plan().plan_id) is None


@pytest.mark.parametrize("status", ["queued", "retrying", "paused", "blocked", "unknown"])
def test_unfinished_plan_remains_observable_without_resuming(session_factory, status):
    store = WorkflowPlanStore(session_factory=session_factory)
    store.save(
        plan=_plan(),
        runtime_context={"agent_run_id": "original"},
        status=status,
        user_id="owner",
        session_id="same",
    )
    assert store.list_active("owner", session_id="same")[0]["status"] == status
    loaded = store.load(_plan().plan_id)
    assert loaded["runtime_context"] == {"agent_run_id": "original"}
    assert loaded["status"] == status
