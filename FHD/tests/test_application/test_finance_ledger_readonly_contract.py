"""Exact ledger-query contract; no generic LOW-risk or name-based exemption."""

from datetime import date

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.application.agent_orchestrator.business_action_ledger import (
    BusinessActionLedger,
)
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.db.models import ChartOfAccount, JournalEntry, JournalEntryLine
from app.domain.shared_services.accounting_services import query_financial_ledger
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_only_reviewed_finance_read_is_exempt():
    spec = get_tool_action_spec("finance", "ledger_query")
    assert spec.read_only and spec.idempotent and spec.risk == "low"
    assert spec.permission == "tool.finance.ledger_query" and spec.required_params == []
    for action in (
        "journal_entry_create",
        "journal_entry_reverse",
        "chart_seed",
        "aging_report",
    ):
        assert not get_tool_action_spec("finance", action).read_only


@pytest.mark.parametrize("params", [{}, {"account_code": "1000"}, {"account_code": "missing"}])
def test_real_ledger_route_preserves_result_and_never_writes(trusted_actor, monkeypatch, params):
    actor = trusted_actor(permissions=["tool.finance.ledger_query"])
    denied = trusted_actor(role="no-finance", permissions=[])
    for tenant, number in ((7, "visible"), (8, "foreign")):
        with tenant_scope(tenant), actor.factory.begin() as db:
            account = ChartOfAccount(tenant_id=tenant, code="1000", name=number)
            db.add(account)
            db.flush()
            db.add(
                JournalEntry(
                    tenant_id=tenant,
                    entry_no=number,
                    journal_date=date(2026, 1, 1),
                    lines=[
                        JournalEntryLine(
                            tenant_id=tenant,
                            account_id=account.id,
                            account_code="1000",
                            debit=1,
                            credit=0,
                        )
                    ],
                )
            )
    with tenant_scope(7):
        expected = query_financial_ledger(**params)
    if not params:
        assert expected["total"] == 1 and expected["data"][0]["entry_no"] == "visible"
    elif params["account_code"] == "1000":
        assert expected["total"] == 1 and expected["data"][0]["entry_no"] == "visible"
        assert expected["account"]["name"] == "visible" and expected["data"][0]["debit"] == 1
    else:
        assert expected == {"success": False, "message": "科目不存在", "data": []}

    def dump():
        with actor.factory.kw["bind"].connect() as connection:
            return list(connection.connection.driver_connection.iterdump())

    def reject_claim(*args, **kwargs):
        pytest.fail("A pure ledger query must not claim the business-action ledger")

    def read_sql_only(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() in {"SELECT", "PRAGMA"}, statement

    monkeypatch.setattr(BusinessActionLedger, "claim", reject_claim)
    before = dump()
    event.listen(Engine, "before_cursor_execute", read_sql_only)
    try:
        executor = AgentToolExecutor()
        step = AgentStep(
            node_id="ledger-read",
            tool_id="finance",
            action="ledger_query",
            params=params,
        )
        assert executor.execute(step, runtime_context=actor.context) == expected
        assert executor.execute(step, runtime_context=actor.context) == expected
        for context, code in (
            ({}, "tool_identity_required"),
            (denied.context, "tool_permission_denied"),
        ):
            result = executor.execute(step, runtime_context=context)
            assert result["success"] is False and result["error_code"] == code
        forged = AgentStep(
            node_id="foreign",
            tool_id="finance",
            action="ledger_query",
            params={**params, "tenant_id": 8},
        )
        result = executor.execute(forged, runtime_context=actor.context)
        assert result["success"] is False and result["error_code"] == "tool_identity_override"
    finally:
        event.remove(Engine, "before_cursor_execute", read_sql_only)
    assert dump() == before
