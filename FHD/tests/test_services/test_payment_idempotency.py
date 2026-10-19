"""Real-DB regressions for payment identity, tenant scope and concurrent balances."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import payment_service as service
from app.db.base import Base
from app.db.models import Customer, JournalEntry, ReceivableAllocation, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def payment_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'receipts.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @contextmanager
    def scope():
        with factory.begin() as db:
            yield db

    monkeypatch.setattr(service, "get_db", scope)
    with tenant_scope(1), scope() as db:
        customer = Customer(customer_name="Receipt regression")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no="IDEMPOTENCY-REGRESSION",
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
    yield scope, order_id
    engine.dispose()


def pay(order_id, key, amount="500.00", **kwargs):
    with tenant_scope(1):
        return service.payment(
            sales_order_id=order_id,
            amount=Decimal(amount),
            idempotency_key=key,
            **kwargs,
        )


def test_equal_installments_with_distinct_keys_both_post(payment_db):
    scope, order_id = payment_db
    first, second = pay(order_id, "bank-1"), pay(order_id, "bank-2")
    assert first["success"] and second["success"]
    assert first["data"]["id"] != second["data"]["id"]
    with tenant_scope(1), scope() as db:
        assert db.query(ReceivableAllocation).count() == 2
        assert db.query(JournalEntry).count() == 2
        assert db.get(SalesOrder, order_id).paid_amount == Decimal("1000.00")


def test_retry_survives_new_session_and_full_payment(payment_db):
    scope, order_id = payment_db
    first = pay(order_id, "bank-1", "1000.00")
    second = pay(order_id, "bank-1", "1000.00")
    assert second["success"] and second["idempotent"]
    assert first["data"]["id"] == second["data"]["id"]
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"amount": "400.00"},
        {"partner_id": 5},
        {"partner_name": "other"},
        {"reference": "another"},
        {"journal_date": date(2026, 10, 21)},
    ],
)
def test_key_payload_conflict_is_rejected(payment_db, changed):
    scope, order_id = payment_db
    assert pay(order_id, "same")["success"]
    result = pay(order_id, "same", **changed)
    assert not result["success"] and result["code"] == "IDEMPOTENCY_CONFLICT"
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 1


def test_refunded_key_cannot_post_a_new_payment(payment_db):
    scope, order_id = payment_db
    first = pay(order_id, "bank-1")
    with tenant_scope(1):
        assert service.refund(allocation_id=first["data"]["id"])["success"]
    retry = pay(order_id, "bank-1")
    assert retry["idempotent"] and retry["data"]["status"] == "refunded"
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 2
        assert db.get(SalesOrder, order_id).paid_amount == 0


def test_concurrent_retry_posts_one_receipt(payment_db):
    scope, order_id = payment_db
    barrier = threading.Barrier(4)

    def worker(_):
        barrier.wait(timeout=10)
        return pay(order_id, "concurrent", "400.00")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(4)))
    assert all(result["success"] for result in results)
    assert len({result["data"]["id"] for result in results}) == 1
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 1


def test_concurrent_distinct_payments_cannot_overpay(payment_db):
    scope, order_id = payment_db
    barrier = threading.Barrier(2)

    def worker(key):
        barrier.wait(timeout=10)
        return pay(order_id, key, "600.00")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ("a", "b")))
    assert sum(bool(result["success"]) for result in results) == 1
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 1
        assert db.get(SalesOrder, order_id).paid_amount == Decimal("600.00")


def test_other_tenant_cannot_lock_or_replay(payment_db):
    scope, order_id = payment_db
    assert pay(order_id, "bank-1")["success"]
    with tenant_scope(2):
        result = service.payment(
            sales_order_id=order_id, amount=500, idempotency_key="bank-1"
        )
    assert not result["success"]
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 1


def test_external_transaction_rollback_removes_receipt_and_identity(payment_db):
    scope, order_id = payment_db
    with pytest.raises(RuntimeError, match="abort"), tenant_scope(1), scope() as db:
        assert service.payment(
            sales_order_id=order_id, amount=500, idempotency_key="rollback", db=db
        )["success"]
        raise RuntimeError("abort")
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 0
        assert db.query(ReceivableAllocation).count() == 0
    assert not pay(order_id, "rollback").get("idempotent", False)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "0", "0.001"])
def test_invalid_amount_fails_without_writes(payment_db, amount):
    scope, order_id = payment_db
    assert not pay(order_id, "invalid", amount)["success"]
    with tenant_scope(1), scope() as db:
        assert db.query(JournalEntry).count() == 0
