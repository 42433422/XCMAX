"""Verify original finance transaction mutations in the tenant ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.agent_orchestrator.run_models import AgentStep, ToolCall
from app.application.agent_orchestrator.verification_readback import _report
from app.db.models import FinancialTransaction

FINANCE_ACTIONS = frozenset({"create_transaction", "update_transaction", "delete_transaction"})
_FINANCE_UPDATABLE_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "description",
        "status",
        "due_date",
        "transaction_date",
        "counterparty_name",
        "counterparty_id",
        "reference_type",
        "reference_id",
    }
)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def verify_finance_creation(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read back the exact approved transaction from the original tenant."""
    from app.application.agent_orchestrator.verification_transactions import (
        _order,
        _transaction_read_scope,
    )
    from app.application.finance_app_service import _parse_dt, _valid_finance_amount

    source = "finance_sql"
    data = output.get("data")
    if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0:
        return _report("inconclusive", "result_finance_identity_missing", source)
    expected = {"currency": "CNY", **step.params}
    amount = _valid_finance_amount(expected.pop("amount", None))
    for field in ("transaction_date", "due_date"):
        if field in expected:
            parsed = _parse_dt(expected[field])
            if parsed is None:
                return _report("failed", "result_finance_effect_mismatch", source)
            expected[field] = parsed.replace(tzinfo=None).isoformat()
    reference = str(expected.get("reference_id") or "")
    if reference.isdecimal():
        expected["reference_id"] = int(reference)

    with _transaction_read_scope(context, {"tool.finance.ledger_query"}, source) as (db, tenant):
        row = _order(db, tenant, data["id"], FinancialTransaction)
        if row is None:
            return _report("inconclusive", "result_finance_record_unavailable", source)
        started = datetime.fromisoformat(call.started_at).astimezone(UTC).replace(tzinfo=None)
        historical = row.created_at < started
        if historical and not (expected.get("reference_type") and reference):
            return _report("failed", "result_finance_effect_mismatch", source)
        if not historical:
            expected.setdefault("status", "pending")
        snapshot = row.to_dict()
        if (
            row.amount != amount
            or data != snapshot
            or any(snapshot.get(key) != value for key, value in expected.items())
        ):
            return _report("failed", "result_finance_effect_mismatch", source)
        return _report(
            "verified", "result_verified", source, transaction_id=row.id, historical=historical
        )


def verify_finance_update(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read back the exact updated transaction from the original tenant."""
    from app.application.agent_orchestrator.verification_transactions import (
        _order,
        _transaction_read_scope,
    )
    from app.application.finance_app_service import _parse_dt, _valid_finance_amount

    source = "finance_sql"
    txn_id = _positive_int(step.params.get("transaction_id"))
    data = output.get("data")
    if (
        txn_id is None
        or not isinstance(data, dict)
        or type(data.get("id")) is not int
        or data["id"] <= 0
    ):
        return _report("inconclusive", "result_finance_identity_missing", source)
    if data["id"] != txn_id:
        return _report("failed", "result_finance_effect_mismatch", source)

    expected = {
        key: value
        for key, value in step.params.items()
        if key in _FINANCE_UPDATABLE_FIELDS and value is not None
    }
    amount = _valid_finance_amount(expected.pop("amount")) if "amount" in expected else None
    for field in ("transaction_date", "due_date"):
        if field in expected:
            parsed = _parse_dt(expected[field])
            if parsed is None:
                return _report("failed", "result_finance_effect_mismatch", source)
            expected[field] = parsed.replace(tzinfo=None).isoformat()
    if "reference_id" in expected and str(expected["reference_id"]).isdecimal():
        expected["reference_id"] = int(str(expected["reference_id"]))

    with _transaction_read_scope(context, {"tool.finance.ledger_query"}, source) as (db, tenant):
        row = _order(db, tenant, txn_id, FinancialTransaction)
        if row is None:
            return _report("inconclusive", "result_finance_record_unavailable", source)
        started = datetime.fromisoformat(call.started_at).astimezone(UTC).replace(tzinfo=None)
        if row.updated_at is None or row.updated_at < started:
            return _report("failed", "result_finance_effect_mismatch", source)
        snapshot = row.to_dict()
        if (
            (amount is not None and row.amount != amount)
            or data != snapshot
            or any(snapshot.get(key) != value for key, value in expected.items())
        ):
            return _report("failed", "result_finance_effect_mismatch", source)
        return _report(
            "verified",
            "result_verified",
            source,
            transaction_id=row.id,
            action="update_transaction",
        )


def verify_finance_deletion(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Confirm the deleted transaction no longer exists in the original tenant."""
    from app.application.agent_orchestrator.verification_transactions import (
        _order,
        _transaction_read_scope,
    )

    source = "finance_sql"
    txn_id = _positive_int(step.params.get("transaction_id"))
    if txn_id is None:
        return _report("inconclusive", "result_finance_identity_missing", source)
    if output.get("success") is not True:
        return _report("failed", "result_finance_effect_mismatch", source)

    with _transaction_read_scope(context, {"tool.finance.ledger_query"}, source) as (db, tenant):
        row = _order(db, tenant, txn_id, FinancialTransaction)
        if row is not None:
            return _report("failed", "result_finance_effect_mismatch", source)
        return _report("verified", "result_verified", source, transaction_id=txn_id, deleted=True)


def verify_finance_result(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch finance write verification across create, update, and delete."""
    if step.action == "create_transaction":
        return verify_finance_creation(step, call, output, context)
    if step.action == "update_transaction":
        return verify_finance_update(step, call, output, context)
    if step.action == "delete_transaction":
        return verify_finance_deletion(step, call, output, context)
    return _report("inconclusive", "result_verifier_unavailable", "finance_sql")
