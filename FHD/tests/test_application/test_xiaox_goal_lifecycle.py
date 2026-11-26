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
from app.infrastructure.xiaox import XiaoxTransportError
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


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
            raise XiaoxTransportError("fixture_final_lost", "final turn event unavailable")
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
    assert len(parent.metadata["xiaox_runtime"]["calls"]) == 2
    assert all(receipt["verified"] for receipt in state.receipts)
    assert result["business_completed"] is (not lost_final), result
    if lost_final:
        assert not state.model_requests, "lost SDK completion is not an independent goal review"
    else:
        assert len(state.model_requests) == 1
        assert parent.status == "completed" and result["runtime_completed"] is True
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    snapshot = reopened.receipt_snapshot(parent.run_id)
    assert len(snapshot) == 2 and all(row["receipt"]["verified"] for row in snapshot)
    assert len(state.receipts) == 2, "receipt verification never replays tools"
    duplicate = asyncio.run(state.invoke(**options))
    assert duplicate["deduplicated"] is True
    assert duplicate["business_completed"] is (not lost_final)
    assert len(state.transports) == 2 and len(state.receipts) == 2
    with pytest.raises(XiaoxBindingError):
        reopened.authenticate(state.token)


def test_pure_reply_needs_no_business_tool_or_upfront_plan(goal_runtime):
    state = goal_runtime
    state.actions = []
    state.reply = "库存表示当前持有的货物数量。"
    state.review = lambda prompt: fixture_goal_review(prompt, kind="reply")
    result = asyncio.run(state.invoke(task="库存是什么意思？", completion_mode="business"))
    assert result["reply_completed"] is True and result["business_completed"] is False
    parent = state.repository.get(result["run_id"])
    assert parent.metadata["xiaox_runtime"]["calls"] == {} and state.receipts == []
    assert parent.metadata["runtime_goal_verification"]["mode"] == "reply"
    assert len(state.transports) == len(state.model_requests) == 1


@pytest.mark.parametrize(
    "failure",
    [
        "no_effect",
        "missing_proof",
        "digest_mismatch",
        "goal_unmet",
        "model_unknown",
        "adapter_lie",
        "adapter_partial",
        "adapter_unknown",
    ],
)
def test_recovered_write_uses_bound_sql_receipts_and_independent_goal_review(
    goal_runtime, local_tools, monkeypatch, failure
):
    from sqlalchemy import select

    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )
    from app.application.facades.tools_facade import execute_registered_workflow_tool
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.resilience import rate_limiter
    from tests.test_application.test_agent_user_decision_pause import _approve_and_execute

    state = goal_runtime
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", state.actor.factory
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.approval_grant._consumption_repository",
        lambda: SQLAlchemyApprovalConsumptionRepository(state.actor.factory),
    )
    dispatches = []
    adapter_failure = failure.startswith("adapter_")
    proven = failure not in {"missing_proof", "digest_mismatch"} and not adapter_failure
    endpoint = "agent-tool:customers.create"
    limiter = rate_limiter._InMemoryRateLimiter(max_requests=120)
    monkeypatch.setitem(rate_limiter._rate_limiters, endpoint, limiter)
    for _ in range(0 if adapter_failure else 120):
        assert rate_limiter.check_rate_limit(str(state.actor.tenant_id), endpoint)["allowed"]
    if failure == "missing_proof":
        # Exercise an original receipt made by the previous host version, which
        # had a definite rejection but did not persist a no-effect attestation.
        monkeypatch.setattr(
            "app.application.agent_orchestrator.tool_executor._pre_dispatch_refusal",
            lambda result: result,
        )

    def names():
        with tenant_scope(state.actor.tenant_id), state.actor.factory() as db:
            return list(
                db.scalars(
                    select(PurchaseUnit.unit_name).where(
                        PurchaseUnit.tenant_id == state.actor.tenant_id
                    )
                )
            )

    def dispatch(tool, action, params):
        assert (tool, action) == ("customers", "create")
        dispatches.append(params["unit_name"])
        assert adapter_failure or params["unit_name"] != "rejected-customer", (
            "host denial reached the adapter"
        )
        actual = execute_registered_workflow_tool(tool, action, params)
        if adapter_failure:
            assert actual["success"] is True
            # The source committed, then its adapter lost/contradicted the result.
            # An adapter's no-effect assertion cannot replace the host boundary.
            return {
                "success": False,
                "error_code": "fixture_response_lost_after_commit",
                "execution": {
                    "outcome": {
                        "adapter_lie": "not_executed",
                        "adapter_partial": "partial",
                        "adapter_unknown": "unknown",
                    }[failure],
                    "committed": failure == "adapter_partial",
                },
            }
        return actual

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )

    def execute(name, call_id):
        pending = state.execute("customers", "create", {"unit_name": name}, call_id)
        if pending.get("pending_approval"):
            _approve_and_execute(
                state.bridge.orchestrator,
                state.repository.get(pending["run_id"]),
                state.actor,
            )
            if failure == "digest_mismatch" and call_id == "rejected-attempt":
                child = state.repository.get(pending["run_id"])
                child.tool_calls[0].metadata["verification_output_sha256"] = "0" * 64
                state.repository.save(child)
        return state.bridge.invoke(state.token, "task_evidence", {"call_id": call_id})

    def script(binding, text):
        first = execute("rejected-customer", "rejected-attempt")
        if adapter_failure:
            assert first["status"] == "unknown" and first["success"] is False, first
            with pytest.raises(CodexBindingError) as rejected:
                state.execute(
                    "customers", "create", {"unit_name": "recovered-customer"}, "changed-call"
                )
            assert rejected.value.code == "outcome_unknown"
            return "模型声称已完成全部目标，但原失败写入仍未核验。"
        assert first["status"] == "failed" and first["success"] is False, first
        assert bool(first.get("execution")) is proven, first
        if not dispatches:
            assert names() == []
        # A new backend window permits the later, separately approved action.
        monkeypatch.setitem(
            rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(120)
        )
        second = execute("recovered-customer", "corrected-attempt")
        assert second["verified"] is True, second
        if failure == "model_unknown":
            import httpx
            from fastapi.testclient import TestClient

            from app.infrastructure.codex.model_gateway import MODEL_PATH

            upstream = httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "id": "unmetered-response",
                        "model": state.settings.route.response_model,
                        "status": "completed",
                        "output": [],
                    },
                )
            )
            app = state.servers[-1]
            app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
                transport=upstream, **kwargs
            )
            with TestClient(app) as client:
                response = client.post(
                    MODEL_PATH,
                    headers={
                        "authorization": f"Bearer {state.transports[-1].config.provider_token}"
                    },
                    json={"model": state.settings.route.model, "input": "read original receipts"},
                )
            assert response.status_code == 502, response.text
        return "原客户已创建并通过独立读回核验。"

    state.script = script
    state.review = lambda prompt: fixture_goal_review(
        prompt, kind="write", status="unmet" if failure == "goal_unmet" else "satisfied"
    )
    result = asyncio.run(state.invoke(task="创建名为 recovered-customer 的客户"))
    parent = state.repository.get(result["run_id"])
    assert names() == ["rejected-customer" if adapter_failure else "recovered-customer"], (
        result.get("exit_status"),
        result.get("error"),
        dispatches,
        parent.metadata.get("codex_runtime", {}).get("calls"),
    )
    assert dispatches == names(), "recovery dispatched a business write more than once"
    unresolved = adapter_failure or failure == "model_unknown"
    if unresolved:
        assert state.model_requests == [] and result["reconciliation_required"] is True
    else:
        accepted = failure != "goal_unmet"
        assert parent.metadata["runtime_goal_verification"]["accepted"] is accepted
        assert result["goal_coverage"]["completed"] is accepted
    if failure == "model_unknown":
        assert parent.metadata["reserved_cost_units"] > 0
        assert any(
            request["state"] == "unknown"
            for request in parent.metadata["codex_runtime"]["model_requests"].values()
        )
    assert result["business_completed"] is (failure == "no_effect"), result
    assert result["ok"] is (failure == "no_effect"), result
    assert result["execution_state"] == (
        "unknown" if unresolved else "completed" if failure == "no_effect" else "partial"
    )
    reopened = CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    rows = reopened.receipt_snapshot(parent.run_id)
    assert len(rows) == (1 if adapter_failure else 2)
    assert rows[0]["receipt"]["success"] is False
    if not adapter_failure:
        assert rows[1]["receipt"]["verified"] is True
    assert bool(rows[0]["receipt"].get("execution")) is proven
    assert dispatches == names(), "readback replayed a tool"


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
        store = XiaoxBindingStore(state.repository)
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
    assert parent.metadata["xiaox_runtime"]["generation"] == generation
    assert not parent.metadata.get("runtime_goal_contract")
    assert not parent.memory_references and not parent.retrieval_calls


@pytest.mark.parametrize("read_state", ["failed", "unknown"])
def test_approval_readback_allows_settled_failed_exploration_but_never_unknown(read_state):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
    from app.infrastructure.xiaox.receipt_projection import project_receipt_state

    parent = AgentRun(
        run_id="readback-goal-parent",
        user_id="42",
        message="先核对库存，再创建发货单",
        intent="xiaox.runtime",
        status="waiting_user",
    )
    contract = build_goal_contract(parent)
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_goal_contract=contract,
        runtime_goal_digest=contract["digest"],
        xiaox_runtime={
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
    parent.final_output["xiaox_result"] = {
        "exit_status": "waiting_user",
        "business_receipts": [read, waiting],
    }
    projected = project_receipt_state(parent, [read, write])
    assert projected is not None
    result = projected.final_output["xiaox_result"]
    assert result["business_completed"] is False, "child completion never proves the original goal"
    if read_state == "unknown":
        assert projected.status == "blocked" and result["reconciliation_required"] is True
    else:
        assert projected.status == "running" and result["exit_status"] == "continuation_pending"

        # A result read cannot invent a new review budget after the SDK already
        # exhausted its bounded corrections with unchanged completed receipts.
        parent.status = "blocked"
        parent.metadata["xiaox_runtime"]["active_seconds"] = 12.0
        parent.metadata["runtime_goal_verification"] = {
            "status": "needs_work",
            "error_code": "goal_verification_required",
            "feedback": "仍有原始目标未完成",
        }
        parent.final_output["xiaox_result"] = {
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
        after = exhausted.final_output["xiaox_result"]
        assert after["exit_status"] == "goal_verification_required"
        assert after["failure_stage"] == "goal_verification"
        assert after["failure_kind"] == "goal_verification_required"
        assert after["failure_reason"] == "仍有原始目标未完成"
        assert after["model_request_attempts"] == 4 and after["active_seconds"] == 12.0
