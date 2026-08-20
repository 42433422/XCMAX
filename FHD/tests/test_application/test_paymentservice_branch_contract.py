from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application import paymentservice
from app.db.models.receivable_allocation import (
    RECEIVABLE_STATUS_PAID,
    RECEIVABLE_STATUS_PARTIAL,
    RECEIVABLE_STATUS_REFUNDED,
    RECEIVABLE_STATUS_UNPAID,
)


class _Query:
    def __init__(self, *, first: Any = None, rows: list[Any] | None = None):
        self.first_value = first
        self.rows = rows or []

    def filter(self, *_args: Any) -> _Query:
        return self

    def first(self) -> Any:
        return self.first_value

    def all(self) -> list[Any]:
        return self.rows


class _Db:
    def __init__(self, queries: dict[Any, _Query]):
        self.queries = queries
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False

    def query(self, model: Any) -> _Query:
        return self.queries[model]

    def add(self, value: Any) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, _value: Any) -> None:
        return None


def _db_context(db: _Db):
    @contextmanager
    def _manager():
        yield db

    return _manager()


def _order(total: str = "100") -> SimpleNamespace:
    return SimpleNamespace(total_amount=Decimal(total), paid_amount=0, payment_state="unpaid")


def _allocation(
    amount: str = "25", *, allocation_id: int = 7, sales_order_id: int | None = 3
) -> SimpleNamespace:
    return SimpleNamespace(
        id=allocation_id,
        sales_order_id=sales_order_id,
        allocated_amount=Decimal(amount),
        status=RECEIVABLE_STATUS_PARTIAL,
        allocated_at=None,
        to_dict=lambda: {"id": allocation_id, "allocated_amount": amount},
    )


def test_payment_helpers_cover_decimal_status_and_line_lookup() -> None:
    assert paymentservice._to_decimal(None) == 0
    assert paymentservice._to_decimal(Decimal("1.2")) == Decimal("1.2")
    assert paymentservice._to_decimal(2.5) == Decimal("2.5")
    assert paymentservice._compute_status(Decimal("0"), Decimal("10")) == (RECEIVABLE_STATUS_UNPAID)
    assert paymentservice._compute_status(Decimal("2"), Decimal("10")) == (
        RECEIVABLE_STATUS_PARTIAL
    )
    assert paymentservice._compute_status(Decimal("9.999"), Decimal("10")) == (
        RECEIVABLE_STATUS_PAID
    )
    rows = [_allocation("1"), _allocation("2")]
    assert paymentservice._sum_allocated(rows) == Decimal("3")
    assert paymentservice._find_line_id({}, "1122") is None
    assert (
        paymentservice._find_line_id({"lines": [{"account_code": "1001", "id": 1}]}, "1122") is None
    )
    assert paymentservice._find_line_id({"lines": [{"account_code": "1122", "id": 8}]}, "1122") == 8


def test_existing_allocations_uses_active_order_scope() -> None:
    rows = [_allocation()]
    db = _Db({paymentservice.ReceivableAllocation: _Query(rows=rows)})
    assert paymentservice._existing_allocations(db, 3) == rows


@pytest.mark.parametrize("amount", [0, -1])
def test_payment_rejects_non_positive_amount(amount: int) -> None:
    assert paymentservice.payment(sales_order_id=1, amount=amount)["success"] is False


def test_payment_missing_idempotent_and_overpayment_paths() -> None:
    missing_db = _Db({paymentservice.SalesOrder: _Query(first=None)})
    with patch.object(paymentservice, "get_db", return_value=_db_context(missing_db)):
        assert paymentservice.payment(sales_order_id=1, amount=1)["success"] is False

    existing = _allocation("25")
    idempotent_db = _Db({paymentservice.SalesOrder: _Query(first=_order())})
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(idempotent_db)),
        patch.object(paymentservice, "_existing_allocations", return_value=[existing]),
    ):
        result = paymentservice.payment(sales_order_id=1, amount="25")
    assert result["idempotent"] is True

    over_db = _Db({paymentservice.SalesOrder: _Query(first=_order("30"))})
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(over_db)),
        patch.object(paymentservice, "_existing_allocations", return_value=[existing]),
    ):
        result = paymentservice.payment(sales_order_id=1, amount="10")
    assert result["success"] is False and "超应收" in result["message"]


def test_payment_journal_failure_success_and_rollback() -> None:
    failed_db = _Db({paymentservice.SalesOrder: _Query(first=_order())})
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(failed_db)),
        patch.object(paymentservice, "_existing_allocations", return_value=[]),
        patch.object(
            paymentservice,
            "create_journal_entry",
            return_value={"success": False, "message": "journal failed"},
        ),
    ):
        result = paymentservice.payment(sales_order_id=1, amount="25")
    assert result["message"] == "journal failed" and failed_db.rollbacks == 1

    success_order = _order("25")
    success_db = _Db({paymentservice.SalesOrder: _Query(first=success_order)})
    journal = {
        "success": True,
        "data": {"id": 9, "lines": [{"account_code": "1122", "id": 11}]},
    }
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(success_db)),
        patch.object(paymentservice, "_existing_allocations", return_value=[]),
        patch.object(paymentservice, "create_journal_entry", return_value=journal) as create,
    ):
        result = paymentservice.payment(
            sales_order_id=1,
            amount="25",
            partner_id=2,
            partner_name="甲",
            reference="R1",
            journal_date=date(2026, 1, 2),
        )
    assert result["success"] is True
    assert success_order.payment_state == RECEIVABLE_STATUS_PAID
    assert success_order.paid_amount == Decimal("25")
    assert success_db.commits == 1 and len(success_db.added) == 1
    assert create.call_args.args[0]["description"].endswith("-R1")

    rollback_db = _Db({paymentservice.SalesOrder: _Query(first=_order())})
    rollback_db.fail_commit = True
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(rollback_db)),
        patch.object(paymentservice, "_existing_allocations", return_value=[]),
        patch.object(paymentservice, "create_journal_entry", return_value=journal),
    ):
        result = paymentservice.payment(sales_order_id=1, amount="25")
    assert result["success"] is False and rollback_db.rollbacks == 1


def test_refund_missing_already_refunded_and_journal_failure() -> None:
    missing_db = _Db({paymentservice.ReceivableAllocation: _Query(first=None)})
    with patch.object(paymentservice, "get_db", return_value=_db_context(missing_db)):
        assert paymentservice.refund(allocation_id=1)["success"] is False

    refunded = _allocation()
    refunded.status = RECEIVABLE_STATUS_REFUNDED
    refunded_db = _Db({paymentservice.ReceivableAllocation: _Query(first=refunded)})
    with patch.object(paymentservice, "get_db", return_value=_db_context(refunded_db)):
        assert "不能重复" in paymentservice.refund(allocation_id=1)["message"]

    alloc = _allocation()
    failed_db = _Db({paymentservice.ReceivableAllocation: _Query(first=alloc)})
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(failed_db)),
        patch.object(
            paymentservice,
            "create_journal_entry",
            return_value={"success": False, "message": "journal failed"},
        ),
    ):
        result = paymentservice.refund(allocation_id=7)
    assert result["message"] == "journal failed" and failed_db.rollbacks == 1


def test_refund_success_without_order_and_commit_failure() -> None:
    journal = {"success": True, "data": {"id": 10, "lines": []}}
    alloc = _allocation(sales_order_id=None)
    db = _Db({paymentservice.ReceivableAllocation: _Query(first=alloc)})
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(db)),
        patch.object(paymentservice, "create_journal_entry", return_value=journal),
    ):
        result = paymentservice.refund(
            allocation_id=7, reference="R", journal_date=date(2026, 1, 2)
        )
    assert result["success"] is True and alloc.status == RECEIVABLE_STATUS_REFUNDED
    assert db.commits == 1 and len(db.added) == 1

    failed_alloc = _allocation()
    failed_db = _Db({paymentservice.ReceivableAllocation: _Query(first=failed_alloc)})
    failed_db.fail_commit = True
    with (
        patch.object(paymentservice, "get_db", return_value=_db_context(failed_db)),
        patch.object(paymentservice, "create_journal_entry", return_value=journal),
        patch.object(paymentservice, "_update_order_after_refund"),
    ):
        result = paymentservice.refund(allocation_id=7)
    assert result["success"] is False and failed_db.rollbacks == 1


def test_refund_updates_order_state_and_handles_missing_orders() -> None:
    alloc = _allocation("25")
    missing_db = _Db({paymentservice.SalesOrder: _Query(first=None)})
    paymentservice._update_order_after_refund(missing_db, alloc)

    no_order_alloc = _allocation(sales_order_id=None)
    order = _order()
    no_order_db = _Db({paymentservice.SalesOrder: _Query(first=order)})
    paymentservice._update_order_after_refund(no_order_db, no_order_alloc)
    assert order.paid_amount == 0

    remaining = _allocation("20", allocation_id=8)
    db = _Db({paymentservice.SalesOrder: _Query(first=order)})
    with patch.object(paymentservice, "_existing_allocations", return_value=[alloc, remaining]):
        paymentservice._update_order_after_refund(db, alloc)
    assert order.paid_amount == Decimal("20")
    assert order.payment_state == RECEIVABLE_STATUS_PARTIAL
