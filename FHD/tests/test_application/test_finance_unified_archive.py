"""P0 company ledger projection must not certify duplicate or missing source rows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models.finance import FinancialTransaction
from app.domain.shared_services import finance_unified_archive as archive
from app.fastapi_routes.finance_unified_ledger import (
    FinanceLedgerRebuildBody,
    finance_unified_ledger_rebuild,
)
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def db_factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    FinancialTransaction.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


def invoice(**changes):
    return {
        "id": 9,
        "market_user_id": 17,
        "invoice_no": "INV-9",
        "amount_cents": 729,
        "status": "issued",
        "issued_at": "2026-11-01T09:00:00+08:00",
        **changes,
    }


def test_same_invoice_replay_does_not_double_book(db_factory):
    with tenant_scope(7):
        first = archive.archive_from_crm_invoice(invoice())
        second = archive.archive_from_crm_invoice(invoice())
        assert first["archived"] and not first["idempotent"]
        assert second == {
            "archived": True,
            "transaction_id": first["transaction_id"],
            "idempotent": True,
        }
        with db_factory() as db:
            rows = db.scalars(select(FinancialTransaction)).all()
        assert len(rows) == 1
        assert rows[0].amount == Decimal("7.29")
        assert rows[0].transaction_date == datetime(2026, 11, 1, 1, 0, 0)
        assert rows[0].status == "issued"
        assert archive.list_ledger(track="contract")[0]["amount_cents"] == 729


def test_same_reference_with_changed_amount_or_status_is_conflict(db_factory):
    with tenant_scope(7):
        first = archive.archive_from_crm_invoice(invoice())
        assert first["archived"]
        for changed in (invoice(amount_cents=730), invoice(status="paid")):
            outcome = archive.archive_from_crm_invoice(changed)
            assert outcome == {
                "archived": False,
                "reason_code": "invoice_archive_conflict",
            }
        with db_factory() as db:
            rows = db.scalars(select(FinancialTransaction)).all()
            assert len(rows) == 1 and rows[0].amount == Decimal("7.29")


def test_no_tenant_does_not_write_and_tenant_references_do_not_mix(db_factory):
    assert archive.archive_from_crm_invoice(invoice()) == {
        "archived": False, "reason_code": "tenant_context_required"
    }
    for tenant in (7, 8):
        with tenant_scope(tenant):
            outcome = archive.archive_from_crm_invoice(invoice())
            assert outcome["archived"]
            with db_factory() as db:
                rows = db.scalars(select(FinancialTransaction)).all()
                assert len(rows) == 1 and rows[0].tenant_id == tenant


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (invoice(id=0), "invoice_identity_required"),
        (invoice(amount_cents=-10), "invoice_amount_invalid"),
        (invoice(issued_at=""), "invoice_date_required"),
    ],
)
def test_invalid_original_rejected_without_booked_row(db_factory, payload, reason):
    with tenant_scope(7):
        assert archive.archive_from_crm_invoice(payload)["reason_code"] == reason
        with db_factory() as db:
            assert db.scalars(select(FinancialTransaction)).all() == []


def test_rebuild_exposes_partial_and_failed_receipts(monkeypatch):
    import app.domain.shared_services.user_cs_crm_store as store

    rows = [invoice(), invoice(id=10)]
    monkeypatch.setattr(store, "list_crm_invoices", lambda **_kw: {
        "items": rows, "total": 3,
    })
    monkeypatch.setattr(archive, "archive_from_crm_invoice", lambda item, **_kw: {
        "archived": item["id"] == 9,
    })
    result = archive.rebuild_ledger_archive()
    assert result["rebuilt"] == 1
    assert result["rejected"] == 1
    assert result["complete"] is False
    assert result["reason_code"] == "invoice_source_truncated"


def test_api_does_not_return_success_on_incomplete_rebuild(monkeypatch):
    import app.application.finance_unified_ledger_app_service as app_service

    monkeypatch.setattr(app_service, "rebuild_ledger_archive", lambda **_kw: {
        "complete": False, "rebuilt": 1, "rejected": 1,
    })
    result = finance_unified_ledger_rebuild(FinanceLedgerRebuildBody())
    assert isinstance(result, JSONResponse)
    assert result.status_code == 409
