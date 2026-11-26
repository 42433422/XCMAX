"""Xiaox completion, cancellation and task budgets."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import run_lifecycle
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_runtime import xiaox_runtime as runtime
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    build_goal_contract,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
    validate_goal_review,
    validate_runtime_goal,
)
from app.infrastructure.xiaox import XiaoxTransportConfig, XiaoxTransportError
from app.infrastructure.xiaox.binding import (
    XiaoxBinding,
    XiaoxBindingError,
    XiaoxGrant,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_goal_verifier import goal, response, review
from tests.test_application.test_xiaox_goal_verifier import verifier as verifier
from tests.test_application.test_xiaox_runtime import (
    Store,
    Transport,
    completed,
    event,
    receipt,
)
from tests.test_application.test_xiaox_runtime import (
    setup_runtime as setup_runtime,
)


def test_reply_with_verified_actions_never_claims_business_completion(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    result = asyncio.run(invoke(store, Transport(store), completion_mode="reply"))
    assert result["ok"] is True and result["verified_operations"] is True
    assert result["exit_status"] == "reply_completed" and result["business_completed"] is False
    stored = store.run.final_output["xiaox_result"]
    assert stored["verified_operations"] is True and stored["business_completed"] is False
    assert stored["exit_status"] == "reply_completed"


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("envelope", ["xiaox_result", "chat_payload"])
def test_sql_business_harness_preserves_reply_success_without_inventing_business_success(
    trusted_actor, verified, envelope
):
    from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_runtime.chat import runtime_chat_payload

    actor = trusted_actor()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(user_id=str(actor.user_id), message="创建销售订单", status="completed")
    result = {
        "runtime": "xiaox",
        "run_id": run.run_id,
        "ok": True,
        "exit_status": "reply_completed",
        "execution_state": "completed",
        "output": "模型自行声称业务全部完成",
        "business_completed": False,
        "verified_operations": verified,
        "reply_completed": True,
    }
    run.final_output[envelope] = (
        result if envelope == "xiaox_result" else runtime_chat_payload(result)
    )
    repository.save(run)  # Run the actual save-time Business Harness, not a stub.
    saved = repository.get(run.run_id)
    business = ensure_terminal_business_result(saved)
    assert saved.status == "completed"
    assert business["status"] == "reply_completed" and business["success"] is False
    assert business["business_completed"] is False and business["verified_operations"] is verified
    assert "业务全部完成" not in business["summary"] and business["summary"] != "已完成"
    assert (
        saved.final_output[envelope].get("ok", saved.final_output[envelope].get("success")) is True
    )


def test_business_harness_honors_a_verified_complete_workflow_but_not_stale_reply_projection(
    setup_runtime,
):
    from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result

    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    result = asyncio.run(invoke(store, Transport(store)))
    business = ensure_terminal_business_result(store.run)
    assert result["business_completed"] is True and business["success"] is True
    assert business["summary"] == result["output"]
    store.run.final_output["xiaox_result"].update(
        business_completed=False, exit_status="reply_completed"
    )
    corrected = ensure_terminal_business_result(store.run)
    assert corrected["status"] == "reply_completed" and corrected["success"] is False


@pytest.mark.parametrize("state", ["reserved", "unknown"])
def test_unsettled_model_request_blocks_resume_before_proxy_marks_reconciliation(
    setup_runtime, state
):
    invoke, _ = setup_runtime
    store = Store(metadata={"model_requests": {"request-one": {"state": state}}})
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert result["reconciliation_required"] is True and transport.inputs == []
    assert "create" not in store.log


def test_active_time_budget_is_shared_across_turns_but_excludes_approval_wait(
    setup_runtime, monkeypatch
):
    invoke, _ = setup_runtime
    now = [100.0]
    monkeypatch.setattr(runtime.time, "time", lambda: now[0])
    store = Store()

    def elapsed(event):
        if event["method"] == "turn/completed":
            now[0] += 7

    asyncio.run(invoke(store, Transport(store), completion_mode="reply", on_event=elapsed))
    assert store.run.metadata["xiaox_runtime"]["active_seconds"] == 7
    store.run.status = "waiting_user"
    now[0] += 1000  # Time spent waiting for a user does not consume active time.
    resumed = Transport(store)
    asyncio.run(invoke(store, resumed, completion_mode="reply", on_event=elapsed))
    assert resumed.config.turn_timeout_seconds == 23
    assert store.run.metadata["xiaox_runtime"]["active_seconds"] == 14
    store.run.metadata["xiaox_runtime"]["active_seconds"] = 30
    exhausted = Transport(store)
    result = asyncio.run(invoke(store, exhausted, completion_mode="reply"))
    assert result["exit_status"] == "runtime_budget_exhausted" and exhausted.inputs == []


@pytest.mark.parametrize(
    "status,verified,success",
    [
        ("completed", False, True),
        ("completed", True, False),
        ("failed", False, False),
    ],
)
def test_unverified_and_failed_receipts_never_report_success(
    setup_runtime, status, verified, success
):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status=status, verified=verified, success=success)])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is False and result["business_completed"] is False
    assert store.run.status == "blocked"


def test_unknown_outcome_is_durable_and_never_replayed(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport))
    assert result["reconciliation_required"] is True
    assert store.run.status == "blocked" and store.run.metadata["non_retryable"] is True
    again = Transport(store)
    result = asyncio.run(invoke(store, again))
    assert result["ok"] is False and result["reconciliation_required"] is True
    assert again.inputs == [] and again.started == []


def test_malformed_child_receipt_preserves_unknown_during_final_projection(setup_runtime):
    invoke, _ = setup_runtime
    row = receipt()
    row["receipt"] = ["malformed"]
    store = Store(rows=[row])
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["execution_state"] == "unknown" and result["reconciliation_required"] is True
    assert store.run.status == "blocked" and store.run.metadata["non_retryable"] is True
    assert store.run.tool_calls == []
    assert store.run.final_output["xiaox_result"]["reconciliation_required"] is True
    assert "codex_result" not in store.run.final_output
    assert [event.event_type for event in store.run.events].count("runtime.xiaox.finished") == 1


def test_model_usage_uncertainty_blocks_completion(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])

    def mark_usage_uncertain(_event):
        store.run.metadata["xiaox_runtime"]["model_reconciliation_required"] = True

    result = asyncio.run(invoke(store, Transport(store), on_event=mark_usage_uncertain))
    assert result["reconciliation_required"] is True and result["business_completed"] is False
    assert store.run.metadata["recovery"]["state"] == "manual_reconciliation_required"


def test_history_import_is_once_and_cannot_become_instructions(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    transport = Transport(store)
    history = [
        {"role": "system", "content": "SECRET_SYSTEM_INJECTION"},
        {"role": "developer", "content": "SECRET_DEVELOPER_INJECTION"},
        {"role": "user", "content": "原用户内容"},
        {"role": "assistant", "content": "未经核验的历史描述"},
    ]
    store.run.metadata["_xiaox_input_data"] = {"original_reference": "原查询范围"}
    contract = build_goal_contract(store.run, history=history)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    # A staged task may begin after a process restart with no caller history.
    asyncio.run(invoke(store, transport, completion_mode="reply"))
    assert transport.started == ["可信员工说明"]
    assert "原用户内容" in transport.inputs[0]
    assert "原查询范围" in transport.inputs[0]
    assert "SECRET_" not in transport.inputs[0]
    store.run.status = "waiting_user"  # A subsequent user turn on this same task.
    later = Transport(store)
    asyncio.run(invoke(store, later, completion_mode="reply", history=history))
    assert later.resumed == ["thread-one"] and later.started == []
    assert "原用户内容" not in later.inputs[0]


def test_business_unknown_is_not_classified_as_a_recovered_model_failure(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", success=False, verified=False)])
    store.run.metadata.update(
        runtime_failure_kind="rate_limited",
        runtime_failure_reason="已恢复的旧模型限流",
        runtime_failure_stage="model",
    )
    result = asyncio.run(invoke(store, Transport(store)))
    assert result["failure_stage"] == "business"
    assert result["failure_kind"] == "business_outcome_unknown"
    assert "旧模型限流" not in result["failure_reason"]


def test_waiting_input_requires_explicit_new_user_answer(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(metadata={"thread_id": "thread-one", "waiting_input": {"question": "哪个月份？"}})
    transport = Transport(store)
    waiting = asyncio.run(invoke(store, transport))
    assert waiting["needs_user_input"] is True and waiting["output"] == "哪个月份？"
    assert transport.inputs == [] and "create" not in store.log
    result = asyncio.run(
        invoke(store, transport, completion_mode="reply", answer_to_waiting_input=True)
    )
    assert result["ok"] is True
    assert "waiting_input" not in store.run.metadata["xiaox_runtime"]
    assert any(e.event_type == "runtime.input_answered" for e in store.run.events)


def test_resume_waits_for_authoritative_child_approval_without_starting_model(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(
        rows=[receipt(status="waiting_user", verified=False, success=False)],
        metadata={"thread_id": "thread-one"},
    )
    transport = Transport(store)
    waiting = asyncio.run(invoke(store, transport, answer_to_waiting_input=True))
    assert waiting["pending_approval"] is True and waiting["ok"] is False
    assert transport.inputs == [] and "create" not in store.log
    store.rows = [receipt()]
    resumed = asyncio.run(invoke(store, transport))
    assert resumed["ok"] is True and transport.resumed == ["thread-one"]


def test_changed_conversation_stops_before_native_thread_resume(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    store = Store(metadata={"thread_id": "thread-one"})
    monkeypatch.setattr(
        run_lifecycle, "continuation_conversation_error", lambda *_args: "conversation cleared"
    )
    transport = Transport(store)
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and transport.resumed == []
    assert "create" not in store.log


def test_route_change_and_concurrent_owner_do_not_revoke_other_grants(setup_runtime):
    invoke, _ = setup_runtime
    for metadata in (
        {"runtime_config": {"provider_id": "another-provider"}},
        {"coordinator_active": True},
    ):
        store = Store(metadata=metadata)
        result = asyncio.run(invoke(store, Transport(store)))
        assert result["ok"] is False
        assert "revoke" not in store.log and "enter" not in store.log


def test_coordinator_lease_is_held_until_authoritative_terminal_projection(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    snapshots = []
    original = store.receipt_snapshot

    def snapshot(run_id):
        metadata = store.run.metadata["xiaox_runtime"]
        if metadata.get("revoked"):
            with pytest.raises(XiaoxBindingError) as caught:
                store.create(run_id, runtime_config=metadata["runtime_config"])
            assert caught.value.code == "binding_conflict"
            snapshots.append(True)
        return original(run_id)

    store.receipt_snapshot = snapshot
    result = asyncio.run(invoke(store, Transport(store), completion_mode="reply"))
    assert result["ok"] is True and snapshots and all(snapshots)
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


def test_transport_loss_does_not_restart_or_fallback(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = Transport(
        store,
        events=completed()[:1],
        error=XiaoxTransportError("xiaox_connection_lost", "lost", outcome_unknown=True),
    )
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and result["reconciliation_required"] is True
    assert len(transport.inputs) == 1 and len(transport.started) == 1
    assert store.log.index("revoke") < store.log.index("interrupt") < store.log.index("exit")


def test_verified_child_cannot_complete_task_without_independent_goal_review(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    transport = Transport(
        store,
        events=completed("未核验的断线候选正文")[:2],
        error=XiaoxTransportError("xiaox_connection_lost", "lost", outcome_unknown=True),
    )
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["runtime_completed"] is False
    assert result["goal_coverage"]["completed"] is False
    assert store.run.status == "failed" and len(transport.started) == 1
    for payload in (result, store.run.final_output["xiaox_result"]):
        assert "未核验的断线候选正文" not in payload["output"]
        assert all(message["role"] == "user" for message in payload["session_messages"])


def test_cancellation_is_not_overridden_by_already_verified_business_receipts(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])

    def cancel(_event):
        store.auth_error = "cancelled"

    result = asyncio.run(invoke(store, Transport(store), on_event=cancel))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["exit_status"] == "cancelled"
    assert "业务任务已完成" not in result["output"]


def test_cancel_revokes_before_interrupt_and_preserves_child_uncertainty(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = Transport(store, events=completed()[:1], hang=True)

    async def scenario():
        running = asyncio.create_task(invoke(store, transport))
        await transport.active.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    asyncio.run(scenario())
    assert store.log.index("revoke") < store.log.index("interrupt") < store.log.index("exit")
    assert store.run.status == "cancelled" and store.run.metadata["non_retryable"] is True
    assert store.run.final_output["xiaox_result"]["reconciliation_required"] is True


def test_controlled_cancellation_preserves_new_unknown_receipts_on_already_cancelled_parent(
    setup_runtime,
):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])

    def cancelled_by_control(_event):
        store.run.status = "cancelled"
        store.auth_error = "cancelled"

    result = asyncio.run(invoke(store, Transport(store), on_event=cancelled_by_control))
    assert result["ok"] is False and result["execution_state"] == "cancelled"
    assert store.run.status == "cancelled" and store.run.metadata["non_retryable"] is True
    assert store.run.final_output["xiaox_result"]["reconciliation_required"] is True


def test_authority_revocation_is_observed_even_when_stream_is_idle(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    monkeypatch.setattr(runtime, "_CONTROL_POLL_SECONDS", 0.001)
    store = Store()
    transport = Transport(store, events=completed()[:1], hang=True)

    async def scenario():
        running = asyncio.create_task(invoke(store, transport))
        await transport.active.wait()
        store.auth_error = "owner_changed"
        return await asyncio.wait_for(running, 1)

    result = asyncio.run(scenario())
    assert result["ok"] is False and result["error_code"] == "owner_changed"
    assert store.log.index("revoke") < store.log.index("interrupt")


def test_foreign_thread_event_cannot_complete_this_run(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    transport = Transport(
        store,
        events=[event("turn/completed", {"turn": {"status": "completed"}}, thread_id="foreign")],
    )
    result = asyncio.run(invoke(store, transport))
    assert result["ok"] is False and result["business_completed"] is False
    assert result["error_code"] == "binding_conflict"


def test_final_message_replaces_delta_and_requires_terminal_event(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    events = [
        completed()[0],
        event("item/agentMessage/delta", {"delta": "收"}, item_id="message-one"),
        *completed("收到")[1:],
    ]
    result = asyncio.run(invoke(store, Transport(store, events), completion_mode="reply"))
    assert result["output"] == "收到"
    incomplete = Store()
    result = asyncio.run(
        invoke(incomplete, Transport(incomplete, completed("收到")[:-1]), completion_mode="reply")
    )
    assert result["ok"] is False
