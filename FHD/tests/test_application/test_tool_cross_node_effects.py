"""A replacement worker cannot replay a committed write after losing a local receipt."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.application.agent_orchestrator import tool_permission
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_background import (
    BackgroundTaskExecutionMixin,
    task_execution_context,
)
from app.application.agent_orchestrator.task_dispatcher import _open_effect
from app.application.agent_orchestrator.task_execution_repository import (
    set_task_execution_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import (
    AgentToolExecutor,
    execute_with_tool_deadline,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.db.models import Customer, JournalEntry, ReceivableAllocation, SalesOrder
from app.db.models.agent import AgentTaskExecutionRecord
from app.db.models.permission import Permission, Role
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.employee_test_identity import seed_employee_identity
from tests.test_db.test_agent_schema_concurrency import schema_engines as schema_engines


@pytest.fixture
def effects_db(schema_engines, tmp_path, monkeypatch):
    from app import db as host_db
    from app.domain.shared_services.session_service import SessionService
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth import agent_principal, dependencies

    engine, replacement = schema_engines
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        # The real spawned interpreter must use the same isolated test schema.
        engine = create_engine(engine.url.update_query_dict({"options": f"-csearch_path={schema}"}))
    factory = seed_employee_identity(engine, session_id="effect-session", username="effect-owner")
    with factory.begin() as db:
        role = db.query(Role).filter_by(name="admin").one()
        for code in ("tool.sales.payment", "tool.sales.query", "tool.finance.ledger_query"):
            role.permissions.append(Permission(code=code, name=code))
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "node-a.sqlite"))
    monkeypatch.setattr(host_db, "HostSessionLocal", factory)
    monkeypatch.setattr(host_db, "SessionLocal", factory)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", factory)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service", SessionService
    )
    monkeypatch.setattr(agent_principal, "resolve_session_user", dependencies.resolve_session_user)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tools/execute",
            "headers": [(b"x-session-id", b"effect-session")],
        }
    )
    actor_context = authenticated_runtime_context(
        {}, agent_principal.require_agent_principal(request, x_user_id=None)
    )
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    set_agent_run_repository_for_tests(runs)
    set_task_execution_repository_for_tests(queue)
    tool_permission.clear_idempotent_replay_for_tests()
    with tenant_scope(11), factory.begin() as db:
        customer = Customer(customer_name="Cross-node payment")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no="CROSS-NODE-PAYMENT",
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

    def prepare(*, read_only=False, approved=True):
        action = "query" if read_only else "payment"
        spec = get_tool_action_spec("sales", action)
        step = AgentStep(
            node_id="original",
            tool_id="sales",
            action=action,
            params={"order_id": order_id, "amount": 100} if not read_only else {},
            idempotent=spec.idempotent,
            risk=spec.risk,
            status="waiting_user",
        )
        run = AgentRun(
            user_id="11",
            message="Perform the approved operation once",
            status="waiting_user",
            metadata={"runtime_context": dict(actor_context)},
            steps=[step],
        )
        runs.save(run)
        queue.enqueue_waiting_approval(run, approver="11")
        if approved:
            token = issue_approval_grant(run, principal_id="11")["grant"]
            run = approve_and_enqueue(
                runs,
                queue,
                run_id=run.run_id,
                token=token,
                principal_id="11",
                runtime_context=actor_context,
                authenticated_binding=actor_context.get("_mod_authorization"),
                authenticated_actor_binding=actor_context["_actor_authorization"],
            )
            step = run.steps[0]
        context = {
            **actor_context,
            "run_id": run.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
            **task_execution_context(run, step),
        }
        claim = queue.claim("node-a", run_id=run.run_id, lease_seconds=120) if approved else None
        if claim is not None:
            step.status = run.status = "running"
        call = ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=copy.deepcopy(step.params),
            status="running",
            metadata={"idempotency_key": context["idempotency_key"]},
        )
        freeze_verification_contract(run, step, call, spec, context)
        run.tool_calls.append(call)
        runs.save(run)
        return SimpleNamespace(run=run, step=step, call=call, context=context, claim=claim)

    @contextmanager
    def owned(invocation):
        marker = _open_effect.set(
            (
                queue,
                invocation.run.run_id,
                "node-a",
                invocation.claim.execution_count if invocation.claim is not None else 0,
            )
        )
        try:
            if invocation.claim is not None:
                with worker_claim_scope(runs, invocation.claim, "node-a"):
                    yield
            else:
                yield
        finally:
            _open_effect.reset(marker)

    def execute(invocation, *, spawned=False):
        with owned(invocation):
            if spawned:
                return execute_with_tool_deadline(
                    AgentToolExecutor(),
                    invocation.step,
                    runtime_context=invocation.context,
                    timeout_seconds=40,
                )
            return AgentToolExecutor().execute(invocation.step, runtime_context=invocation.context)

    def new_node(invocation):
        tool_permission.drop_process_idempotency_memory()
        monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "node-b.sqlite"))
        other = SQLAlchemyTaskExecutionRepository(session_factory=sessionmaker(bind=replacement))
        expired = datetime.fromisoformat(invocation.claim.lease_expires_at) + timedelta(seconds=1)
        claim = other.claim(
            "node-b", run_id=invocation.run.run_id, lease_seconds=120, now=expired.isoformat()
        )
        return other, claim

    def payments(count, amount):
        with tenant_scope(11), factory() as db:
            assert db.query(ReceivableAllocation).count() == count
            assert db.query(JournalEntry).count() == count
            assert db.get(SalesOrder, order_id).paid_amount == Decimal(amount)

    try:
        yield SimpleNamespace(
            prepare=prepare,
            execute=execute,
            owned=owned,
            new_node=new_node,
            payments=payments,
            runs=runs,
            queue=queue,
            factory=factory,
        )
    finally:
        tool_permission.clear_idempotent_replay_for_tests()
        set_task_execution_repository_for_tests(None)
        set_agent_run_repository_for_tests(None)
        if engine is not schema_engines[0]:
            engine.dispose()


@pytest.mark.parametrize("spawned", [False, True], ids=["direct", "spawn"])
@pytest.mark.parametrize("receipt_saved", [False, True], ids=["lost-receipt", "verified-receipt"])
def test_replacement_reconciles_committed_payment_before_dispatch(
    effects_db, spawned, receipt_saved
):
    invocation = effects_db.prepare()
    assert invocation.step.idempotent  # This previously suppressed the shared SQL effect.
    result = effects_db.execute(invocation, spawned=spawned)
    assert result.get("success") is True, result
    effects_db.payments(1, "100.00")
    assert effects_db.queue.lifecycle(invocation.run.run_id)["effects"] == [invocation.step.step_id]
    if receipt_saved:
        invocation.step.status = invocation.call.status = "completed"
        invocation.step.output = invocation.call.output = copy.deepcopy(result)
        bind_execution_receipt(invocation.call)
        verify_step_result(
            run=invocation.run,
            step=invocation.step,
            call=invocation.call,
            context=invocation.context,
        )
        assert invocation.call.metadata["verification"]["status"] == "verified"
        effects_db.runs.save(invocation.run)
    other, recovered = effects_db.new_node(invocation)
    if receipt_saved:
        assert recovered is not None and recovered.recovery_count == 1
        stored = effects_db.runs.get(invocation.run.run_id)
        assert stored.steps[0].status == "completed"
        assert other.lifecycle(stored.run_id)["effects"] == []
        assert (
            other.finish(
                stored.run_id,
                "node-b",
                "completed",
                execution_count=recovered.execution_count,
            ).state
            == "succeeded"
        )
    else:
        assert recovered is None
        row = other.get(invocation.run.run_id)
        assert (row.state, row.last_error_code) == ("unknown", "needs_verification")
        assert other.lifecycle(row.run_id)["effects"] == [invocation.step.step_id]
        assert other.claim("node-c", lease_seconds=120) is None
    effects_db.payments(1, "100.00")


def test_read_only_step_can_recover_without_a_local_tool_ledger(effects_db):
    invocation = effects_db.prepare(read_only=True)
    assert effects_db.execute(invocation).get("success") is True
    assert effects_db.queue.lifecycle(invocation.run.run_id)["effects"] == []
    other, claim = effects_db.new_node(invocation)
    assert claim is not None and claim.recovery_count == 1
    run = effects_db.runs.get(invocation.run.run_id)
    assert BackgroundTaskExecutionMixin()._prepare_expired_execution_recovery(run)
    assert run.steps[0].status == "pending"
    assert other.lifecycle(run.run_id)["effects"] == []
    effects_db.payments(0, "0.00")


@pytest.mark.parametrize("refusal", ["identity", "schema", "approval"])
@pytest.mark.parametrize("older_effect", [False, True])
def test_host_preflight_refusal_neither_opens_nor_erases_an_effect(
    effects_db, refusal, older_effect
):
    invocation = effects_db.prepare(approved=refusal != "approval")
    if older_effect:
        if invocation.claim is None:
            # Existing uncertainty is independent of a later approval refusal.
            with effects_db.queue.transaction() as db:
                from app.domain.task_lifecycle.control import SessionBook

                book = SessionBook(db)
                body = book.get("agent", "11", invocation.run.run_id)
                body["effects"] = ["older-unknown-write"]
                book.put("agent", "11", invocation.run.run_id, body)
        else:
            assert effects_db.queue.mark_open_effect(
                invocation.run.run_id,
                "older-unknown-write",
                owner_id="node-a",
                execution_count=invocation.claim.execution_count,
            )
    if refusal == "identity":
        invocation.context.pop("idempotency_key")
    elif refusal == "schema":
        invocation.step.params.pop("amount")
    result = effects_db.execute(invocation)
    assert result["success"] is False, result
    expected = {
        "identity": "task_identity_required",
        "schema": "schema_validation_failed",
        "approval": "approval_required",
    }
    assert result["error_code"] == expected[refusal], result
    assert effects_db.queue.lifecycle(invocation.run.run_id)["effects"] == (
        ["older-unknown-write"] if older_effect else []
    )
    effects_db.payments(0, "0.00")


def test_restored_owner_generation_is_checked_in_effect_transaction(effects_db):
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost

    invocation = effects_db.prepare()
    with effects_db.factory.begin() as db:
        db.get(AgentTaskExecutionRecord, invocation.run.run_id).execution_count += 1
    with worker_claim_scope(effects_db.runs, invocation.claim, "node-a"):
        # No dispatcher ContextVar: use the same trusted restoration path as spawn.
        with pytest.raises(WorkerLeaseLost):
            AgentToolExecutor().execute(invocation.step, runtime_context=invocation.context)
    assert effects_db.queue.lifecycle(invocation.run.run_id)["effects"] == []
    effects_db.payments(0, "0.00")


def test_custom_executor_cannot_clear_effect_by_claiming_not_started(effects_db):
    invocation = effects_db.prepare()
    with effects_db.owned(invocation):
        execute_with_tool_deadline(
            SimpleNamespace(
                execute_with_deadline=lambda *args, **kwargs: {
                    "success": False,
                    "execution_status": "not_started",
                    "execution": {"outcome": "not_executed", "committed": False},
                }
            ),
            invocation.step,
            runtime_context=invocation.context,
            timeout_seconds=30,
        )
    assert effects_db.queue.lifecycle(invocation.run.run_id)["effects"] == [invocation.step.step_id]
    result = effects_db.queue.finish(
        invocation.run.run_id,
        "node-a",
        "failed",
        execution_count=invocation.claim.execution_count,
    )
    assert (result.state, result.last_error_code) == ("unknown", "needs_verification")
    effects_db.payments(0, "0.00")
