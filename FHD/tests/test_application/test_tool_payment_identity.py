"""Real approved payment writes must keep their identity across tool retries."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import tool_permission
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_repository import (
    set_task_execution_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.facades import tools_facade
from app.db.models import Customer, JournalEntry, ReceivableAllocation, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def payment_call(trusted_actor, tmp_path, monkeypatch):
    spec = get_tool_action_spec("sales", "payment")
    actor = trusted_actor(role="payment-clerk", permissions=[spec.permission])
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    tool_permission.clear_idempotent_replay_for_tests()
    runs = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(runs)
    set_task_execution_repository_for_tests(queue)

    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        customer = Customer(customer_name="Approved payment regression")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no="TOOL-PAYMENT-IDENTITY",
            customer_id=customer.id,
            customer_name=customer.customer_name,
            state="confirmed",
            status="confirmed",
            total_amount=Decimal("1000.00"),
            paid_amount=0,
            payment_state="unpaid",
        )
        db.add(order)
        db.flush()
        order_id = order.id

    run = AgentRun(
        user_id=str(actor.user_id),
        message="Post the approved payment once",
        status="waiting_user",
        metadata={"runtime_context": dict(actor.context)},
        steps=[
            AgentStep(
                node_id="payment",
                tool_id="sales",
                action="payment",
                params={"order_id": order_id, "amount": 100},
                status="waiting_user",
            )
        ],
    )
    runs.save(run)
    queue.enqueue_waiting_approval(run, approver=str(actor.user_id))
    calls = []
    dispatch = tools_facade.execute_registered_workflow_tool

    def record_dispatch(*args, **kwargs):
        calls.append(args[:2])
        return dispatch(*args, **kwargs)

    monkeypatch.setattr(tools_facade, "execute_registered_workflow_tool", record_dispatch)

    def context(current):
        return {
            **actor.context,
            "run_id": current.run_id,
            **task_execution_context(current, current.steps[0]),
            **(
                {"_tool_approval_scope": current.metadata["approval_receipt"]}
                if "approval_receipt" in current.metadata
                else {}
            ),
        }

    def approve():
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        approved = approve_and_enqueue(
            runs,
            queue,
            run_id=run.run_id,
            token=grant["grant"],
            principal_id=str(actor.user_id),
            runtime_context=dict(actor.context),
            authenticated_binding=actor.context.get("_mod_authorization"),
            authenticated_actor_binding=actor.context["_actor_authorization"],
        )
        assert queue.get(run.run_id).state == "queued"
        return approved.steps[0], context(approved)

    def assert_payments(count, amount):
        with tenant_scope(actor.tenant_id), actor.factory() as db:
            assert db.query(ReceivableAllocation).count() == count
            assert db.query(JournalEntry).count() == count
            assert db.get(SalesOrder, order_id).paid_amount == Decimal(amount)

    try:
        yield SimpleNamespace(
            step=run.steps[0],
            context=context(run),
            approve=approve,
            calls=calls,
            assert_payments=assert_payments,
        )
    finally:
        set_task_execution_repository_for_tests(None)
        set_agent_run_repository_for_tests(None)
        tool_permission.clear_idempotent_replay_for_tests()


def test_idempotent_payment_without_business_identity_never_dispatches(payment_call):
    step, context = payment_call.approve()
    # The payment contract is idempotent only when its optional key is present.
    # Without this executor guard the real service posts two distinct receipts.
    assert get_tool_action_spec("sales", "payment").idempotent
    context.pop("idempotency_key")
    for _ in range(2):
        result = AgentToolExecutor().execute(step, runtime_context=context)
        assert result["error_code"] == "task_identity_required", result
        assert result["execution_status"] == "not_started"
        tool_permission.drop_process_idempotency_memory()
    assert payment_call.calls == []
    payment_call.assert_payments(0, "0.00")


def test_approved_payment_replay_survives_lost_memory_and_rejects_changed_amount(payment_call):
    step, context = payment_call.approve()
    first = AgentToolExecutor().execute(step, runtime_context=context)
    assert first["success"] is True, first
    payment_call.assert_payments(1, "100.00")

    tool_permission.drop_process_idempotency_memory()
    replay = AgentToolExecutor().execute(step, runtime_context=context)
    assert replay["success"] is True, replay
    assert replay["data"]["id"] == first["data"]["id"]
    assert len(payment_call.calls) == 1
    payment_call.assert_payments(1, "100.00")

    tool_permission.drop_process_idempotency_memory()
    changed = replace(step, params={**step.params, "amount": 200})
    conflict = AgentToolExecutor().execute(changed, runtime_context=context)
    assert conflict["error_code"] == "idempotency_conflict", conflict
    assert len(payment_call.calls) == 1
    payment_call.assert_payments(1, "100.00")


def test_stable_payment_identity_does_not_bypass_pending_approval(payment_call):
    result = AgentToolExecutor().execute(payment_call.step, runtime_context=payment_call.context)
    assert result["error_code"] == "approval_required", result
    assert payment_call.calls == []
    payment_call.assert_payments(0, "0.00")


@pytest.mark.parametrize(
    "first_key,retry_key", [(None, "new"), ("first", "changed"), ("first", None)]
)
def test_approved_payment_client_key_changes_cannot_rename_the_server_intent(
    payment_call, first_key, retry_key
):
    step, context = payment_call.approve()
    first_step = replace(
        step, params={**step.params, **({"idempotency_key": first_key} if first_key else {})}
    )
    first = AgentToolExecutor().execute(first_step, runtime_context=context)
    assert first["success"] is True, first
    tool_permission.drop_process_idempotency_memory()

    retry_step = replace(
        step, params={**step.params, **({"idempotency_key": retry_key} if retry_key else {})}
    )
    replay = AgentToolExecutor().execute(retry_step, runtime_context=context)

    assert replay["success"] is True, replay
    assert replay["data"]["id"] == first["data"]["id"]
    assert len(payment_call.calls) == 1
    payment_call.assert_payments(1, "100.00")
