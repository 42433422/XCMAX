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
from tests.fixtures.backend_ci_isolation import provision_native_checkpoint_schema
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_planning_clarification_roundtrip import roundtrip as roundtrip


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

    def test_returning_to_original_session_restores_same_run_after_slot_overwrite(
        self, session_factory
    ):
        from unittest.mock import Mock, patch

        from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
        from app.application.ai_chat_app_service import AIChatApplicationService

        store = WorkflowPlanStore(session_factory=session_factory)
        svc = object.__new__(AIChatApplicationService)
        svc._pending_workflows = {}
        with patch("app.application.workflow.plan_store.WorkflowPlanStore", return_value=store):
            for session in ("A", "B"):
                plan = plan_from_dict({**plan_to_dict(_plan()), "plan_id": f"plan-{session}"})
                svc._pending_workflows["u1"] = {
                    "plan": plan,
                    "runtime_context": {"user_id": "u1", "session_id": session},
                    "agent_run_id": f"run-{session}",
                    "approval_required": session == "B",
                    "approval_nodes": [{"node_id": "n2"}] if session == "B" else [],
                }
                svc._persist_plan_state(
                    plan,
                    svc._pending_workflows["u1"]["runtime_context"],
                    "pending_awaiting",
                )
            assert svc._pending_workflows["u1"]["agent_run_id"] == "run-B"
            orchestrator = Mock()
            plan_a = plan_from_dict({**plan_to_dict(_plan()), "plan_id": "plan-A"})
            plan_b = plan_from_dict({**plan_to_dict(_plan()), "plan_id": "plan-B"})
            orchestrator.get_run.side_effect = lambda run_id: AgentRun(
                user_id="u1",
                message="long task",
                run_id=run_id,
                status="waiting_user",
                plan_id="plan-B" if run_id == "run-B" else "plan-A",
                intent="long_task",
                metadata={"plan": plan_to_dict(plan_b if run_id == "run-B" else plan_a)},
                steps=[
                    AgentStep(
                        node_id=node.node_id,
                        tool_id=node.tool_id,
                        action=node.action,
                        depends_on=node.depends_on,
                        status="waiting_user" if node.node_id == "n2" else "completed",
                    )
                    for node in plan_a.nodes
                ],
            )
            orchestrator.continue_run.return_value = AgentRun(
                user_id="u1",
                message="long task",
                run_id="run-A",
                status="completed",
                plan_id="plan-A",
                intent="long_task",
                metadata={"plan": plan_to_dict(plan_a)},
            )
            svc._format_agent_run_response = Mock(return_value={"run_id": "run-A"})
            with patch(
                "app.application.agent_orchestrator.AgentOrchestrator",
                return_value=orchestrator,
            ):
                handled, response = svc._resume_pending_dynamic_workflow(
                    "u1", "确认", "确认", {"session_id": "A"}
                )
            assert handled and response["run_id"] == "run-A"
            orchestrator.continue_run.assert_called_once_with(
                "run-A",
                approved_by="u1",
                runtime_context={"user_id": "u1", "session_id": "A"},
            )
            orchestrator.start_run_from_plan.assert_not_called()
            assert (
                store.load("plan-B")["runtime_context"]["pending_confirmation"]["agent_run_id"]
                == "run-B"
            )

            with patch(
                "app.application.agent_orchestrator.AgentOrchestrator",
                return_value=orchestrator,
            ):
                assert svc._hydrate_pending_workflow("u1", "B")
            assert svc._pending_workflows["u1"]["approval_required"] is True
            assert svc._pending_workflows["u1"]["approval_nodes"] == [{"node_id": "n2"}]

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


@pytest.mark.parametrize("failed_save", [False, True])
def test_normal_cancel_is_durable_and_save_failure_preserves_pending(
    session_factory, monkeypatch, failed_save
):
    import app.application.workflow.plan_store as module
    from app.application.ai_chat_app_service import AIChatApplicationService

    store = WorkflowPlanStore(session_factory=session_factory)
    plan = _plan()
    context = {"user_id": "u1", "session_id": "sess", "task_id": "original-task"}
    store.save(
        plan=plan,
        runtime_context=context,
        status="pending_awaiting",
        user_id="u1",
        session_id="sess",
    )
    service = object.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    monkeypatch.setattr(module, "WorkflowPlanStore", lambda: store)
    if failed_save:
        from sqlalchemy.exc import OperationalError

        def fail(self):
            raise OperationalError("commit", {}, RuntimeError("controlled commit failure"))

        monkeypatch.setattr(session_factory.class_, "commit", fail)
    result = service._try_handle_dynamic_workflow(
        "u1", "取消", "normal", {"session_id": "sess"}, {}
    )
    assert result["success"] is not failed_save
    assert store.load(plan.plan_id)["status"] == (
        "pending_awaiting" if failed_save else "cancelled"
    )
    assert store.load(plan.plan_id)["runtime_context"] == context
    assert ("u1" in service._pending_workflows) == failed_save
    reopened = object.__new__(AIChatApplicationService)
    reopened._pending_workflows = {}
    assert reopened._hydrate_pending_workflow("u1", "sess") is failed_save
    if not failed_save:
        assert result["data"]["data"] == {
            "plan_id": plan.plan_id,
            "task_id": "original-task",
        }


@pytest.mark.parametrize("projection", ["missing", "running", "shadowed"])
def test_waiting_run_survives_missing_or_lagging_plan_projection(
    roundtrip, monkeypatch, projection
):
    from app.db.models.workflow import WorkflowPlan
    from tests.test_application.test_planning_clarification_roundtrip import ANSWER, ORIGINAL

    service = roundtrip.service()
    persist = service._persist_plan_state
    monkeypatch.setattr(
        service,
        "_persist_plan_state",
        lambda plan, context, status, **kw: (
            False if status == "pending_awaiting" else persist(plan, context, status, **kw)
        ),
    )
    first = roundtrip.send(service, ORIGINAL)
    assert first["data"]["action"] == "workflow_persistence_failed"
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user" and not waiting.tool_calls
    plan = plan_from_dict(waiting.metadata["plan"])
    with roundtrip.actor.factory.begin() as db:
        db.query(WorkflowPlan).filter_by(plan_id=plan.plan_id).delete()
    if projection != "missing":
        roundtrip.store.save(
            plan=plan,
            runtime_context=waiting.metadata["runtime_context"],
            status="running" if projection == "running" else "pending_awaiting",
            user_id=roundtrip.chat_user,
            session_id="purchase-query",
        )
    if projection == "shadowed":
        newer = plan_from_dict({**plan_to_dict(plan), "plan_id": "newer-running-plan"})
        roundtrip.store.save(
            plan=newer,
            status="running",
            user_id=roundtrip.chat_user,
            session_id="purchase-query",
        )
    result = roundtrip.send(roundtrip.service(), "A")
    assert result["run_id"] == waiting.run_id
    assert result["success"] and ANSWER in result["response"]
    assert roundtrip.repository.get(waiting.run_id).status == "completed"
    assert roundtrip.executor.execute_with_deadline.call_count == 1


def test_run_recovery_ignores_other_owners_tenants_mods_sessions_and_revisions(roundtrip):
    from copy import deepcopy

    from app.db.models.workflow import WorkflowPlan
    from tests.test_application.test_planning_clarification_roundtrip import ORIGINAL

    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    with roundtrip.actor.factory.begin() as db:
        db.query(WorkflowPlan).filter_by(plan_id=waiting.plan_id).delete()
    for key, value in (
        ("tenant_id", "another-tenant"),
        ("mod_id", "another-mod"),
        ("session_id", "another-conversation"),
        ("_conversation_revision", 1),
        ("user_id", "another-owner"),
    ):
        other = deepcopy(waiting)
        other.run_id = f"unrelated-{key}"
        other.events = []
        other.metadata["task_context"] = {"task_id": other.run_id}
        other.metadata["runtime_context"][key] = value
        if key == "user_id":
            other.user_id = value
        roundtrip.repository.save(other)
    result = roundtrip.send(roundtrip.service(), "A")
    assert result["success"] and result["run_id"] == waiting.run_id
    assert roundtrip.executor.execute_with_deadline.call_count == 1


def test_ambiguous_authoritative_wait_requires_an_explicit_plan_card(roundtrip):
    from copy import deepcopy

    from tests.test_application.test_planning_clarification_roundtrip import ORIGINAL

    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    other = deepcopy(waiting)
    other.run_id = "another-waiting-run"
    other.plan_id = "another-waiting-plan"
    other.metadata["plan"]["plan_id"] = other.plan_id
    other.metadata["task_context"] = {"task_id": other.run_id}
    other.events = []
    roundtrip.repository.save(other)
    reopened = roundtrip.service()
    reply = roundtrip.send(reopened, "A")
    assert reply["data"]["action"] == "workflow_resume_ambiguous"
    assert roundtrip.repository.get(waiting.run_id).status == "waiting_user"
    assert roundtrip.repository.get(other.run_id).status == "waiting_user"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    assert len(roundtrip.requests) == 1
    selected = roundtrip.send(reopened, "A", extra={"expected_workflow_plan_id": waiting.plan_id})
    assert selected["success"] and selected["run_id"] == waiting.run_id
    assert roundtrip.executor.execute_with_deadline.call_count == 1
    assert roundtrip.repository.get(other.run_id).status == "waiting_user"


def test_recovery_query_failure_does_not_dispatch_a_new_task(roundtrip, monkeypatch):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from tests.test_application.test_planning_clarification_roundtrip import ORIGINAL

    first = roundtrip.send(roundtrip.service(), ORIGINAL)

    def unavailable(*args, **kwargs):
        raise OSError("controlled recovery read failure")

    monkeypatch.setattr(SQLAlchemyAgentRunRepository, "list_recent", unavailable)
    reply = roundtrip.send(roundtrip.service(), "A")
    assert reply["data"]["action"] == "workflow_resume_failed"
    assert roundtrip.repository.get(first["run_id"]).status == "waiting_user"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    assert len(roundtrip.requests) == 1


@pytest.mark.parametrize("invalid_plan", [None, {"plan_id": "broken", "nodes": []}])
def test_authoritative_wait_with_missing_or_invalid_plan_cannot_start_over(roundtrip, invalid_plan):
    import json

    from app.db.models.agent import AgentRunRecord
    from tests.test_application.test_planning_clarification_roundtrip import ORIGINAL

    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    waiting.metadata["plan"] = invalid_plan
    with roundtrip.actor.factory.begin() as db:
        db.get(AgentRunRecord, waiting.run_id).payload_json = json.dumps(waiting.to_dict())
    reply = roundtrip.send(roundtrip.service(), "A")
    assert reply["data"]["action"] == "workflow_resume_failed"
    assert roundtrip.repository.get(waiting.run_id).status == "waiting_user"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    assert len(roundtrip.requests) == 1


def test_recovering_without_plan_projection_does_not_extend_clarification_ttl(roundtrip):
    import json
    from datetime import UTC, datetime, timedelta

    from app.db.models.agent import AgentRunRecord
    from app.db.models.workflow import WorkflowPlan
    from tests.test_application.test_planning_clarification_roundtrip import ORIGINAL

    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    for event in waiting.events:
        if event.event_type == "step.clarification_required":
            event.created_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with roundtrip.actor.factory.begin() as db:
        # Age the persisted fixture; ordinary saves deliberately preserve audit events.
        db.get(AgentRunRecord, waiting.run_id).payload_json = json.dumps(waiting.to_dict())
        db.query(WorkflowPlan).filter_by(plan_id=waiting.plan_id).delete()
    reply = roundtrip.send(roundtrip.service(), "A")
    assert reply["data"]["action"] == "workflow_clarification_expired"
    assert roundtrip.repository.get(waiting.run_id).status == "cancelled"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    assert len(roundtrip.requests) == 1


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


@pytest.mark.parametrize("user_id,session_id", [("u2", "sess"), ("u1", "other")])
@pytest.mark.parametrize("message", ["取消", "确认"])
def test_restarted_control_never_loads_another_owner_or_session(
    session_factory, monkeypatch, user_id, session_id, message
):
    from unittest.mock import Mock

    import app.application.workflow.plan_store as module
    from app.application.ai_chat_app_service import AIChatApplicationService

    store = WorkflowPlanStore(session_factory=session_factory)
    plan = _plan()
    store.save(
        plan=plan,
        runtime_context={"user_id": "u1", "session_id": "sess"},
        status="pending_awaiting",
        user_id="u1",
        session_id="sess",
    )
    monkeypatch.setattr(module, "WorkflowPlanStore", lambda: store)
    service = object.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    # No matching pending task: retain the normal model-selection path, not a
    # fabricated cancellation/confirmation success for somebody else's plan.
    model_reply = {"success": False, "message": "clarification required"}
    service._dispatch_model_selection = Mock(return_value=model_reply)
    result = service._try_handle_dynamic_workflow(
        user_id, message, "normal", {"session_id": session_id}, {}
    )
    assert result is model_reply
    service._dispatch_model_selection.assert_called_once()
    assert service._pending_workflows == {}
    assert store.load(plan.plan_id)["status"] == "pending_awaiting"


def test_restarted_confirmation_without_execution_record_stays_fail_closed(
    session_factory, monkeypatch
):
    from unittest.mock import Mock

    import app.application.workflow.plan_store as module
    from app.application.ai_chat_app_service import AIChatApplicationService

    store = WorkflowPlanStore(session_factory=session_factory)
    plan = _plan()
    store.save(
        plan=plan,
        runtime_context={"user_id": "u1", "session_id": "sess"},
        status="pending_awaiting",
        user_id="u1",
        session_id="sess",
    )
    monkeypatch.setattr(module, "WorkflowPlanStore", lambda: store)
    service = object.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    service._dispatch_model_selection = Mock(side_effect=AssertionError("must not replan"))
    result = service._try_handle_dynamic_workflow(
        "u1", "确认", "normal", {"session_id": "sess"}, {}
    )
    assert result["success"] is False
    assert result["data"]["action"] == "workflow_resume_failed"
    assert store.load(plan.plan_id)["status"] == "pending_awaiting"
    assert service._pending_workflows["u1"]["plan"].plan_id == plan.plan_id
    service._dispatch_model_selection.assert_not_called()


@pytest.mark.parametrize("scoped", [False, True])
def test_restarted_confirmation_resumes_signed_durable_agent_run(
    monkeypatch, tmp_path, trusted_actor, scoped
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_task_context import scoped_conversation_user_id
    from app.application.ai_chat.dialogue_memory import prepare_chat_turn
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.employee_runtime.task_continuity import ledger_path

    actor = trusted_actor(user_id=17, role="admin")
    session_factory = actor.factory
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    context = {**actor.context, "user_id": "17", "session_id": "sess"}
    prepare_chat_turn("resume", context)
    chat_user = scoped_conversation_user_id("17", context) if scoped else "17"
    plan = PlanGraph(
        plan_id="restart-confirm-plan",
        intent="employee",
        nodes=[
            WorkflowNode(
                "employee",
                "employee",
                "execute",
                params={
                    "employee_id": "clerk",
                    "task": "start continuity",
                    "continuity_action": "start",
                    "goal": "verify resumed confirmation",
                },
            )
        ],
    )
    repository = SQLAlchemyAgentRunRepository(session_factory=session_factory)
    run = AgentRun(user_id="17", message="resume", metadata={"runtime_context": context})
    AgentOrchestrator(repository=repository)._apply_plan(run, plan)
    run.status = "waiting_user"
    run.steps[0].status = "waiting_user"
    repository.save(run)
    store = WorkflowPlanStore(session_factory=session_factory)
    monkeypatch.setattr("app.application.workflow.plan_store.WorkflowPlanStore", lambda: store)
    if scoped:
        original = object.__new__(AIChatApplicationService)
        original._pending_workflows = {
            chat_user: {
                "plan": plan,
                "runtime_context": context,
                "agent_run_id": run.run_id,
            }
        }
        assert original._persist_plan_state(plan, context, "pending_awaiting")
        saved = store.load(plan.plan_id)
        assert saved["user_id"] == chat_user
        assert saved["runtime_context"]["user_id"] == "17"
        assert saved["runtime_context"]["pending_confirmation"]["agent_run_id"] == run.run_id
    else:
        store.save(
            plan=plan,
            runtime_context={
                **context,
                "pending_confirmation": {"agent_run_id": run.run_id},
            },
            status="pending_awaiting",
            user_id="17",
            session_id="sess",
        )
    # New service and repository objects, not the old in-memory run instance.
    provision_native_checkpoint_schema(session_factory.kw["bind"])
    fresh = SQLAlchemyAgentRunRepository(session_factory=session_factory, auto_create=False)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator",
        lambda: AgentOrchestrator(repository=fresh),
    )
    service = object.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    service._try_handle_dynamic_workflow(chat_user, "确认", "normal", {"session_id": "sess"}, {})
    completed = fresh.get(run.run_id)
    assert completed.status == "completed", completed.to_dict()
    assert completed.tool_calls and completed.tool_calls[0].output["success"]
    assert ledger_path(tmp_path).is_file()
    assert store.load(plan.plan_id)["status"] == "succeeded"
    receipt = ledger_path(tmp_path).read_bytes()
    handled, response = service._resume_pending_dynamic_workflow(
        chat_user, "确认", "确认", {"session_id": "sess"}
    )
    assert handled and response["data"]["action"] == "clarification_required"
    assert ledger_path(tmp_path).read_bytes() == receipt
    assert len(fresh.get(run.run_id).tool_calls) == len(completed.tool_calls)


@pytest.mark.parametrize("status", ["pending_awaiting", "cancelled", "succeeded"])
def test_session_persistence_reports_real_commit_failure(session_factory, monkeypatch, status):
    from unittest.mock import Mock

    from sqlalchemy.exc import OperationalError

    from app.application.ai_chat.workflow_session import WorkflowSession

    store = WorkflowPlanStore(session_factory=session_factory)

    def fail(_self):
        raise OperationalError("commit", {}, RuntimeError("controlled commit failure"))

    monkeypatch.setattr(session_factory.class_, "commit", fail)
    session = WorkflowSession({}, Mock(), store=store)
    assert not session.persist_plan_state(_plan(), {"user_id": "u1"}, status)
    assert store.load(_plan().plan_id) is None


@pytest.mark.parametrize("status", ["queued", "retrying", "paused", "blocked", "unknown"])
def test_unfinished_plan_remains_observable_without_resuming(session_factory, status):
    from unittest.mock import Mock

    from app.application.ai_chat.workflow_session import WorkflowSession

    store = WorkflowPlanStore(session_factory=session_factory)
    store.save(
        plan=_plan(),
        runtime_context={"agent_run_id": "original"},
        status=status,
        user_id="owner",
        session_id="same",
    )
    assert store.list_active("owner", session_id="same")[0]["status"] == status
    pending = {}
    assert not WorkflowSession(pending, Mock(), store=store).hydrate_pending_workflow(
        "owner", "same"
    )
    assert pending == {}
