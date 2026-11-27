"""Finance deletion needs original scoped prestate and read-only postconditions."""

import copy

import pytest
from sqlalchemy import event

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.finance_app_service import FinanceAppService
from app.db.models import FinancialTransaction
from app.infrastructure.tenant_scope import owned_tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_verification_readback import invocation


def _prepare(actor, transaction_id):
    case = invocation(actor, "finance", "delete_transaction", {"transaction_id": transaction_id})
    freeze_verification_contract(
        case.run,
        case.step,
        case.call,
        get_tool_action_spec("finance", "delete_transaction"),
        case.context,
    )
    return case


def _verify(case, output):
    case.step.status = case.call.status = "completed"
    case.step.output = copy.deepcopy(output)
    case.call.output = copy.deepcopy(output)
    bind_execution_receipt(case.call)
    return verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)


@pytest.fixture
def finance(trusted_actor):
    actor = trusted_actor(role="finance", permissions=["tool.finance.ledger_query"])
    service = FinanceAppService()
    with owned_tenant_scope(actor.tenant_id):
        created = service.create_transaction({"transaction_type": "revenue", "amount": 500})
    assert created["success"] is True
    return actor, service, created["data"]["id"]


@pytest.mark.parametrize("prestate", ["nonexistent", "foreign_tenant", "already_deleted"])
def test_absence_cannot_certify_an_unobserved_finance_deletion(finance, trusted_actor, prestate):
    owner, service, transaction_id = finance
    observer = owner
    target = transaction_id
    if prestate == "nonexistent":
        target += 1000
    elif prestate == "foreign_tenant":
        observer = trusted_actor(
            role="finance", tenant_id=8, permissions=["tool.finance.ledger_query"]
        )
    else:
        with owned_tenant_scope(owner.tenant_id):
            assert service.delete_transaction(transaction_id)["success"] is True
    case = _prepare(observer, target)
    report = _verify(case, {"success": True, "message": "claimed deletion"})
    assert report["status"] == "inconclusive", report
    assert report["accepted"] is False
    assert report["code"] == "result_finance_baseline_unavailable"
    with owned_tenant_scope(owner.tenant_id), owner.factory() as db:
        assert (db.get(FinancialTransaction, transaction_id) is None) == (
            prestate == "already_deleted"
        )


def test_legacy_finance_contract_without_prestate_cannot_certify_absence(finance):
    owner, service, transaction_id = finance
    case = _prepare(owner, transaction_id)
    contract = case.call.metadata["verification_contract"]
    contract.pop("authority_baseline", None)
    contract["contract_sha256"] = canonical_hash(
        {key: value for key, value in contract.items() if key != "contract_sha256"}
    )
    with owned_tenant_scope(owner.tenant_id):
        output = service.delete_transaction(transaction_id)
    assert output["success"] is True
    report = _verify(case, output)
    assert report["status"] == "inconclusive", report
    assert report["accepted"] is False
    assert report["code"] == "result_finance_baseline_unavailable"


def test_original_finance_deletion_receipt_can_be_reverified_without_writes(finance):
    owner, service, transaction_id = finance
    case = _prepare(owner, transaction_id)
    with owned_tenant_scope(owner.tenant_id):
        output = service.delete_transaction(transaction_id)
    assert output["success"] is True
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = owner.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            report = _verify(case, output)
            assert report["status"] == "verified", report
            assert report["accepted"] is True
            assert report["checks"][0]["evidence"]["transaction_id"] == transaction_id
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)
