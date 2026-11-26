"""Original-receipt supplier return: SQL ledger, batch and AP invariant tests."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.db_base import Base
from app.db.models import (
    InventoryLedger,
    InventoryTransaction,
    Product,
    PurchaseInbound,
    PurchaseInboundItem,
    PurchaseReturn,
    PurchaseReturnItem,
    Supplier,
    Warehouse,
)
from app.db.models.accounting import JournalEntry, JournalEntryLine
from app.db.models.approval import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalRecord,
    ApprovalRequest,
    ApprovalStatus,
)
from app.db.models.user import User
from app.domain.shared_services import purchase_return_posting
from app.domain.shared_services.purchase_service import PurchaseService
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture(params=["sqlite", "postgres"])
def original_purchase(tmp_path, monkeypatch, request):
    server = None
    schema = None
    if request.param == "postgres":
        raw = os.getenv("XCAGI_TEST_POSTGRES_URL", "").strip()
        if not raw:
            pytest.skip("BLOCKED: PostgreSQL acceptance requires XCAGI_TEST_POSTGRES_URL")
        url = make_url(raw)
        if url.get_backend_name() != "postgresql" or not (
            url.database or ""
        ).endswith("_test"):
            pytest.fail("PostgreSQL integration must target a database ending in _test")
        schema = "purchase_return_" + uuid.uuid4().hex[:16]
        server = create_engine(raw, pool_pre_ping=True)
        with server.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(
            raw,
            pool_pre_ping=True,
            connect_args={"options": f"-c search_path={schema}"},
        )
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'purchase-return.sqlite'}")
    Base.metadata.create_all(engine)

    with tenant_scope(3), Session(engine) as db:
        db.add_all(
            [
                User(id=101, username="purchase-applicant", password="test", tenant_id=3),
                User(id=102, username="purchase-approver", password="test", tenant_id=3),
            ]
        )
        flow = ApprovalFlow(flow_key="purchase-return-test", flow_name="退货审批")
        supplier = Supplier(tenant_id=3, code="RET-S", name="原供应商")
        warehouse = Warehouse(tenant_id=3, code="RET-W", name="原仓库", status="active")
        product = Product(tenant_id=3, name="原商品", unit="个")
        db.add_all([flow, supplier, warehouse, product])
        db.flush()
        node = ApprovalFlowNode(
            flow_id=flow.id, node_name="退货经理", node_order=1, approver_type="user",
            approver_ids="[102]",
        )
        receipt = PurchaseInbound(
            tenant_id=3, inbound_no="IN-TEST-RETURN", supplier_id=supplier.id,
            warehouse_id=warehouse.id, inbound_date=date(2026, 11, 25),
            total_amount=Decimal("60.00"), status="completed",
        )
        db.add_all([node, receipt])
        db.flush()
        lines = [
            PurchaseInboundItem(
                tenant_id=3, inbound_id=receipt.id, product_id=product.id,
                batch_no="batch-A", quantity=Decimal("5.0000"),
                unit_price=Decimal("5.0000"), amount=Decimal("25.00"),
            ),
            PurchaseInboundItem(
                tenant_id=3, inbound_id=receipt.id, product_id=product.id,
                batch_no="batch-B", quantity=Decimal("5.0000"),
                unit_price=Decimal("7.0000"), amount=Decimal("35.00"),
            ),
        ]
        db.add_all(lines)
        db.flush()
        for line in lines:
            ledger = InventoryLedger(
                tenant_id=3, product_id=product.id, warehouse_id=warehouse.id,
                batch_no=line.batch_no, quantity=Decimal("5.0000"),
                available_quantity=Decimal("5.0000"), reserved_quantity=0,
            )
            db.add(ledger)
            db.flush()
            db.add(
                InventoryTransaction(
                    tenant_id=3, ledger_id=ledger.id, product_id=product.id,
                    warehouse_id=warehouse.id, batch_no=line.batch_no,
                    transaction_type="in", quantity=Decimal("5.0000"),
                    reference_type="purchase_inbound", reference_id=receipt.id,
                    transaction_date=datetime(2026, 11, 25),
                )
            )
        journal = JournalEntry(
            tenant_id=3, entry_no="AP-ORIGINAL-TEST", status="posted",
            reference_type="purchase_inbound", reference_id=receipt.id,
            debit_total=Decimal("60.00"), credit_total=Decimal("60.00"),
        )
        db.add(journal)
        db.flush()
        db.add_all(
            [
                JournalEntryLine(
                    tenant_id=3, entry_id=journal.id, account_code="1401",
                    debit=Decimal("60.00"), credit=Decimal("0"),
                ),
                JournalEntryLine(
                    tenant_id=3, entry_id=journal.id, account_code="2201",
                    debit=Decimal("0"), credit=Decimal("60.00"),
                ),
            ]
        )
        payload = {
            "return_no": "RET-TEST-1",
            "inbound_id": receipt.id,
            "items": [
                {"inbound_item_id": lines[0].id, "quantity": "2.0000"},
                {"inbound_item_id": lines[1].id, "quantity": "1.0000"},
            ],
        }
        approval = ApprovalRequest(
            tenant_id=3, request_no="RET-APPROVAL-1", flow_id=flow.id,
            business_type="purchase_return", business_id=receipt.id,
            business_data=json.dumps(payload), applicant_id=101, approved_by=102,
            title="退货原件审批", status=ApprovalStatus.APPROVED.value,
            current_node_id=node.id,
        )
        db.add(approval)
        db.flush()
        db.add(
            ApprovalRecord(
                tenant_id=3, request_id=approval.id, node_id=node.id,
                approver_id=102, action=ApprovalAction.APPROVE.value,
                is_passed=True,
            )
        )
        request_data = {**payload, "approval_request_id": approval.id}
        receipt_id = receipt.id
        db.commit()

    @contextmanager
    def session():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(purchase_return_posting, "get_db", session)
    try:
        yield engine, request_data, receipt_id
    finally:
        engine.dispose()
        if server is not None and schema is not None:
            with server.begin() as conn:
                conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            server.dispose()


def test_approved_return_reverses_exact_two_batches_and_one_payable(original_purchase):
    engine, data, receipt_id = original_purchase
    with tenant_scope(3):
        result = PurchaseService().post_purchase_return(data)
        assert result["success"] is True, result
        assert result["idempotent"] is False
        assert result["amount"] == "17.00"
        assert result["bank_settlement_verified"] is False
        again = PurchaseService().post_purchase_return(data)
        assert again["success"] is True and again["idempotent"] is True
        assert again["return_id"] == result["return_id"]

        with Session(engine) as db:
            rows = db.scalars(select(PurchaseReturn)).all()
            assert len(rows) == 1
            details = db.scalars(select(PurchaseReturnItem)).all()
            assert sorted((i.batch_no, i.quantity) for i in details) == [
                ("batch-A", Decimal("2.0000")),
                ("batch-B", Decimal("1.0000")),
            ]
            stock = db.scalars(select(InventoryLedger)).all()
            assert {s.batch_no: s.quantity for s in stock} == {
                "batch-A": Decimal("3.0000"),
                "batch-B": Decimal("4.0000"),
            }
            negative = db.scalars(
                select(InventoryTransaction).where(
                    InventoryTransaction.reference_type == "purchase_return"
                )
            ).all()
            assert len(negative) == 2
            assert sum((r.quantity for r in negative), Decimal("0")) == Decimal("-3")
            reversals = db.scalars(
                select(JournalEntry).where(
                    JournalEntry.reference_type == "purchase_return"
                )
            ).all()
            assert len(reversals) == 1
            reversal = reversals[0]
            assert reversal.id == result["journal_entry_id"]
            assert reversal.debit_total == reversal.credit_total == Decimal("17.00")
            assert [(l.account_code, l.debit, l.credit) for l in reversal.lines] == [
                ("2201", Decimal("17.00"), Decimal("0")),
                ("1401", Decimal("0"), Decimal("17.00")),
            ]


def test_return_requires_exact_frozen_approval_and_tenant(original_purchase):
    engine, data, receipt_id = original_purchase
    changed = json.loads(json.dumps(data))
    changed["items"][0]["quantity"] = "3.0000"
    with tenant_scope(3):
        result = PurchaseService().post_purchase_return(changed)
        assert result["success"] is False
    with tenant_scope(4):
        result = PurchaseService().post_purchase_return(data)
        assert result["success"] is False
    with tenant_scope(3), Session(engine) as db:
        assert db.scalars(select(PurchaseReturn)).all() == []
        assert all(
            stock.quantity == Decimal("5") for stock in db.scalars(select(InventoryLedger))
        )


def test_second_batch_failure_rolls_back_first_batch_and_financial_reversal(original_purchase):
    engine, data, receipt_id = original_purchase
    with tenant_scope(3), Session(engine) as db:
        batch = db.scalar(
            select(InventoryLedger).where(InventoryLedger.batch_no == "batch-B")
        )
        batch.available_quantity = Decimal("0")
        batch.reserved_quantity = Decimal("5")
        db.commit()

    with tenant_scope(3):
        result = PurchaseService().post_purchase_return(data)
        assert result["success"] is False
    with tenant_scope(3), Session(engine) as db:
        row_a = db.scalar(select(InventoryLedger).where(InventoryLedger.batch_no == "batch-A"))
        assert row_a.quantity == row_a.available_quantity == Decimal("5")
        assert db.scalars(select(PurchaseReturn)).all() == []
        assert db.scalars(
            select(JournalEntry).where(JournalEntry.reference_type == "purchase_return")
        ).all() == []
        assert db.scalars(
            select(InventoryTransaction).where(
                InventoryTransaction.reference_type == "purchase_return"
            )
        ).all() == []


def test_incomplete_original_batch_evidence_blocks_return(original_purchase):
    engine, data, receipt_id = original_purchase
    with tenant_scope(3), Session(engine) as db:
        original = db.scalar(
            select(InventoryTransaction).where(
                InventoryTransaction.reference_type == "purchase_inbound",
                InventoryTransaction.batch_no == "batch-B",
            )
        )
        db.delete(original)
        db.commit()
    with tenant_scope(3):
        result = PurchaseService().post_purchase_return(data)
        assert result["success"] is False
    with tenant_scope(3), Session(engine) as db:
        assert db.scalars(select(PurchaseReturn)).all() == []


def test_postgres_concurrent_same_approval_posted_once(original_purchase):
    from concurrent.futures import ThreadPoolExecutor

    engine, data, _ = original_purchase
    if engine.dialect.name != "postgresql":
        pytest.skip("Parallel approval claim acceptance requires real PostgreSQL")

    def submit(_):
        with tenant_scope(3):
            return PurchaseService().post_purchase_return(data)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))
    assert all(r["success"] is True for r in results), results
    assert sum(r.get("idempotent") is False for r in results) == 1
    assert len({r["return_id"] for r in results}) == 1
    with tenant_scope(3), Session(engine) as db:
        assert len(db.scalars(select(PurchaseReturn)).all()) == 1
        assert len(db.scalars(
            select(JournalEntry).where(JournalEntry.reference_type == "purchase_return")
        ).all()) == 1


def test_approver_revocation_prevents_posting_and_does_not_change_stock(original_purchase):
    engine, data, _ = original_purchase
    with tenant_scope(3), Session(engine) as db:
        user = db.get(User, 102)
        user.is_active = False
        db.commit()
    with tenant_scope(3):
        outcome = PurchaseService().post_purchase_return(data)
    assert outcome["success"] is False
    with tenant_scope(3), Session(engine) as db:
        assert db.scalars(select(PurchaseReturn)).all() == []
        assert all(
            row.quantity == Decimal("5")
            for row in db.scalars(select(InventoryLedger)).all()
        )
