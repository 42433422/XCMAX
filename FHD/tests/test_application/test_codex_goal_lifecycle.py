"""Real SQL, dynamic MCP and independent review; only upstream I/O is a fixture.

No compiler/plan fixture makes the user's goal true. These scenarios exercise the
original request, host-persisted answers, independent children and final evidence.
"""

from __future__ import annotations

import asyncio
import copy
import threading

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import gateway, goal_admission
from app.domain.task_lifecycle.agent_runtime_contract import goal_answers
from app.infrastructure.codex import CodexTransportError
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.codex_http_runtime import fixture_goal_review
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def goal_runtime(dynamic_chat_runtime):
    state = dynamic_chat_runtime

    async def invoke(**kwargs):
        return await gateway.run_runtime_task_async(
            **{
                "task": "依次查询两个产品",
                "system_prompt": "根据原目标先观察，再逐项核对真实业务结果。",
                "runtime_context": {**state.actor.context, "turn_id": "original-goal-turn"},
                "completion_mode": "auto",
                "settings": state.settings,
                **kwargs,
            }
        )

    state.invoke = invoke
    return state


@pytest.mark.parametrize("lost_final", [False, True])
def test_dynamic_clarification_and_actions_keep_original_goal_and_sql_parent(
    goal_runtime, lost_final
):
    state = goal_runtime

    def script(binding, text):
        if not goal_answers(binding.run):
            question = state.bridge.invoke(
                state.token, "request_input", {"question": "请确认要查询的两个产品名称。"}
            )
            return question["question"]
        for name in ("first", "second"):
            receipt = state.execute("products", "query", {"keyword": name}, name)
            assert receipt["verified"] is True, receipt
        if lost_final:
            raise CodexTransportError("fixture_final_lost", "final turn event unavailable")
        return "已分别读取first和second的原查询回执。"

    state.script = script
    state.review = lambda prompt: fixture_goal_review(prompt, kind="read")
    waiting = asyncio.run(state.invoke())
    assert waiting["needs_user_input"] and not waiting["business_completed"]
    assert state.receipts == [] and state.model_requests == []
    parent = state.repository.get(waiting["run_id"])
    contract = copy.deepcopy(parent.metadata["runtime_goal_contract"])
    assert contract["request"]["text"] == "依次查询两个产品"
    assert not parent.metadata.get("runtime_frozen_plan")
    options = {
        "run_id": parent.run_id,
        "task": "first 和 second",
        "answer_to_waiting_input": True,
        "runtime_context": {**state.actor.context, "turn_id": "original-answer-turn"},
    }
    result = asyncio.run(state.invoke(**options))
    parent = state.repository.get(parent.run_id)
    assert parent.metadata["runtime_goal_contract"] == contract
    assert goal_answers(parent)[0]["answer"] == "first 和 second"
    assert result["run_id"] == parent.run_id and len(state.transports) == 2
    assert len(parent.metadata["codex_runtime"]["calls"]) == 2
    assert all(receipt["verified"] for receipt in state.receipts)
    assert result["business_completed"] is (not lost_final), result
    if lost_final:
        assert not state.model_requests, "lost SDK completion is not an independent goal review"
    else:
        assert len(state.model_requests) == 1
        assert parent.status == "completed" and result["runtime_completed"] is True
    reopened = CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    snapshot = reopened.receipt_snapshot(parent.run_id)
    assert len(snapshot) == 2 and all(row["receipt"]["verified"] for row in snapshot)
    assert len(state.receipts) == 2, "receipt verification never replays tools"
    duplicate = asyncio.run(state.invoke(**options))
    assert duplicate["deduplicated"] is True
    assert duplicate["business_completed"] is (not lost_final)
    assert len(state.transports) == 2 and len(state.receipts) == 2
    with pytest.raises(CodexBindingError):
        reopened.authenticate(state.token)


def test_pure_reply_needs_no_business_tool_or_upfront_plan(goal_runtime):
    state = goal_runtime
    state.actions = []
    state.reply = "库存表示当前持有的货物数量。"
    state.review = lambda prompt: fixture_goal_review(prompt, kind="reply")
    result = asyncio.run(state.invoke(task="库存是什么意思？", completion_mode="business"))
    assert result["reply_completed"] is True and result["business_completed"] is False
    parent = state.repository.get(result["run_id"])
    assert parent.metadata["codex_runtime"]["calls"] == {} and state.receipts == []
    assert parent.metadata["runtime_goal_verification"]["mode"] == "reply"
    assert len(state.transports) == len(state.model_requests) == 1


@pytest.mark.parametrize("control", ["cancel", "pause", "revoke_actor", "expire_grant"])
def test_context_admission_cannot_freeze_after_same_generation_authority_change(
    goal_runtime, monkeypatch, control
):
    from app.db.models.user import User

    state = goal_runtime
    entered, release = threading.Event(), threading.Event()
    actual_prepare = goal_admission.prepare_runtime_goal
    parents = []

    def prepare(binding, **kwargs):
        value = actual_prepare(binding, **kwargs)
        parents.append(binding.run_id)
        entered.set()
        assert release.wait(timeout=5), "fixture admission must be released"
        return value

    monkeypatch.setattr(goal_admission, "prepare_runtime_goal", prepare)

    async def scenario():
        pending = asyncio.create_task(state.invoke())
        assert await asyncio.to_thread(entered.wait, 5)
        store = CodexBindingStore(state.repository)
        parent_id = parents[0]
        generation = store.get(parent_id).metadata["generation"]
        try:
            if control in {"cancel", "pause"}:
                state.repository.request_task_control(
                    parent_id, control, requested_by=str(state.actor.user_id)
                )
            elif control == "revoke_actor":
                with state.actor.factory.begin() as db:
                    db.get(User, state.actor.user_id).is_active = False
            else:
                store.update(parent_id, lambda _run, metadata: metadata.update(expires_at=0))
        finally:
            release.set()
        return await asyncio.wait_for(pending, 5), parent_id, generation

    result, parent_id, generation = asyncio.run(scenario())
    parent = state.repository.get(parent_id)
    assert not result["ok"] and not result["business_completed"]
    assert state.transports == state.receipts == state.model_requests == []
    assert parent.metadata["codex_runtime"]["generation"] == generation
    assert not parent.metadata.get("runtime_goal_contract")
    assert not parent.memory_references and not parent.retrieval_calls


@pytest.mark.parametrize("read_state", ["failed", "unknown"])
def test_approval_readback_allows_settled_failed_exploration_but_never_unknown(read_state):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
    from app.infrastructure.codex.receipt_projection import project_receipt_state

    parent = AgentRun(
        run_id="readback-goal-parent",
        user_id="42",
        message="先核对库存，再创建发货单",
        intent="codex.runtime",
        status="waiting_user",
    )
    contract = build_goal_contract(parent)
    parent.metadata.update(
        runtime_type="codex",
        runtime_goal_contract=contract,
        runtime_goal_digest=contract["digest"],
        codex_runtime={
            "calls": {"read": {}, "write": {}},
            "goal_digest": contract["digest"],
            "coordinator_active": False,
            "revoked": True,
            "runtime_status": "completed",
        },
    )
    read = {
        "call_id": "read-call",
        "child_run_id": "read",
        "child_task_id": "read-task",
        "tool_id": "products",
        "action": "query",
        "params": {},
        "read_only": True,
        "state": read_state,
        "receipt": {
            "run_id": "read",
            "task_id": "read-task",
            "status": read_state,
            "success": False,
            "verified": False,
            "outcome": "not_started" if read_state == "failed" else "unknown",
        },
    }
    write = {
        "call_id": "write-call",
        "child_run_id": "write",
        "child_task_id": "write-task",
        "tool_id": "shipment",
        "action": "create",
        "params": {},
        "read_only": False,
        "state": "completed",
        "receipt": {
            "run_id": "write",
            "task_id": "write-task",
            "status": "completed",
            "success": True,
            "verified": True,
        },
    }
    waiting = copy.deepcopy(write)
    waiting.update(state="waiting_approval")
    waiting["receipt"].update(status="waiting_approval", success=False, verified=False)
    parent.final_output["codex_result"] = {
        "exit_status": "waiting_user",
        "business_receipts": [read, waiting],
    }
    projected = project_receipt_state(parent, [read, write])
    assert projected is not None
    result = projected.final_output["codex_result"]
    assert result["business_completed"] is False, "child completion never proves the original goal"
    if read_state == "unknown":
        assert projected.status == "blocked" and result["reconciliation_required"] is True
    else:
        assert projected.status == "running" and result["exit_status"] == "continuation_pending"

        # A result read cannot invent a new review budget after the SDK already
        # exhausted its bounded corrections with unchanged completed receipts.
        parent.status = "blocked"
        parent.metadata["codex_runtime"]["active_seconds"] = 12.0
        parent.metadata["runtime_goal_verification"] = {
            "status": "needs_work",
            "error_code": "goal_verification_required",
            "feedback": "仍有原始目标未完成",
        }
        parent.final_output["codex_result"] = {
            "exit_status": "goal_verification_required",
            "business_receipts": [read, write],
            "failure_stage": "goal_verification",
            "failure_kind": "goal_verification_required",
            "failure_reason": "仍有原始目标未完成",
            "model_request_attempts": 4,
            "active_seconds": 12.0,
        }
        exhausted = project_receipt_state(parent, [read, write])
        assert exhausted is not None and exhausted.status == "blocked"
        after = exhausted.final_output["codex_result"]
        assert after["exit_status"] == "goal_verification_required"
        assert after["failure_stage"] == "goal_verification"
        assert after["failure_kind"] == "goal_verification_required"
        assert after["failure_reason"] == "仍有原始目标未完成"
        assert after["model_request_attempts"] == 4 and after["active_seconds"] == 12.0
