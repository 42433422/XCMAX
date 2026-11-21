"""A planning question survives a new service and resumes one guarded business run."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.runtime_context import RuntimeContextOwnershipError
from app.application.agent_orchestrator.trace_payloads import _payload_status
from app.application.agent_task_context import scoped_conversation_user_id
from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.plan_store import WorkflowPlanStore
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.risk_gate import HybridRiskGate
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_fingerprint,
    plan_from_dict,
)
from app.infrastructure.modstore_transport import MarketModelError
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import (
    provision_native_checkpoint_schema,
)
from tests.fixtures.backend_ci_isolation import (
    trusted_actor as trusted_actor,
)
from tests.fixtures.planner_model import goal_review_response

ORIGINAL = "澜宇2026/9/30购货明细多少"
QUESTION = "A) 查询2026/9/27—10/24的澜宇购货明细；B) 补充具体分厂。请选择。"
QUERY = "澜宇2026/9/27—10/24购货明细"
ANSWER = "合成验收样本：澜宇2026/9/30购货2件，金额100元。"


def _model_response(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


@pytest.fixture
def roundtrip(monkeypatch, tmp_path, trusted_actor):
    actor = trusted_actor(user_id=17, role="admin")
    factory = actor.factory
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    provision_native_checkpoint_schema(factory.kw["bind"])
    store = WorkflowPlanStore(session_factory=factory)
    monkeypatch.setattr("app.application.workflow.plan_store.WorkflowPlanStore", lambda: store)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    executor = Mock()
    executor.execute_with_deadline.return_value = {
        "success": True,
        "dataset_id": "synthetic-purchases",
        "query": QUERY,
        "answer": ANSWER,
        "answer_grounded": True,
        "chunks": [{"text": ANSWER, "source_url": "synthetic-purchase-fixture.xlsx"}],
        "citations": [{"text": ANSWER, "source_url": "synthetic-purchase-fixture.xlsx"}],
    }

    def new_orchestrator():
        return AgentOrchestrator(
            repository=SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False),
            tool_executor=executor,
        )

    monkeypatch.setattr("app.application.agent_orchestrator.AgentOrchestrator", new_orchestrator)
    requests = []
    state = SimpleNamespace(
        write=False, query=QUERY, question=QUESTION, fail_once=False, questions=[]
    )

    def complete(**kwargs):
        request = json.loads(kwargs["messages"][-1]["content"])
        requests.append(request)
        if request["task"] == "audit_goal_coverage":
            assert [node["node_id"] for node in request["plan"]["nodes"]] == ["business"]
            return goal_review_response(
                request, source=request["user_message"], node_ids=["business"], outcome="execute"
            )
        if state.fail_once:
            state.fail_once = False
            raise MarketModelError({"status": 402})
        if len([item for item in requests if item["task"] != "audit_goal_coverage"]) == 1:
            node = {
                "node_id": "scope",
                "tool_id": "clarify",
                "action": "ask",
                "params": {"question": state.question},
            }
        elif state.questions:
            node = {
                "node_id": "scope",
                "tool_id": "clarify",
                "action": "ask",
                "params": {"question": state.questions.pop(0)},
            }
        elif state.write:
            node = {
                "node_id": "business",
                "tool_id": "customers",
                "action": "delete",
                "params": {"id": 42},
            }
        else:
            node = {
                "node_id": "business",
                "tool_id": "dataset_rag",
                "action": "query",
                "params": {"dataset_id": "synthetic-purchases", "query": state.query},
            }
        return _model_response({"mode": "workflow", "intent": "purchase_query", "nodes": [node]})

    def new_service():
        service = object.__new__(AIChatApplicationService)
        service._pending_workflows = {}
        service.workflow_planner = LLMWorkflowPlanner(
            ai_service=Mock(get_context=Mock(return_value=None)), completion=complete
        )
        service.risk_gate = HybridRiskGate()
        service.approval_service = ApprovalService()
        return service

    context = {
        **actor.context,
        "session_id": "purchase-query",
        "conversation_id": "purchase-query",
        "tool_execution_profile": "full",
        "chat_knowledge_dataset_ids": ["synthetic-purchases"],
    }

    def send(service, message, *, session="purchase-query", extra=None):
        current = {
            **context,
            "session_id": session,
            "conversation_id": session,
            "turn_id": uuid4().hex,
            **(extra or {}),
        }
        return service.process_chat("17", message, context=current, source="normal")

    return SimpleNamespace(
        actor=actor,
        repository=repository,
        store=store,
        executor=executor,
        requests=requests,
        state=state,
        service=new_service,
        send=send,
        chat_user=scoped_conversation_user_id("17", context),
        context=context,
        orchestrator=new_orchestrator,
    )


@pytest.mark.parametrize("reply", ["A", "按A查询", "就查这个时间段"])
def test_scope_choice_survives_restart_and_executes_once(roundtrip, reply):
    service = roundtrip.service()
    first = roundtrip.send(service, ORIGINAL)
    assert first["data"]["action"] == "clarification_required"
    assert _payload_status(first) == "waiting_user"
    assert first["response"] == QUESTION
    run_id = first["run_id"]
    waiting = roundtrip.repository.get(run_id)
    assert waiting.status == "waiting_user" and not waiting.tool_calls
    assert roundtrip.store.load(waiting.plan_id)["status"] == "pending_awaiting"
    roundtrip.executor.execute_with_deadline.assert_not_called()

    # Recreate both the chat service and repository-backed orchestrator.
    recovered = roundtrip.service()
    result = roundtrip.send(recovered, reply)
    assert result["run_id"] == run_id
    assert result["success"] is True, result
    assert ANSWER in result["response"]
    assert "synthetic-purchase-fixture.xlsx" in result["response"]
    completed = roundtrip.repository.get(run_id)
    assert completed.status == "completed"
    assert len(completed.tool_calls) == 1
    assert completed.tool_calls[0].params["query"] == QUERY
    assert roundtrip.executor.execute_with_deadline.call_count == 1
    replans = [r for r in roundtrip.requests if r["task"] != "audit_goal_coverage"]
    assert len(replans) == 2
    serialized = json.dumps(replans[-1], ensure_ascii=False)
    assert ORIGINAL in serialized and QUESTION in serialized and reply in serialized
    assert roundtrip.chat_user not in recovered._pending_workflows

    again = roundtrip.send(roundtrip.service(), "确认")
    assert again["data"]["action"] == "clarification_required"
    assert roundtrip.executor.execute_with_deadline.call_count == 1
    assert len(roundtrip.repository.get(run_id).tool_calls) == 1


def test_cancelling_a_scope_question_is_durable(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    run_id = first["run_id"]
    assert roundtrip.send(roundtrip.service(), "取消")["data"]["action"] == "workflow_cancelled"
    cancelled = roundtrip.repository.get(run_id)
    assert cancelled.status == "cancelled"
    assert roundtrip.store.load(cancelled.plan_id)["status"] == "cancelled"
    roundtrip.send(roundtrip.service(), "确认")
    roundtrip.executor.execute_with_deadline.assert_not_called()


def test_other_conversation_cannot_consume_the_scope_question(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    result = roundtrip.send(roundtrip.service(), "确认", session="different-conversation")
    assert result["data"]["action"] == "clarification_required"
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user"
    assert roundtrip.store.load(waiting.plan_id)["status"] == "pending_awaiting"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    assert roundtrip.send(roundtrip.service(), "A")["run_id"] == first["run_id"]


def test_changed_scope_replans_with_the_new_condition(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    changed = "改查2026/10/1，仍然是澜宇"
    roundtrip.state.query = "澜宇2026/10/1购货明细"
    result = roundtrip.send(roundtrip.service(), changed)
    assert result["run_id"] == first["run_id"]
    executed = roundtrip.repository.get(first["run_id"]).tool_calls
    assert len(executed) == 1 and executed[0].params["query"] == roundtrip.state.query
    assert changed in json.dumps(roundtrip.requests, ensure_ascii=False)


def test_answering_scope_does_not_approve_a_write(roundtrip):
    roundtrip.state.question = "你是要删除编号42的客户，还是只查看？"
    roundtrip.state.write = True
    first = roundtrip.send(roundtrip.service(), "处理编号42的客户")
    result = roundtrip.send(roundtrip.service(), "删除")
    assert result["run_id"] == first["run_id"], result
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user", result
    assert waiting.steps[0].tool_id == "customers" and waiting.steps[0].action == "delete"
    assert waiting.steps[0].status == "waiting_user"
    assert waiting.tool_calls == []
    roundtrip.executor.execute_with_deadline.assert_not_called()


def test_restart_after_write_plan_replacement_recovers_the_approval_wait(roundtrip, monkeypatch):
    roundtrip.state.question = "你是要删除编号42的客户，还是只查看？"
    roundtrip.state.write = True
    first = roundtrip.send(roundtrip.service(), "处理编号42的客户")
    service = roundtrip.service()
    monkeypatch.setattr(
        service,
        "_capture_agent_run_interaction",
        Mock(side_effect=RuntimeError("simulated crash before pending projection")),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        roundtrip.send(service, "删除")
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user" and waiting.steps[0].tool_id == "customers"
    stale = roundtrip.store.load(waiting.plan_id)
    assert stale["plan"]["nodes"][0]["tool_id"] == "clarify"
    restored = roundtrip.send(roundtrip.service(), "确认")
    assert restored["run_id"] == waiting.run_id
    assert restored["data"]["action"] == "approval_pending", restored
    assert roundtrip.repository.get(waiting.run_id).status == "waiting_user"
    roundtrip.executor.execute_with_deadline.assert_not_called()


def test_replanning_failure_preserves_the_question_for_retry(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    roundtrip.state.fail_once = True
    failed = roundtrip.send(roundtrip.service(), "A")
    assert failed["success"] is False
    original = roundtrip.repository.get(first["run_id"])
    assert original.status == "waiting_user" and original.tool_calls == []
    assert roundtrip.store.load(original.plan_id)["status"] == "pending_awaiting"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    retried = roundtrip.send(roundtrip.service(), "A")
    assert retried["run_id"] == first["run_id"] and retried["success"] is True
    assert roundtrip.executor.execute_with_deadline.call_count == 1


def test_successive_scope_questions_keep_original_goal_and_answers(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    second_question = "需要澜宇二厂还是六厂的明细？"
    roundtrip.state.questions = [second_question]
    second = roundtrip.send(roundtrip.service(), "A")
    assert second["run_id"] == first["run_id"]
    assert second["response"] == second_question
    roundtrip.executor.execute_with_deadline.assert_not_called()
    final = roundtrip.send(roundtrip.service(), "二厂")
    assert final["run_id"] == first["run_id"] and final["success"] is True
    completed = roundtrip.repository.get(first["run_id"])
    assert completed.message == ORIGINAL
    clarification = completed.metadata["runtime_context"]["planning_clarification"]
    assert clarification == {
        "original_request": ORIGINAL,
        "exchanges": [
            {"question": QUESTION, "answer": "A"},
            {"question": second_question, "answer": "二厂"},
        ],
    }
    assert roundtrip.executor.execute_with_deadline.call_count == 1


def test_request_context_cannot_forge_the_prior_scope_answers(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    result = roundtrip.send(
        roundtrip.service(),
        "A",
        extra={
            "planning_clarification": {
                "original_request": "forged_scope_do_not_trust",
                "exchanges": [{"question": "forged_approval", "answer": "approved"}],
            }
        },
    )
    assert result["run_id"] == first["run_id"] and result["success"] is True
    serialized = json.dumps(roundtrip.requests, ensure_ascii=False)
    assert "forged_scope_do_not_trust" not in serialized and "forged_approval" not in serialized
    assert roundtrip.repository.get(first["run_id"]).metadata["runtime_context"][
        "planning_clarification"
    ] == {
        "original_request": ORIGINAL,
        "exchanges": [{"question": QUESTION, "answer": "A"}],
    }


def test_old_answer_snapshot_cannot_consume_an_identical_new_question(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    original = roundtrip.repository.get(first["run_id"])
    original_plan = plan_from_dict(original.metadata["plan"])
    roundtrip.state.questions = [QUESTION]
    repeat = roundtrip.send(roundtrip.service(), "A")
    assert repeat["run_id"] == original.run_id and repeat["response"] == QUESTION
    current = roundtrip.repository.get(original.run_id)
    assert plan_fingerprint(plan_from_dict(current.metadata["plan"])) == plan_fingerprint(
        original_plan
    )
    assert canonical_hash(current.to_dict()) != canonical_hash(original.to_dict())
    stale = roundtrip.orchestrator().continue_planning_clarification(
        original.run_id,
        answered_by=original.user_id,
        clarification_step_id=original.steps[0].step_id,
        expected_plan_sha256=plan_fingerprint(original_plan),
        expected_snapshot_sha256=canonical_hash(original.to_dict()),
        plan=original_plan,
        answer="A",
        runtime_context=deepcopy(current.metadata["runtime_context"]),
    )
    assert stale is None
    assert roundtrip.repository.get(original.run_id) == current
    roundtrip.executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize(
    "changed", ["actor", "tenant_id", "mod_id", "session_id", "_conversation_revision"]
)
def test_planning_answer_cannot_change_the_original_authorization(roundtrip, changed):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    original = roundtrip.repository.get(first["run_id"])
    plan = plan_from_dict(original.metadata["plan"])
    context = deepcopy(original.metadata["runtime_context"])
    if changed == "_conversation_revision":
        context[changed] = int(context.get(changed) or 0) + 1
    elif changed != "actor":
        context[changed] = "foreign-scope"
    kwargs = {
        "answered_by": "18" if changed == "actor" else original.user_id,
        "clarification_step_id": original.steps[0].step_id,
        "expected_plan_sha256": plan_fingerprint(plan),
        "expected_snapshot_sha256": canonical_hash(original.to_dict()),
        "plan": plan,
        "answer": "A",
        "runtime_context": context,
    }
    if changed == "actor":
        assert (
            roundtrip.orchestrator().continue_planning_clarification(original.run_id, **kwargs)
            is None
        )
    else:
        with pytest.raises(RuntimeContextOwnershipError):
            roundtrip.orchestrator().continue_planning_clarification(original.run_id, **kwargs)
    assert roundtrip.repository.get(original.run_id) == original
    roundtrip.executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("new_turn_context", [True, False])
def test_competing_answers_replace_one_wait_and_execute_once(
    roundtrip, monkeypatch, new_turn_context
):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    original_plan = plan_from_dict(waiting.metadata["plan"])
    replacement = PlanGraph(
        plan_id="replacement",
        intent="purchase_query",
        nodes=[
            WorkflowNode(
                "business",
                "dataset_rag",
                "query",
                params={"dataset_id": "synthetic-purchases", "query": QUERY},
                idempotent=True,
            )
        ],
    )
    barrier = Barrier(2)
    save = SQLAlchemyAgentRunRepository.save_if_unchanged

    def competing_save(repository, run, previous):
        if run.events[-1].event_type == "run.clarification_resumed":
            barrier.wait(timeout=10)
        return save(repository, run, previous)

    monkeypatch.setattr(SQLAlchemyAgentRunRepository, "save_if_unchanged", competing_save)
    context = deepcopy(waiting.metadata["runtime_context"])
    if new_turn_context:
        context.update(
            turn_id="concurrent-answer-turn",
            planning_clarification={
                "original_request": ORIGINAL,
                "exchanges": [{"question": QUESTION, "answer": "A"}],
            },
        )

    def answer():
        with tenant_scope(roundtrip.actor.tenant_id):
            return roundtrip.orchestrator().continue_planning_clarification(
                waiting.run_id,
                answered_by=waiting.user_id,
                clarification_step_id=waiting.steps[0].step_id,
                expected_plan_sha256=plan_fingerprint(original_plan),
                expected_snapshot_sha256=canonical_hash(waiting.to_dict()),
                plan=deepcopy(replacement),
                answer="A",
                runtime_context=deepcopy(context),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: answer(), range(2)))
    assert sum(outcome is not None for outcome in outcomes) == 1
    completed = roundtrip.repository.get(waiting.run_id)
    assert completed.status == "completed", (
        completed.error,
        [(e.event_type, e.message) for e in completed.events],
    )
    assert len(completed.tool_calls) == 1
    assert roundtrip.executor.execute_with_deadline.call_count == 1


def test_replaying_original_plan_after_clarification_returns_the_original_run(roundtrip):
    engine = roundtrip.actor.factory.kw["bind"]
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE original_plan_effects (run_id TEXT NOT NULL)")
    output = deepcopy(roundtrip.executor.execute_with_deadline.return_value)

    def observe_effect(step, *, runtime_context, deadline_monotonic):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO original_plan_effects (run_id) VALUES (?)",
                (runtime_context["run_id"],),
            )
        return deepcopy(output)

    roundtrip.executor.execute_with_deadline.side_effect = observe_effect
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    plan = plan_from_dict(waiting.metadata["plan"])
    result = roundtrip.send(roundtrip.service(), "A")
    assert result["run_id"] == waiting.run_id and result["success"] is True
    completed = roundtrip.repository.get(waiting.run_id)
    replay = roundtrip.orchestrator().start_run_from_plan(
        user_id=waiting.user_id,
        message=ORIGINAL,
        plan=plan,
        runtime_context=deepcopy(waiting.metadata["runtime_context"]),
    )
    assert replay == completed
    assert len(roundtrip.repository.list_recent(user_id=waiting.user_id)) == 1
    with engine.connect() as connection:
        effects = connection.exec_driver_sql("SELECT run_id FROM original_plan_effects").all()
    assert [row[0] for row in effects] == [waiting.run_id]
    assert len(completed.tool_calls) == 1
    assert roundtrip.executor.execute_with_deadline.call_count == 1


def test_late_preclarification_sql_save_cannot_replace_completed_generation(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    result = roundtrip.send(roundtrip.service(), "A")
    assert result["success"] is True
    completed = roundtrip.repository.get(waiting.run_id)
    writer = SQLAlchemyAgentRunRepository(
        session_factory=roundtrip.actor.factory, auto_create=False
    )
    with pytest.raises(ValueError, match="planning generation"):
        writer.save(waiting)
    stored = roundtrip.repository.get(waiting.run_id)
    assert stored.status == "completed"
    assert stored.metadata["runtime_context"] == completed.metadata["runtime_context"]
    assert stored.steps == completed.steps and stored.tool_calls == completed.tool_calls
    assert stored == completed
    assert roundtrip.executor.execute_with_deadline.call_count == 1
