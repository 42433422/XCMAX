"""A planning question survives a new service and resumes one guarded business run."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.runtime_context import RuntimeContextOwnershipError
from app.application.agent_orchestrator.trace_payloads import _payload_status
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_fingerprint,
    plan_from_dict,
)
from app.infrastructure.modstore_transport import MarketModelError
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import (
    trusted_actor as trusted_actor,
)
from tests.fixtures.planning_clarification import (
    ANSWER,
    ORIGINAL,
    QUERY,
    QUESTION,
    _planning_requests,
)
from tests.fixtures.planning_clarification import roundtrip as roundtrip


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
    replans = _planning_requests(roundtrip.requests)
    assert len(replans) == 2
    serialized = json.dumps(replans[-1], ensure_ascii=False)
    assert ORIGINAL in serialized and QUESTION in serialized and reply in serialized
    assert roundtrip.chat_user not in recovered._pending_workflows

    again = roundtrip.send(roundtrip.service(), "确认")
    assert again["data"]["action"] == "clarification_required"
    assert roundtrip.executor.execute_with_deadline.call_count == 1
    assert len(roundtrip.repository.get(run_id).tool_calls) == 1


@pytest.mark.parametrize("extra", [None, {"attachment_upload_ids": []}])
def test_cancelling_a_scope_question_is_durable(roundtrip, extra):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    run_id = first["run_id"]
    assert (
        roundtrip.send(roundtrip.service(), "取消", extra=extra)["data"]["action"]
        == "workflow_cancelled"
    )
    cancelled = roundtrip.repository.get(run_id)
    assert cancelled.status == "cancelled"
    assert roundtrip.store.load(cancelled.plan_id)["status"] == "cancelled"
    roundtrip.send(roundtrip.service(), "确认")
    roundtrip.executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("side_question", ["向量检索有什么作用？", "能解释一下毛利率吗？", "继续"])
def test_side_question_keeps_wait_and_resumes_original_run_after_restart(roundtrip, side_question):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    roundtrip.state.classification = {"turn_kind": "new_goal", "resolved": False, "parameters": {}}
    roundtrip.state.reply = "这是对插问的独立说明。"
    reply = roundtrip.send(roundtrip.service(), side_question)
    assert reply["success"] is True, reply
    assert reply["response"] == roundtrip.state.reply
    assert "_workflow_new_goal" not in json.dumps(reply)
    assert reply["data"]["pending_workflow"] == {
        "run_id": waiting.run_id,
        "plan_id": waiting.plan_id,
        "status": "waiting_user",
    }
    assert roundtrip.repository.get(waiting.run_id) == waiting
    assert roundtrip.store.load(waiting.plan_id)["status"] == "pending_awaiting"
    other_runs = [r for r in roundtrip.repository.list_recent() if r.run_id != waiting.run_id]
    assert all(r.status == "completed" and not r.tool_calls for r in other_runs)
    classification = [r for r in roundtrip.requests if r["task"] == "classify_clarification_turn"]
    assert len(classification) == 1
    assert classification[0]["current_question"] == QUESTION
    assert classification[0]["user_answer"] == side_question
    assert _planning_requests(roundtrip.requests)[-1]["user_message"] == side_question
    roundtrip.executor.execute_with_deadline.assert_not_called()

    roundtrip.state.classification = {"turn_kind": "answer", "resolved": True, "parameters": {}}
    roundtrip.state.reply = None
    resumed = roundtrip.send(roundtrip.service(), "A")
    assert resumed["run_id"] == waiting.run_id and resumed["success"] is True
    completed = roundtrip.repository.get(waiting.run_id)
    assert completed.metadata["runtime_context"]["planning_clarification"]["exchanges"] == [
        {"question": QUESTION, "answer": "A"}
    ]
    roundtrip.executor.execute_with_deadline.assert_called_once()


@pytest.mark.parametrize("turn_kind", ["answer", "unclear"])
def test_uncertain_scope_answer_leaves_wait_and_does_not_replan(roundtrip, turn_kind):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    roundtrip.state.classification = {"turn_kind": turn_kind, "resolved": False, "parameters": {}}
    response = roundtrip.send(roundtrip.service(), "还没确定")
    assert response["success"] is True
    assert response["data"]["action"] == "clarification_required"
    assert response["data"]["data"]["turn_kind"] == turn_kind
    assert len(_planning_requests(roundtrip.requests)) == 1
    assert roundtrip.repository.get(waiting.run_id) == waiting
    assert response["run_id"] == response["agent_run_id"] == waiting.run_id
    assert len(roundtrip.repository.list_recent()) == 1
    roundtrip.executor.execute_with_deadline.assert_not_called()
    roundtrip.state.classification = {"turn_kind": "answer", "resolved": True, "parameters": {}}
    resumed = roundtrip.send(roundtrip.service(), "A")
    assert resumed["run_id"] == waiting.run_id and resumed["success"] is True
    roundtrip.executor.execute_with_deadline.assert_called_once()


def test_new_business_goal_completes_without_consuming_original_wait(roundtrip):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    roundtrip.state.classification = {"turn_kind": "new_goal", "resolved": False, "parameters": {}}
    side_request = "另查乙客户的采购汇总"
    roundtrip.state.query = side_request
    side = roundtrip.send(roundtrip.service(), side_request)
    assert side["success"] is True and side["run_id"] != waiting.run_id
    assert roundtrip.repository.get(waiting.run_id) == waiting
    completed_side = roundtrip.repository.get(side["run_id"])
    assert completed_side.status == "completed"
    assert "planning_clarification" not in completed_side.metadata["runtime_context"]
    assert completed_side.tool_calls[0].params["query"] == side_request
    roundtrip.state.classification = {"turn_kind": "answer", "resolved": True, "parameters": {}}
    roundtrip.state.query = QUERY
    resumed = roundtrip.send(roundtrip.service(), "A")
    assert resumed["run_id"] == waiting.run_id and resumed["success"] is True
    assert roundtrip.executor.execute_with_deadline.call_count == 2


@pytest.mark.parametrize("failure", ["balance", "timeout", "context", "invalid"])
def test_classification_failure_is_not_missing_user_input_and_preserves_wait(roundtrip, failure):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    waiting = roundtrip.repository.get(first["run_id"])
    if failure == "balance":
        roundtrip.state.classification_error = MarketModelError(
            {"status": 402, "message": "secret"}
        )
        expected_code = "model_balance_insufficient"
    elif failure == "timeout":
        roundtrip.state.classification_error = TimeoutError("secret provider URL")
        expected_code = "model_timeout"
    elif failure == "context":
        from app.application.agent_orchestrator.context_window_manager import ContextWindowExceeded

        roundtrip.state.classification_error = ContextWindowExceeded("当前模型窗口不足")
        expected_code = "context_window_exceeded"
    else:
        roundtrip.state.classification = {
            "turn_kind": "new_goal",
            "resolved": True,
            "parameters": {},
        }
        expected_code = "model_response_invalid"
    failed = roundtrip.send(roundtrip.service(), "A")
    assert failed["success"] is False, failed
    assert failed["data"]["action"] == "workflow_clarification_failed"
    assert failed["data"]["error_code"] == expected_code
    assert failed["data"]["planning_failure_stage"] == "clarification"
    assert failed["execution_state"] == "waiting_user"
    assert failed["run_id"] == failed["agent_run_id"] == waiting.run_id
    assert "secret" not in json.dumps(failed)
    assert len(_planning_requests(roundtrip.requests)) == 1
    assert roundtrip.repository.get(waiting.run_id) == waiting
    roundtrip.executor.execute_with_deadline.assert_not_called()
    roundtrip.state.classification_error = None
    roundtrip.state.classification = {"turn_kind": "answer", "resolved": True, "parameters": {}}
    resumed = roundtrip.send(roundtrip.service(), "A")
    assert resumed["run_id"] == waiting.run_id and resumed["success"] is True
    roundtrip.executor.execute_with_deadline.assert_called_once()


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
    roundtrip.state.question = "你是要删除编号42的产品，还是只查看？"
    roundtrip.state.write = True
    first = roundtrip.send(roundtrip.service(), "处理编号42的产品")
    result = roundtrip.send(roundtrip.service(), "删除")
    assert result["run_id"] == first["run_id"], result
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user", result
    assert waiting.steps[0].tool_id == "products" and waiting.steps[0].action == "delete"
    assert waiting.steps[0].status == "waiting_user"
    assert waiting.tool_calls == []
    roundtrip.executor.execute_with_deadline.assert_not_called()


def test_restart_after_write_plan_replacement_recovers_the_approval_wait(roundtrip, monkeypatch):
    roundtrip.state.question = "你是要删除编号42的产品，还是只查看？"
    roundtrip.state.write = True
    first = roundtrip.send(roundtrip.service(), "处理编号42的产品")
    service = roundtrip.service()
    monkeypatch.setattr(
        service,
        "_capture_agent_run_interaction",
        Mock(side_effect=RuntimeError("simulated crash before pending projection")),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        roundtrip.send(service, "删除")
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user" and waiting.steps[0].tool_id == "products"
    stale = roundtrip.store.load(waiting.plan_id)
    assert stale["plan"]["nodes"][0]["tool_id"] == "clarify"
    restored = roundtrip.send(roundtrip.service(), "确认")
    assert restored["run_id"] == waiting.run_id
    assert restored["data"]["action"] == "approval_pending", restored
    assert roundtrip.repository.get(waiting.run_id).status == "waiting_user"
    roundtrip.executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("failure", ["model", "context"])
def test_replanning_failure_preserves_the_question_for_retry(roundtrip, failure):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    roundtrip.state.fail_once = failure
    failed = roundtrip.send(roundtrip.service(), "A")
    assert failed["success"] is False
    assert failed["run_id"] == failed["agent_run_id"] == first["run_id"]
    if failure == "context":
        assert failed["data"]["error_code"] == "context_window_exceeded"
    original = roundtrip.repository.get(first["run_id"])
    assert original.status == "waiting_user" and original.tool_calls == []
    assert roundtrip.store.load(original.plan_id)["status"] == "pending_awaiting"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    retried = roundtrip.send(roundtrip.service(), "A")
    assert retried["run_id"] == first["run_id"] and retried["success"] is True
    assert roundtrip.executor.execute_with_deadline.call_count == 1


@pytest.mark.parametrize(
    ("rejection", "code"),
    [
        ("binding", "elt_attachment_binding_failed"),
        ("prohibited", "workflow_action_prohibited"),
        ("malformed_risk", "workflow_risk_denied"),
        ("denied", "workflow_risk_denied"),
        ("missing_plan", "workflow_confirmation_stale"),
        ("cas", "workflow_confirmation_stale"),
        ("recent_record", "missing_recent_database_target"),
    ],
)
def test_replanning_rejection_keeps_the_verified_run(roundtrip, monkeypatch, rejection, code):
    from app.application.elt.batch_continuation import BatchContinuationBlocked
    from app.domain.autonomy.risk_types import ProhibitedActionError, RiskDecision

    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    original = roundtrip.repository.get(first["run_id"])
    service = roundtrip.service()
    answer = "A"
    with monkeypatch.context() as blocked:
        if rejection == "binding":
            boundary = Mock(side_effect=BatchContinuationBlocked("附件绑定已失效"))
            blocked.setattr("app.application.elt.batch_continuation.bind_durable_batch", boundary)
        elif rejection in {"prohibited", "malformed_risk", "denied"}:
            decision = RiskDecision(False, "风险策略拒绝", denied_nodes=["business"])
            if rejection == "malformed_risk":
                decision.blocking_nodes = "business"
            boundary = Mock(return_value=decision)
            if rejection == "prohibited":
                boundary.side_effect = ProhibitedActionError("dataset_rag.query", "禁止执行")
            blocked.setattr(service.risk_gate, "evaluate", boundary)
        elif rejection == "missing_plan":
            resume = service._resume_pending_dynamic_workflow

            def lose_plan(*args, **kwargs):
                handled, result = resume(*args, **kwargs)
                # The durable run was verified, but its local snapshot became unusable.
                result["_planning_clarification"]["run"].metadata.pop("plan")
                return handled, result

            boundary = Mock(side_effect=lose_plan)
            blocked.setattr(service, "_resume_pending_dynamic_workflow", boundary)
        elif rejection == "cas":
            boundary = Mock(return_value=False)
            blocked.setattr(SQLAlchemyAgentRunRepository, "save_if_unchanged", boundary)
        else:
            answer = "查询刚才那条产品记录"
            boundary = Mock(return_value=None)
            blocked.setattr(
                "app.domain.shared_services.tools_workflow_registered.get_recent_business_db_target",
                boundary,
            )
        failed = roundtrip.send(
            service, answer, extra={"run_id": "forged-run", "agent_run_id": "forged-agent-run"}
        )
        boundary.assert_called_once()
    if rejection == "recent_record":
        assert failed["data"]["data"]["reason"] == code
    else:
        assert failed["success"] is False and failed["execution_state"] == "blocked"
        assert failed["data"]["error_code"] == code
        assert failed["data"]["execution_started"] is False
    assert failed["run_id"] == failed["agent_run_id"] == original.run_id
    assert roundtrip.repository.get(original.run_id) == original
    assert {run.run_id for run in roundtrip.repository.list_recent()} == {original.run_id}
    assert roundtrip.store.load(original.plan_id)["status"] == "pending_awaiting"
    roundtrip.executor.execute_with_deadline.assert_not_called()
    retried = roundtrip.send(roundtrip.service(), "A")
    assert retried["run_id"] == original.run_id and retried["success"] is True
    roundtrip.executor.execute_with_deadline.assert_called_once()


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


@pytest.mark.parametrize("turns", [20, 100])
def test_long_clarification_chain_preserves_every_accepted_answer(roundtrip, turns):
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    questions = [QUESTION, *[f"请确认第 {index} 项查询范围。" for index in range(2, turns + 1)]]
    roundtrip.state.questions = questions[1:]
    exchanges = []
    for index, question in enumerate(questions, start=1):
        answer = f"第 {index} 项仅查询，禁止写入"
        exchanges.append({"question": question, "answer": answer})
        result = roundtrip.send(roundtrip.service(), answer)
        assert result["success"] is True, (index, result.get("data"), result.get("response"))
        assert result["run_id"] == first["run_id"], (index, result)
        persisted = roundtrip.repository.get(first["run_id"])
        assert persisted.message == ORIGINAL
        assert persisted.metadata["runtime_context"]["planning_clarification"] == {
            "original_request": ORIGINAL,
            "exchanges": exchanges,
        }
        request = _planning_requests(roundtrip.requests)[-1]
        assert "planning_clarification" not in request.get("context", {})
        assert json.loads(request["user_message"]) == {
            "original_request": ORIGINAL,
            "exchanges": exchanges,
        }
        if index < turns:
            assert persisted.status == "waiting_user"
            roundtrip.executor.execute_with_deadline.assert_not_called()
    assert persisted.status == "completed"
    roundtrip.executor.execute_with_deadline.assert_called_once()


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
