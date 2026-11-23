"""Sales verification reads real transactions and never replays a command."""

import copy

import pytest
from sqlalchemy import event

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.sales_app_service import SalesAppService
from app.db.models import InventoryTransaction, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_enterprise_acceptance import _seed_order
from tests.test_application.test_verification_readback import invocation


@pytest.fixture
def sales(trusted_actor, monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    from app.db.models.permission import DEFAULT_ROLES

    permissions = next(row["permissions"] for row in DEFAULT_ROLES if row["name"] == "admin")
    actor = trusted_actor(role="admin", permissions=[*permissions, "tool.finance.ledger_query"])
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    order_id, item_id, warehouse_id, _ = _seed_order(actor)
    return (
        actor,
        SalesAppService(),
        {"order_id": order_id, "item_id": item_id, "warehouse_id": warehouse_id},
    )


def prepare(sales, action, *, idempotency_key=None):
    actor, service, ids = sales
    params = {"order_id": ids["order_id"]}
    if action == "deliver":
        params.update(item_id=ids["item_id"], warehouse_id=ids["warehouse_id"], quantity=4)
    if action == "payment":
        params["amount"] = 100
    if idempotency_key is not None:
        params["idempotency_key"] = idempotency_key
    if action == "credit_note":
        with tenant_scope(actor.tenant_id):
            assert service.invoice(ids["order_id"])["success"]
    case = invocation(actor, tool="sales", action=action, params=params)
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("sales", action), case.context
    )
    assert case.call.metadata["verification_contract"]["authority_baseline"]["status"] == "observed"
    return case


def effect(sales, case):
    actor, service, _ = sales
    with tenant_scope(actor.tenant_id):
        return getattr(service, case.step.action)(**case.step.params)


def verify(case, output):
    case.step.status = case.call.status = "completed"
    case.step.output = copy.deepcopy(output)
    case.call.output = copy.deepcopy(output)
    bind_execution_receipt(case.call)
    return verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)


@pytest.mark.parametrize(
    "action", ["confirm", "cancel", "deliver", "invoice", "payment", "credit_note"]
)
def test_sales_effect_requires_authoritative_readback_and_reverification_is_read_only(
    sales, action
):
    case = prepare(sales, action)
    output = effect(sales, case)
    assert output["success"], output
    actor = sales[0]
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            result = verify(case, output)
            assert result["status"] == "verified", result
            assert result["checks"][0]["evidence"]["postcondition_verified"]
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "action", ["confirm", "cancel", "deliver", "invoice", "payment", "credit_note"]
)
def test_claimed_success_without_the_real_effect_is_not_evidence(sales, action):
    case = prepare(sales, action)
    result = verify(case, {"success": True, "verified": True, "data": {"id": sales[2]["order_id"]}})
    assert result["accepted"] is False


@pytest.mark.parametrize(
    "action", ["confirm", "cancel", "deliver", "invoice", "payment", "credit_note"]
)
def test_returned_foreign_identity_cannot_replace_original_request(sales, action):
    case = prepare(sales, action)
    output = effect(sales, case)
    output["data"]["item_id" if action == "deliver" else "id"] = 99999
    assert verify(case, output)["accepted"] is False


def test_other_tenant_order_and_revoked_read_permission_are_not_read(sales, monkeypatch):
    from app.db.models.permission import Role

    case = prepare(sales, "confirm")
    output = effect(sales, case)
    actor = sales[0]
    with actor.factory.begin() as db:
        db.query(Role).filter_by(name="admin").one().permissions = []
    assert verify(case, output)["accepted"] is False
    forged = dict(case.context, tenant_id=str(actor.tenant_id + 1))
    assert (
        verify_step_result(run=case.run, step=case.step, call=case.call, context=forged)["accepted"]
        is False
    )


def test_real_foreign_order_cannot_supply_a_verification_baseline(sales):
    actor = sales[0]
    with tenant_scope(actor.tenant_id + 1), actor.factory.begin() as db:
        foreign = SalesOrder(order_no="foreign-order", state="quote", total_amount=100)
        db.add(foreign)
        db.flush()
        order_id = foreign.id
    case = invocation(actor, tool="sales", action="confirm", params={"order_id": order_id})
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("sales", "confirm"), case.context
    )
    assert (
        case.call.metadata["verification_contract"]["authority_baseline"]["status"] == "unavailable"
    )
    assert (
        verify(case, {"success": True, "data": {"id": order_id, "state": "sale"}})["accepted"]
        is False
    )


def test_sales_query_is_a_read_contract_and_write_actions_still_need_evidence(sales):
    actor, service, _ = sales
    case = invocation(actor, tool="sales", action="query", params={})
    spec = get_tool_action_spec("sales", "query")
    assert spec.read_only is True
    freeze_verification_contract(case.run, case.step, case.call, spec, case.context)
    statements = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement.split()[0].upper())

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with tenant_scope(actor.tenant_id):
            output = service.query()
        assert output["data"][0]["id"] == sales[2]["order_id"]
        assert verify(case, output)["status"] == "not_required"
        assert not {"INSERT", "UPDATE", "DELETE"}.intersection(statements)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    for action in ("confirm", "cancel", "deliver", "invoice", "payment", "credit_note"):
        assert get_tool_action_spec("sales", action).read_only is False
        write = prepare(sales, action)
        assert verify(write, {"success": True})["accepted"] is False


def test_partial_payment_business_status_does_not_hide_unknown_execution(sales):
    from app.domain.task_lifecycle.results import (
        execution_result_error,
        execution_result_outcome_unknown,
    )

    case = prepare(sales, "payment")
    output = effect(sales, case)
    assert output["data"]["status"] == "partial"
    assert execution_result_error(output) == ""
    assert execution_result_outcome_unknown(output) is False
    for execution in (
        {"execution_state": "unknown"},
        {"execution_state": "rejected"},
        {"reconciliation_required": True},
        {"pending_approval": True},
    ):
        forged = copy.deepcopy(output)
        forged["data"].update(execution)
        assert execution_result_error(forged)
        assert verify(case, forged)["accepted"] is False


def test_partial_payment_completes_original_approved_task_once(sales, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models import ReceivableAllocation
    from tests.test_application.test_enterprise_acceptance import _approve_and_execute

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = sales[0]
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    orchestrator = AgentOrchestrator(repository=repository, tool_executor=executor)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda repo: AgentOrchestrator(
            repository=repo, tool_executor=executor
        ),
    )
    plan = PlanGraph(
        plan_id="partial-payment",
        intent="register_partial_payment",
        nodes=[
            WorkflowNode(
                "pay",
                "sales",
                "payment",
                {"order_id": sales[2]["order_id"], "amount": 100},
                risk="high",
                idempotent=True,
            )
        ],
        metadata={"approval_required_node_ids": ["pay"]},
    )
    run = orchestrator.start_task_from_plan(
        user_id=str(actor.user_id),
        message="登记100元部分收款",
        plan=plan,
        runtime_context=actor.context,
    )
    assert run.status == "waiting_user" and not run.tool_calls
    completed, _ = _approve_and_execute(actor, repository, queue, dispatcher, run)
    assert completed.status == "completed", completed.to_dict()
    assert completed.tool_calls[0].output["data"]["status"] == "partial"
    assert completed.tool_calls[0].metadata["verification"]["status"] == "verified"
    assert queue.get(run.run_id).state == "succeeded"
    assert queue.claim("duplicate-worker", run_id=run.run_id, lease_seconds=30) is None
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.get(SalesOrder, sales[2]["order_id"]).paid_amount == 100
        assert db.query(ReceivableAllocation).count() == 1


def test_unrelated_existing_delivery_cannot_satisfy_a_new_call(sales):
    first = prepare(sales, "deliver")
    first_output = effect(sales, first)
    case = prepare(sales, "deliver")
    assert verify(case, first_output)["accepted"] is False


@pytest.mark.parametrize("action", ["deliver", "payment"])
def test_exact_business_idempotency_key_can_read_original_effect(sales, action):
    first = prepare(sales, action, idempotency_key="original-business-request")
    first_output = effect(sales, first)
    assert verify(first, first_output)["accepted"]
    case = prepare(sales, action, idempotency_key="original-business-request")
    output = effect(sales, case)
    assert output["idempotent"]
    assert verify(case, output)["accepted"]
    case.step.params["quantity" if action == "deliver" else "amount"] = 3
    case.call.params = copy.deepcopy(case.step.params)
    assert verify(case, output)["accepted"] is False


def test_unknown_or_rejected_receipts_do_not_become_verified(sales):
    case = prepare(sales, "confirm")
    effect(sales, case)
    for output in (
        {"success": False, "message": "rejected"},
        {"success": True, "outcome": "unknown", "reconciliation_required": True},
    ):
        assert verify(case, output)["accepted"] is False


def test_missing_inventory_movement_is_not_hidden_by_updated_order(sales):
    case = prepare(sales, "deliver")
    output = effect(sales, case)
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.query(InventoryTransaction).delete()
        assert db.get(SalesOrder, sales[2]["order_id"]).items[0].delivered_quantity == 4
    assert verify(case, output)["accepted"] is False
