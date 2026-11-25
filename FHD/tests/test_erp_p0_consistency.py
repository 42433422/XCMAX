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
            Decimal("2"), Decimal("2"), Decimal("0")
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
            Decimal("8"), Decimal("0"), Decimal("8")
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
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = order
    db.query.return_value.join.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(quantity=Decimal("0.1000")),
        SimpleNamespace(quantity=Decimal("0.2000")),
    ]
    PurchaseService()._update_order_received_quantity(db, 7)
    assert row.received_quantity == Decimal("0.3000")
    assert row.status == order.status == "completed"


@pytest.mark.parametrize("paid,received,invoiced", [
    ("1.00", "0", "0"), ("0", "1.0000", "0"), ("0", "0", "1.0000")
])
def test_purchase_cancel_rejects_prior_liability(monkeypatch, paid, received, invoiced):
    from app.domain.shared_services import purchase_service

    order = SimpleNamespace(
        id=7, tenant_id=3, status="approved", paid_amount=Decimal(paid),
        items=[SimpleNamespace(
            received_quantity=Decimal(received), invoiced_quantity=Decimal(invoiced)
        )],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = order

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(purchase_service, "_write_lock", lambda db: None)
    monkeypatch.setattr(purchase_service, "get_db", session)
    result = PurchaseService().cancel_purchase_order(7)
    assert result["success"] is False
    assert order.status == "approved"
    db.commit.assert_not_called()
