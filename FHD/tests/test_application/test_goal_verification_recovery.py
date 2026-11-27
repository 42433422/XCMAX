"""Verification-only recovery after transport timeouts and process loss.

The original business action and receipt must never be replayed by recovery."""

from __future__ import annotations

import asyncio
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import goal_verification_task as checkpoint
from app.application.agent_runtime.verification_budget import JOB_KEY
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.goal_verification_task import _finish as _finish
from tests.fixtures.goal_verification_task import _review as _review
from tests.fixtures.goal_verification_task import review_task as review_task
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def pending_business_review(dynamic_chat_runtime, local_tools, monkeypatch, request):
    """Commit one real customer, then fail only the independent model review."""
    from sqlalchemy import select

    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )
    from app.application.agent_runtime import gateway, goal_verifier, xiaox_runtime
    from app.db.models.purchase_unit import PurchaseUnit
    from app.domain.shared_services import tools_workflow_dispatch
    from app.infrastructure.tenant_scope import tenant_scope
    from tests.test_application.test_agent_user_decision_pause import _approve_and_execute

    state = dynamic_chat_runtime
    state.dispatches = []
    name = "verification-only-customer"
    fault = getattr(request, "param", "settled_timeout")
    after_commit = "_after_" in fault
    reply_only = fault.endswith("_after_reply")
    if "process_loss" in fault:
        finish = xiaox_runtime.finish_verification

        def capture_before_finalize(store, run_id, **kwargs):
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            if after_commit:
                if fault.endswith("_after_blocked"):
                    store.update(
                        run_id, lambda run, _metadata: run.metadata[JOB_KEY].update(attempts=3)
                    )
                finish(store, run_id, **kwargs)
            state.crash_run = copy.deepcopy(store.get(run_id).run)
            with state.actor.factory() as db:
                queued = db.get(AgentTaskExecutionRecord, run_id)
                state.crash_control = copy.deepcopy(
                    SessionBook(db).get("agent", str(state.actor.tenant_id), run_id)
                )
                state.crash_queue = (
                    {
                        column.name: getattr(queued, column.name)
                        for column in queued.__table__.columns
                    }
                    if queued is not None
                    else None
                )
            if after_commit:
                raise XiaoxBindingError(
                    "injected_process_loss_after_verification", "fault injection"
                )
            return finish(store, run_id, **kwargs)

        monkeypatch.setattr(xiaox_runtime, "finish_verification", capture_before_finalize)
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session",
        state.actor.factory,
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.approval_grant._consumption_repository",
        lambda: SQLAlchemyApprovalConsumptionRepository(state.actor.factory),
    )
    original_dispatch = tools_workflow_dispatch.execute_registered_workflow_tool

    def dispatch(tool, action, params):
        state.dispatches.append((tool, action, copy.deepcopy(params)))
        return original_dispatch(tool, action, params)

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        dispatch,
    )

    def names():
        with tenant_scope(state.actor.tenant_id), state.actor.factory() as db:
            return list(
                db.scalars(
                    select(PurchaseUnit.unit_name).where(
                        PurchaseUnit.tenant_id == state.actor.tenant_id,
                    )
                )
            )

    def script(_binding, _text):
        if reply_only:
            return "库存表示当前持有的货物数量。"
        receipt = state.execute("customers", "create", {"unit_name": name}, "original-write")
        if receipt.get("pending_approval"):
            _approve_and_execute(
                state.bridge.orchestrator,
                state.repository.get(receipt["run_id"]),
                state.actor,
            )
        receipt = state.bridge.invoke(state.token, "task_evidence", {"call_id": "original-write"})
        child = state.repository.get(receipt["run_id"])
        assert receipt["verified"] is True, child.metadata.get("verification")
        assert names() == [name]
        return "原客户已创建并由原业务读回确认。"

    state.script = script
    clock = SimpleNamespace(offset=0.0)
    actual_time = goal_verifier.time
    monkeypatch.setattr(
        goal_verifier,
        "time",
        SimpleNamespace(
            time=time.time,
            monotonic=lambda: time.monotonic() + clock.offset,
        ),
    )

    def review(prompt):
        if fault in {"unknown_transport", "queued_process_loss_unknown"}:
            import httpx

            raise httpx.ReadTimeout("injected response loss after request admission")
        value = fixture_goal_review(prompt, kind="reply" if reply_only else "write")
        if fault.endswith("_after_needs_work"):
            value["goals"].append(
                {
                    "goal_id": "missing-explanation",
                    "source_id": "request",
                    "source": prompt["original_request"]["text"],
                    "kind": "reply",
                    "status": "unmet",
                    "evidence_ids": [],
                    "reason": "The original business purpose still needs explaining.",
                }
            )
        # Metering completes in the real gateway, but the local verifier sees
        # its own deadline elapse before accepting the response. No wall sleep.
        if not after_commit or fault.endswith(("_after_pending", "_after_blocked")):
            clock.offset = 1000.0
        return value

    state.review = review
    if fault.startswith("queued_"):
        accepted = state.client.post(
            "/api/agent/runs",
            json={
                "message": "解释库存的含义" if reply_only else f"创建客户 {name} 并解释其业务用途",
                "request_id": "original-before-process-loss",
            },
        )
        assert accepted.status_code == 202, accepted.text
        result = state.drain(accepted.json()["data"]["run_id"]).final_output["xiaox_result"]
    else:
        result = asyncio.run(
            gateway.run_runtime_task_async(
                task=f"创建客户 {name}",
                system_prompt="按原授权执行，并独立核对真实回执。",
                runtime_context={**state.actor.context, "turn_id": "wg06-original-turn"},
                completion_mode="auto",
                settings=state.settings,
            )
        )
    monkeypatch.setattr(goal_verifier, "time", actual_time)
    if "process_loss" in fault:
        monkeypatch.setattr(xiaox_runtime, "finish_verification", finish)
    state.review = lambda _prompt: pytest.fail("a settled original review must not be billed again")
    state.parent_id = result["run_id"]
    state.first_result = result
    state.original_parent = state.repository.get(state.parent_id)
    state.names = names
    state.original_rows = XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id)
    assert names() == ([] if reply_only else [name])
    assert len(state.dispatches) == len(state.original_rows) == (0 if reply_only else 1)
    if not reply_only:
        assert state.original_rows[0]["receipt"]["verified"] is True, state.original_rows[0]
    if not fault.endswith(("_after_verified", "_after_reply")):
        assert not result["business_completed"] and not result["ok"], result
    return state


def _make_due(state):
    XiaoxBindingStore(state.repository).update(
        state.parent_id,
        lambda run, _metadata: run.metadata[JOB_KEY].update(next_attempt_at=0),
    )


def _forbid_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("verification recovery must not create/resume an SDK thread or dispatch tools")

    monkeypatch.setattr("app.infrastructure.xiaox.XiaoxTransport", forbidden)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.AgentToolExecutor.execute",
        forbidden,
    )


@pytest.mark.parametrize(
    "pending_business_review", ["settled_timeout", "queued_timeout"], indirect=True
)
def test_settled_timeout_recovers_only_verification_and_original_business_receipt(
    pending_business_review,
    monkeypatch,
):
    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    reopened = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    assert checkpoint.enqueue_pending_goal_verifications(repository=reopened) == 1
    saved = state.drain(state.parent_id)
    result = saved.final_output["xiaox_result"]
    assert result["ok"] and result["business_completed"], result
    assert saved.metadata[JOB_KEY]["state"] == "verified"
    assert saved.metadata[JOB_KEY]["attempts"] == 2
    assert len(state.transports) == 1 and len(state.dispatches) == 1
    assert len(state.model_requests) == 1, "parsing a settled response must not repeat billing"
    assert state.names() == ["verification-only-customer"]
    current_rows = XiaoxBindingStore(reopened).receipt_snapshot(state.parent_id)
    assert current_rows == state.original_rows
    assert (
        saved.metadata["runtime_goal_contract"]
        == state.original_parent.metadata["runtime_goal_contract"]
    )
    assert state.queue.get(state.parent_id).state == "succeeded"


def test_concurrent_recovery_scanners_publish_one_original_queue_request(
    pending_business_review,
    monkeypatch,
):
    from app.infrastructure.xiaox import queued_runtime

    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    barrier = threading.Barrier(2)
    enqueue = queued_runtime.enqueue_resume

    def simultaneous(*args, **kwargs):
        barrier.wait(timeout=10)
        return enqueue(*args, **kwargs)

    with monkeypatch.context() as racing:
        racing.setattr(queued_runtime, "enqueue_resume", simultaneous)

        def scan():
            return checkpoint.enqueue_pending_goal_verifications(
                repository=SQLAlchemyAgentRunRepository(session_factory=state.actor.factory),
            )

        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [workers.submit(scan) for _ in range(2)]
            outcomes = [future.result(timeout=15) for future in pending]
    assert sorted(outcomes) == [0, 1]
    run = state.repository.get(state.parent_id)
    assert (
        sum(
            entry.get("source") == "independent_goal_verification"
            for entry in run.metadata["runtime_requests"].values()
        )
        == 1
    )
    saved = state.drain(state.parent_id)
    assert saved.final_output["xiaox_result"]["business_completed"] is True
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


def test_scanner_cursor_reaches_a_due_review_after_an_incompatible_older_checkpoint(
    pending_business_review, review_task, monkeypatch
):
    state = pending_business_review
    stale = review_task
    report = _review(stale, status="unavailable", error_code="goal_verification_timeout")
    _finish(stale, report)

    def block(run, _metadata):
        run.status = "blocked"
        run.metadata[JOB_KEY]["next_attempt_at"] = 0
        run.metadata[JOB_KEY]["version"] = "retired-verifier-version"

    stale.store.update(stale.run_id, block)
    stale.store.close(stale.run_id, "goal_verification_timeout", generation=stale.generation)
    _make_due(state)  # The recoverable row is deliberately later than the incompatible one.
    _forbid_execution(monkeypatch)
    cursor = {}
    assert (
        checkpoint.enqueue_pending_goal_verifications(
            repository=state.repository, cursor=cursor, limit=1
        )
        == 0
    )
    assert cursor["run_id"] == stale.run_id
    assert (
        checkpoint.enqueue_pending_goal_verifications(
            repository=state.repository, cursor=cursor, limit=1
        )
        == 1
    )
    assert cursor["run_id"] == state.parent_id
    assert (
        checkpoint.enqueue_pending_goal_verifications(
            repository=state.repository, cursor=cursor, limit=1
        )
        == 0
    )
    assert cursor == {}, "an exhausted scan must wrap instead of abandoning older pending rows"
    saved = state.drain(state.parent_id)
    assert saved.final_output["xiaox_result"]["business_completed"] is True
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert stale.repository.get(stale.run_id).metadata[JOB_KEY]["attempts"] == 1


@pytest.mark.parametrize("pending_business_review", ["unknown_transport"], indirect=True)
def test_unknown_model_charge_does_not_schedule_another_review_or_business_action(
    pending_business_review,
    monkeypatch,
):
    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    parent = state.repository.get(state.parent_id)
    assert parent.metadata["xiaox_runtime"]["model_reconciliation_required"] is True
    assert any(
        entry["state"] == "unknown"
        for entry in parent.metadata["xiaox_runtime"]["model_requests"].values()
    )
    before = copy.deepcopy(parent.metadata["xiaox_runtime"]["model_requests"])
    for _ in range(2):
        assert (
            checkpoint.enqueue_pending_goal_verifications(
                repository=SQLAlchemyAgentRunRepository(session_factory=state.actor.factory),
            )
            == 0
        )
    after = state.repository.get(state.parent_id)
    assert after.metadata["xiaox_runtime"]["model_requests"] == before
    assert not after.final_output["xiaox_result"]["business_completed"]
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )


@pytest.mark.parametrize("control", ["cancel", "pause", "revoke_actor"])
def test_recovery_queue_rechecks_controls_without_dispatch(
    pending_business_review, monkeypatch, control
):
    from app.db.models.user import User

    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    if control in {"cancel", "pause"}:
        state.repository.request_task_control(
            state.parent_id,
            control,
            requested_by=str(state.actor.user_id),
        )
    else:
        with state.actor.factory.begin() as db:
            db.get(User, state.actor.user_id).is_active = False
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    saved = state.repository.get(state.parent_id)
    assert not saved.final_output["xiaox_result"]["ok"]
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert state.names() == ["verification-only-customer"]


def _restore_last_pre_crash_commit(state):
    """Restore the actual SQL snapshot captured before any runtime finalization."""
    import json
    from datetime import UTC, datetime, timedelta

    from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord
    from app.domain.task_lifecycle.control import SessionBook

    original = copy.deepcopy(state.crash_run)
    metadata = original.metadata["xiaox_runtime"]
    job = original.metadata[JOB_KEY]
    # Move only the owner's clocks back to represent downtime. Frozen business
    # receipts remain byte-for-byte identical to the actual committed operation.
    elapsed = 3600
    for key in ("active_started_at", "deadline_at", "execution_deadline_at", "expires_at"):
        if metadata.get(key) is not None:
            metadata[key] -= elapsed
    for key in ("started_at", "observed_at"):
        if job.get(key) is not None:
            job[key] -= elapsed
    observed = datetime.fromisoformat(original.updated_at) - timedelta(seconds=elapsed)
    original.updated_at = observed.isoformat()
    with state.actor.factory.begin() as db:
        record = db.get(AgentRunRecord, state.parent_id)
        record.status = original.status
        record.updated_at = original.updated_at
        record.payload_json = json.dumps(original.to_dict(), ensure_ascii=False)
        SessionBook(db).put(
            "agent", str(state.actor.tenant_id), state.parent_id, copy.deepcopy(state.crash_control)
        )
        if state.crash_queue:
            queued = db.get(AgentTaskExecutionRecord, state.parent_id)
            for name, value in state.crash_queue.items():
                setattr(queued, name, value)
            queued.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    return original


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss"], indirect=True)
def test_startup_and_new_queue_lease_recover_a_process_loss_after_settled_review_response(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher

    state = pending_business_review
    before = _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    assert state.repository.get(state.parent_id).status == "running"
    old_count = state.queue.get(state.parent_id).execution_count
    recovered = state.queue.claim("restarted-verifier", lease_seconds=120)
    if recovered is None:
        from app.domain.task_lifecycle.control import SessionBook

        with state.actor.factory() as db:
            current = SessionBook(db).get("agent", str(state.actor.tenant_id), state.parent_id)
        pytest.fail(str({"original_control": state.crash_control, "current_control": current}))
    assert recovered.execution_count == old_count + 1
    AgentTaskDispatcher(
        execution_repository=state.queue, run_repository=state.repository
    )._execute_claim(recovered, "restarted-verifier")
    after = state.repository.get(state.parent_id)
    assert after.final_output["xiaox_result"]["business_completed"] is True, after.final_output
    assert after.metadata[JOB_KEY]["state"] == "verified"
    assert after.metadata[JOB_KEY]["attempts"] == 2
    assert (
        after.metadata["xiaox_runtime"]["active_seconds"]
        >= before.metadata["xiaox_runtime"]["active_seconds"]
    )
    assert after.metadata["xiaox_runtime"]["active_seconds"] < 120
    assert state.queue.get(state.parent_id).state == "succeeded"
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )


@pytest.mark.parametrize("pending_business_review", ["direct_process_loss"], indirect=True)
def test_startup_parks_expired_synchronous_review_then_original_scanner_recovers(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert state.crash_queue is None
    assert stale_run_reconciler.reconcile_stale_running_runs() == 1
    recovered = state.repository.get(state.parent_id)
    assert recovered.status == "blocked"
    assert recovered.metadata[JOB_KEY]["state"] == "pending"
    assert recovered.metadata["xiaox_runtime"]["coordinator_active"] is False
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 1
    after = state.drain(state.parent_id)
    assert after.final_output["xiaox_result"]["business_completed"] is True
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss_unknown"], indirect=True)
def test_process_loss_does_not_clear_an_unknown_model_charge_or_start_a_new_review(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    original = _restore_last_pre_crash_commit(state)
    before = copy.deepcopy(original.metadata["xiaox_runtime"]["model_requests"])
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    after = state.drain(state.parent_id)
    assert after.final_output["xiaox_result"]["reconciliation_required"] is True
    assert after.metadata["xiaox_runtime"]["model_requests"] == before
    assert not after.final_output["xiaox_result"]["ok"]
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss"], indirect=True)
@pytest.mark.parametrize("exhausted", ["attempts", "active_time"])
def test_process_loss_exhaustion_is_terminal_without_dispatching_another_review(
    pending_business_review, monkeypatch, exhausted
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    # The same last pre-crash write is replayed with the already-consumed recovery
    # count. No goal, response, ledger receipt or billing row is changed.
    if exhausted == "attempts":
        state.crash_run.metadata[JOB_KEY]["attempts"] = 3
    else:
        runtime = state.crash_run.metadata["xiaox_runtime"]
        runtime["active_seconds"] = runtime["runtime_config"]["max_active_seconds"]
    _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    after = state.drain(state.parent_id)
    job = after.metadata[JOB_KEY]
    assert job["state"] == "blocked" and job["attempts"] == (3 if exhausted == "attempts" else 1)
    assert job["terminal_code"] == (
        "goal_verification_budget_exhausted"
        if exhausted == "attempts"
        else "runtime_budget_exhausted"
    )
    assert after.final_output["xiaox_result"]["retryable"] is False
    assert not after.final_output["xiaox_result"].get("reconciliation_required", False)
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss"], indirect=True)
@pytest.mark.parametrize("tamper", ["child_output", "child_parent", "intent", "step_id"])
def test_crash_recovery_never_clears_a_child_effect_from_parent_verified_flags_alone(
    pending_business_review, monkeypatch, tamper
):
    from app.domain.task_lifecycle.control import SessionBook

    state = pending_business_review
    _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    parent = state.repository.get(state.parent_id)
    call = next(iter(parent.metadata["xiaox_runtime"]["calls"].values()))
    assert call["receipt"]["verified"] is True
    if tamper in {"child_output", "child_parent"}:
        child = state.repository.get(call["child_run_id"])
        if tamper == "child_output":
            import json

            from app.db.models.agent import AgentRunRecord

            # Normal repository saves correctly reject alteration of a verified
            # receipt; inject storage corruption to exercise the recovery reader.
            child.tool_calls[0].output["success"] = False
            with state.actor.factory.begin() as db:
                db.get(AgentRunRecord, child.run_id).payload_json = json.dumps(
                    child.to_dict(), ensure_ascii=False
                )
        else:
            child.metadata["runtime_context"]["parent_run_id"] = "another-original-parent"
            state.repository.save(child)
    elif tamper == "intent":
        call["params"]["unit_name"] = "a-different-business-intent"
        call["fingerprint"] = canonical_digest(
            {key: call[key] for key in ("tool_id", "action", "params")}
        )
        state.repository.save(parent)
    else:
        with state.actor.factory.begin() as db:
            book = SessionBook(db)
            body = book.get("agent", str(state.actor.tenant_id), state.parent_id)
            body["effects"] = [f"child:{call['child_run_id']}:a-different-step"]
            book.put("agent", str(state.actor.tenant_id), state.parent_id, body)
    with state.actor.factory() as db:
        before = SessionBook(db).get("agent", str(state.actor.tenant_id), state.parent_id)[
            "effects"
        ]
    assert before
    assert state.queue.claim("restarted-verifier", lease_seconds=120) is None
    with state.actor.factory() as db:
        after = SessionBook(db).get("agent", str(state.actor.tenant_id), state.parent_id)["effects"]
    assert after == before
    assert state.queue.get(state.parent_id).state == "unknown"
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize(
    "pending_business_review",
    [
        "queued_process_loss_after_pending",
        "queued_process_loss_after_verified",
        "queued_process_loss_after_reply",
        "queued_process_loss_after_blocked",
    ],
    indirect=True,
)
def test_committed_review_recovers_after_process_loss_before_runtime_finalization(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    original_state = state.crash_run.metadata[JOB_KEY]["state"]
    if original_state == "verified":
        # An already verified third attempt must only publish its committed
        # verdict, never require a forbidden fourth attempt to acknowledge it.
        state.crash_run.metadata[JOB_KEY]["attempts"] = 3
    original = _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    saved = state.drain(state.parent_id)
    result = saved.final_output["xiaox_result"]
    assert len(state.transports) == len(state.model_requests) == 1
    assert len(state.dispatches) == len(state.original_rows)
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )
    if original_state == "blocked":
        assert saved.metadata[JOB_KEY]["state"] == "blocked"
        assert not result["ok"] and result["retryable"] is False
        assert result["terminal_code"] == "goal_verification_budget_exhausted"
    else:
        assert result["ok"] and saved.metadata[JOB_KEY]["state"] == "verified", result
        assert bool(result["business_completed"]) is bool(state.original_rows)
        assert bool(result["reply_completed"]) is not bool(state.original_rows)
        if original_state == "verified":
            assert saved.metadata[JOB_KEY]["attempts"] == 3
            assert (
                saved.metadata["runtime_goal_verification"]
                == original.metadata["runtime_goal_verification"]
            )


@pytest.mark.parametrize(
    "pending_business_review", ["queued_process_loss_after_needs_work"], indirect=True
)
def test_committed_gap_report_recovers_to_original_compensation_without_repeating_the_write(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    assert state.crash_run.metadata[JOB_KEY]["state"] == "needs_work"
    original = _restore_last_pre_crash_commit(state)

    def no_more_writes(*_args, **_kwargs):
        pytest.fail("the persisted gap only needs an explanation, not another business write")

    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.AgentToolExecutor.execute", no_more_writes
    )
    state.script = lambda _binding, _text: "该客户用于记录业务往来；原客户已创建并核验。"
    state.review = lambda prompt: fixture_goal_review(prompt, kind="write")
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    saved = state.drain(state.parent_id)
    assert saved.final_output["xiaox_result"]["business_completed"] is True, saved.final_output
    assert len(state.dispatches) == 1 and state.names() == ["verification-only-customer"]
    assert len(state.transports) == len(state.model_requests) == 2
    assert any(
        entry.get("source") == "independent_goal_compensation"
        for entry in saved.metadata["runtime_requests"].values()
    )
    assert (
        saved.metadata["xiaox_runtime"]["thread_id"]
        == original.metadata["xiaox_runtime"]["thread_id"]
    )
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )
