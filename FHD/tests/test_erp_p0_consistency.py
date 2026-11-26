"""P0 ledger and purchase invariants. Real SQLite CAS; no synthetic success receipts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, DateTime, Integer, Numeric, create_engine
from sqlalchemy.orm import Session, declarative_base

from app.domain.shared_services import inventory_movements
from app.domain.shared_services.purchase_service import PurchaseService, _line_amount


def test_inventory_debit_rejects_stale_second_writer(tmp_path, monkeypatch):
    base = declarative_base()

    class Ledger(base):
        __tablename__ = "stock_cas_test"
        id = Column(Integer, primary_key=True)
        tenant_id = Column(Integer, nullable=False)
        quantity = Column(Numeric(18, 4), nullable=False)
        available_quantity = Column(Numeric(18, 4), nullable=False)
        reserved_quantity = Column(Numeric(18, 4), nullable=False)
        updated_at = Column(DateTime)

    engine = create_engine(f"sqlite:///{tmp_path / 'cas.sqlite'}")
    base.metadata.create_all(engine)
    monkeypatch.setattr(
        inventory_movements, "_facade", lambda: SimpleNamespace(InventoryLedger=Ledger)
    )
    with Session(engine) as seed:
        seed.add(Ledger(id=1, tenant_id=3, quantity=10, available_quantity=10, reserved_quantity=0))
        seed.commit()
    with Session(engine) as stale, Session(engine) as writer:
        stale_row = stale.get(Ledger, 1)
        writer_row = writer.get(Ledger, 1)
        now = datetime(2026, 11, 25)
        assert inventory_movements._move_available(writer, writer_row, Decimal("-8"), now)
        writer.commit()
        assert not inventory_movements._move_available(stale, stale_row, Decimal("-5"), now)
        stale.rollback()
    with Session(engine) as verify:
        row = verify.get(Ledger, 1)
        assert (row.quantity, row.available_quantity, row.reserved_quantity) == (
            Decimal("2"),
            Decimal("2"),
            Decimal("0"),
        )
    engine.dispose()


def test_inventory_guard_refuses_to_spend_reserved_or_broken_stock(tmp_path, monkeypatch):
    base = declarative_base()

    class Ledger(base):
        __tablename__ = "stock_reserved_test"
        id = Column(Integer, primary_key=True)
        tenant_id = Column(Integer, nullable=False)
        quantity = Column(Numeric(18, 4), nullable=False)
        available_quantity = Column(Numeric(18, 4), nullable=False)
        reserved_quantity = Column(Numeric(18, 4), nullable=False)
        updated_at = Column(DateTime)

    engine = create_engine(f"sqlite:///{tmp_path / 'reserved.sqlite'}")
    base.metadata.create_all(engine)
    monkeypatch.setattr(
        inventory_movements, "_facade", lambda: SimpleNamespace(InventoryLedger=Ledger)
    )
    with Session(engine) as db:
        row = Ledger(id=1, tenant_id=3, quantity=10, available_quantity=2, reserved_quantity=8)
        db.add(row)
        db.commit()
        assert not inventory_movements._move_available(db, row, Decimal("-3"), datetime.now())
        assert inventory_movements._move_available(db, row, Decimal("-2"), datetime.now())
        db.commit()
        assert (row.quantity, row.available_quantity, row.reserved_quantity) == (
            Decimal("8"),
            Decimal("0"),
            Decimal("8"),
        )
        row.available_quantity = Decimal("9")
        db.commit()
        assert not inventory_movements._move_available(db, row, Decimal("-1"), datetime.now())
    engine.dispose()


def test_purchase_line_amount_rounding_matches_journal():
    assert _line_amount(Decimal("0.1000"), Decimal("0.1500")) == Decimal("0.02")
    assert _line_amount(Decimal("0.1000"), Decimal("0.0500")) == Decimal("0.01")


def test_purchase_progress_uses_completed_receipts_and_exact_decimal():
    row = SimpleNamespace(
        id=11, quantity=Decimal("0.3000"), received_quantity=Decimal("0"), status="approved"
    )
    order = SimpleNamespace(id=7, tenant_id=3, status="approved", items=[row])
    from app.db.models import PurchaseInboundItem, PurchaseOrder, PurchaseReturnItem

    db = MagicMock()
    order_q = MagicMock()
    order_q.filter.return_value.first.return_value = order
    inbound_q = MagicMock()
    inbound_q.join.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(quantity=Decimal("0.1000")),
        SimpleNamespace(quantity=Decimal("0.2000")),
    ]
    returns_q = MagicMock()
    returns_q.join.return_value.join.return_value.filter.return_value.all.return_value = []
    db.query.side_effect = lambda model: {
        PurchaseOrder: order_q,
        PurchaseInboundItem: inbound_q,
        PurchaseReturnItem: returns_q,
    }[model]
    PurchaseService()._update_order_received_quantity(db, 7)
    assert row.received_quantity == Decimal("0.3000")
    assert row.status == order.status == "completed"


@pytest.mark.parametrize(
    "paid,received,invoiced", [("1.00", "0", "0"), ("0", "1.0000", "0"), ("0", "0", "1.0000")]
)
def test_purchase_cancel_rejects_prior_liability(monkeypatch, paid, received, invoiced):
    from app.domain.shared_services import purchase_service

    order = SimpleNamespace(
        id=7,
        tenant_id=3,
        status="approved",
        paid_amount=Decimal(paid),
        items=[
            SimpleNamespace(
                received_quantity=Decimal(received), invoiced_quantity=Decimal(invoiced)
            )
        ],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
        order
    )

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(purchase_service, "_write_lock", lambda db: None)
    monkeypatch.setattr(purchase_service, "get_db", session)
    result = PurchaseService().cancel_purchase_order(7)
    assert result["success"] is False
    assert order.status == "approved"
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "debit,credit",
    [
        ("1.00", "0.99"),
        ("1.001", "1.001"),
        ("NaN", "0"),
        ("-1.00", "1.00"),
        ("1.00", "1.00"),
    ],
)
def test_journal_cannot_post_invalid_or_imbalanced_amounts(debit, credit):
    from app.domain.shared_services.accounting_services import _create_journal_entry

    ledger = {
        "lines": [
            {"debit": debit, "credit": "0"},
            {"debit": "0", "credit": credit},
        ]
    }
    result = _create_journal_entry(ledger, MagicMock())
    assert result["success"] is False


def test_journal_reverse_once_creates_exact_opposite_entry(tmp_path, monkeypatch):
    from app.db.models.accounting import ChartOfAccount, JournalEntry, JournalEntryLine
    from app.domain.shared_services import accounting_services

    engine = create_engine(f"sqlite:///{tmp_path / 'journal.sqlite'}")
    for model in (ChartOfAccount, JournalEntry, JournalEntryLine):
        model.__table__.create(engine)

    with Session(engine) as db:
        created = accounting_services.create_journal_entry(
            {
                "entry_no": "TEST-POST-001",
                "lines": [
                    {"account_code": "1001", "debit": Decimal("5.25"), "credit": 0},
                    {"account_code": "2201", "debit": 0, "credit": Decimal("5.25")},
                ],
            },
            db=db,
        )
        assert created["success"] is True
        db.commit()
        original_id = created["data"]["id"]

    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
            db.commit()

    monkeypatch.setattr(accounting_services, "get_db", session)
    first = accounting_services.journal_entry_reverse(original_id)
    second = accounting_services.journal_entry_reverse(original_id)
    assert first["success"] is True
    assert second["success"] is False
    with Session(engine) as db:
        source = db.get(JournalEntry, original_id)
        reversal = db.query(JournalEntry).filter(JournalEntry.reversed_of_id == original_id).one()
        assert source.reversed_at is not None
        assert reversal.debit_total == reversal.credit_total == Decimal("5.25")
        assert [(line.debit, line.credit) for line in reversal.lines] == [
            (Decimal("0"), Decimal("5.25")),
            (Decimal("5.25"), Decimal("0")),
        ]
    engine.dispose()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "1.234", True])
def test_manual_finance_requires_positive_exact_cents(value):
    from app.application.finance_app_service import _valid_finance_amount

    with pytest.raises(ValueError):
        _valid_finance_amount(value)


def test_financial_reference_replay_does_not_accept_new_amount():
    from app.application.finance_app_service import _same_financial_posting

    posted = SimpleNamespace(
        amount=Decimal("100.00"),
        currency="CNY",
        counterparty_id=3,
        counterparty_name="A",
    )
    assert _same_financial_posting(
        posted, {"amount": "100.00", "currency": "CNY", "counterparty_id": 3}, Decimal("100.00")
    )
    assert not _same_financial_posting(
        posted, {"amount": "100.01", "currency": "CNY", "counterparty_id": 3}, Decimal("100.01")
    )
    assert not _same_financial_posting(
        posted, {"amount": "100.00", "currency": "USD", "counterparty_id": 3}, Decimal("100.00")
    )


def test_order_reservation_cas_fences_a_stale_writer(tmp_path, monkeypatch):
    from app.domain.shared_services import inventory_orders

    base = declarative_base()

    class Ledger(base):
        __tablename__ = "order_reserved_cas_test"
        id = Column(Integer, primary_key=True)
        tenant_id = Column(Integer, nullable=False)
        quantity = Column(Numeric(18, 4), nullable=False)
        available_quantity = Column(Numeric(18, 4), nullable=False)
        reserved_quantity = Column(Numeric(18, 4), nullable=False)
        updated_at = Column(DateTime)

    monkeypatch.setattr(inventory_orders, "InventoryLedger", Ledger)
    engine = create_engine(f"sqlite:///{tmp_path / 'order-cas.sqlite'}")
    base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Ledger(id=1, tenant_id=3, quantity=10, available_quantity=10, reserved_quantity=0))
        db.commit()
    with Session(engine) as stale, Session(engine) as writer:
        old_row = stale.get(Ledger, 1)
        current = writer.get(Ledger, 1)
        assert inventory_orders._order_ledger_cas(
            writer,
            current,
            physical_delta=Decimal("0"),
            available_delta=Decimal("-4"),
            reserved_delta=Decimal("4"),
            now=datetime(2026, 11, 25),
        )
        writer.commit()
        assert not inventory_orders._order_ledger_cas(
            stale,
            old_row,
            physical_delta=Decimal("-8"),
            available_delta=Decimal("-8"),
            reserved_delta=Decimal("0"),
            now=datetime(2026, 11, 25),
        )
        stale.rollback()
    with Session(engine) as db:
        row = db.get(Ledger, 1)
        assert (row.quantity, row.available_quantity, row.reserved_quantity) == (
            Decimal("10"),
            Decimal("6"),
            Decimal("4"),
        )
    engine.dispose()


def test_approval_node_claim_rejects_stale_status_and_reassigned_node(tmp_path, monkeypatch):
    from app.application.approval_workspace import decisions

    base = declarative_base()

    class Request(base):
        __tablename__ = "approval_cas_test"
        id = Column(Integer, primary_key=True)
        tenant_id = Column(Integer, nullable=False)
        status = Column(Integer, nullable=False)
        current_node_id = Column(Integer, nullable=False)
        current_node_order = Column(Integer, nullable=False)

    engine = create_engine(f"sqlite:///{tmp_path / 'approval-cas.sqlite'}")
    base.metadata.create_all(engine)
    monkeypatch.setattr(decisions, "ApprovalRequest", Request)
    with Session(engine) as db:
        db.add(Request(id=1, tenant_id=3, status=1, current_node_id=5, current_node_order=1))
        db.commit()
    with Session(engine) as stale, Session(engine) as writer:
        old_req = stale.get(Request, 1)
        changed = (
            writer.query(Request)
            .filter(Request.id == 1)
            .update({Request.current_node_id: 8, Request.current_node_order: 2})
        )
        assert changed == 1
        writer.commit()
        assert not decisions._claim_open_step(stale, old_req, 2)
        stale.rollback()
    with Session(engine) as db:
        current = db.get(Request, 1)
        assert (current.status, current.current_node_id) == (1, 8)
    engine.dispose()


def test_approval_reviewer_cannot_act_after_tenant_change():
    from app.application.approval_workspace.decisions import _active_decision_actor

    db = MagicMock()
    reviewer = db.query.return_value.filter.return_value.with_for_update.return_value
    reviewer.first.return_value = SimpleNamespace(tenant_id=4)
    assert not _active_decision_actor(db, SimpleNamespace(tenant_id=3), actor=5)
    reviewer.first.return_value = None
    assert not _active_decision_actor(db, SimpleNamespace(tenant_id=3), actor=5)
    db.query.return_value.filter.return_value.with_for_update.assert_called_with(read=True)


def test_reviewer_active_row_is_locked_for_entire_decision():
    from app.application.approval_workspace.decisions import _active_decision_actor

    db = MagicMock()
    reviewer = db.query.return_value.filter.return_value.with_for_update.return_value
    reviewer.first.return_value = SimpleNamespace(tenant_id=3)
    assert _active_decision_actor(db, SimpleNamespace(tenant_id=3), actor=5)
    db.query.return_value.filter.return_value.with_for_update.assert_called_once_with(read=True)


def test_purchase_cross_table_reconciliation_checks_batch_and_payable(tmp_path, monkeypatch):
    """Real isolated SQLite rows: receipt, batch stock movement and AP journal."""
    from datetime import date

    from app.db.db_base import Base
    from app.db.models.accounting import JournalEntry, JournalEntryLine
    from app.db.models.inventory import InventoryTransaction, Warehouse
    from app.db.models.product import Product
    from app.db.models.purchase import PurchaseInbound, PurchaseInboundItem, Supplier
    from app.domain.shared_services import purchase_service
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'purchase-reconcile.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        supplier = Supplier(tenant_id=3, code="TEST-S1", name="test supplier")
        warehouse = Warehouse(tenant_id=3, code="TEST-W1", name="test warehouse")
        product = Product(tenant_id=3, name="test product")
        db.add_all([supplier, warehouse, product])
        db.flush()
        receipt = PurchaseInbound(
            tenant_id=3,
            inbound_no="IN-TEST-1",
            supplier_id=supplier.id,
            warehouse_id=warehouse.id,
            inbound_date=date(2026, 11, 25),
            total_amount=Decimal("10.00"),
            status="completed",
        )
        db.add(receipt)
        db.flush()
        db.add(
            PurchaseInboundItem(
                tenant_id=3,
                inbound_id=receipt.id,
                product_id=product.id,
                batch_no="batch-A",
                quantity=Decimal("2.0000"),
                unit_price=Decimal("5.0000"),
                amount=Decimal("10.00"),
            )
        )
        db.add(
            InventoryTransaction(
                tenant_id=3,
                product_id=product.id,
                warehouse_id=warehouse.id,
                transaction_type="in",
                batch_no="batch-A",
                quantity=Decimal("2.0000"),
                reference_type="purchase_inbound",
                reference_id=receipt.id,
                transaction_date=datetime(2026, 11, 25),
            )
        )
        journal = JournalEntry(
            tenant_id=3,
            entry_no="TEST-AP-1",
            status="posted",
            reference_type="purchase_inbound",
            reference_id=receipt.id,
            debit_total=Decimal("10.00"),
            credit_total=Decimal("10.00"),
        )
        db.add(journal)
        db.flush()
        db.add_all(
            [
                JournalEntryLine(
                    tenant_id=3,
                    entry_id=journal.id,
                    account_code="1401",
                    debit=Decimal("10.00"),
                    credit=Decimal("0"),
                ),
                JournalEntryLine(
                    tenant_id=3,
                    entry_id=journal.id,
                    account_code="2201",
                    debit=Decimal("0"),
                    credit=Decimal("10.00"),
                ),
            ]
        )
        receipt_id = receipt.id
        db.commit()

    @contextmanager
    def session():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(purchase_service, "get_db", session)
    try:
        with tenant_scope(3):
            verified = PurchaseService().reconcile_purchase_inbound(receipt_id)
            assert verified["posting_consistent"] is True
            assert verified["bank_settlement_verified"] is False
            assert verified["inventory_posting_count"] == 1

        with tenant_scope(3), Session(engine) as db:
            posting = (
                db.query(InventoryTransaction)
                .filter(InventoryTransaction.reference_id == receipt_id)
                .one()
            )
            posting.batch_no = "batch-forged"
            db.commit()
        with tenant_scope(3):
            broken = PurchaseService().reconcile_purchase_inbound(receipt_id)
            assert broken["posting_consistent"] is False
            assert "purchase_batch_stock_mismatch" in broken["issues"]

        with tenant_scope(4):
            denied = PurchaseService().reconcile_purchase_inbound(receipt_id)
            assert denied["reason_code"] == "completed_purchase_receipt_required"
    finally:
        engine.dispose()
