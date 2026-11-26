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
    # The original CRM voucher is read independently of any supplied dict.
    monkeypatch.setattr(
        "app.domain.shared_services.user_cs_crm_store.get_crm_invoice_by_id",
        lambda invoice_id: invoice() if invoice_id == 9 else None,
    )
    monkeypatch.setattr(
        archive,
        "_crm_market_user_owned",
        lambda tenant_id, market_user_id: tenant_id == 7 and market_user_id == 17,
    )
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
        for changed in (invoice(amount_cents=730), invoice(status="paid"), invoice(label="forged")):
            outcome = archive.archive_from_crm_invoice(changed)
            assert outcome == {
                "archived": False,
                "reason_code": "invoice_source_conflict",
            }
        with db_factory() as db:
            rows = db.scalars(select(FinancialTransaction)).all()
            assert len(rows) == 1 and rows[0].amount == Decimal("7.29")


def test_no_tenant_and_foreign_tenant_invoice_are_refused(db_factory):
    with tenant_scope(None):
        assert archive.archive_from_crm_invoice(invoice()) == {
            "archived": False,
            "reason_code": "tenant_context_required",
        }
    with tenant_scope(7):
        assert archive.archive_from_crm_invoice(invoice())["archived"] is True
    with tenant_scope(8):
        assert archive.archive_from_crm_invoice(invoice()) == {
            "archived": False,
            "reason_code": "invoice_tenant_ownership_conflict",
        }
    with tenant_scope(7), db_factory() as db:
        rows = db.scalars(select(FinancialTransaction)).all()
        assert len(rows) == 1 and rows[0].tenant_id == 7


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (invoice(id=0), "invoice_identity_required"),
        (invoice(amount_cents=-10), "invoice_amount_invalid"),
        (invoice(issued_at=""), "invoice_date_required"),
        (invoice(issued_at="2026-11-01T09:00:00"), "invoice_timezone_required"),
        (invoice(amount_cents=None, amount=250), "invoice_amount_invalid"),
        (invoice(amount_cents=True), "invoice_amount_invalid"),
        (invoice(market_user_id="17"), "invoice_counterparty_invalid"),
    ],
)
def test_invalid_original_rejected_without_booked_row(db_factory, payload, reason):
    with tenant_scope(7):
        assert archive.archive_from_crm_invoice(payload)["reason_code"] == reason
        with db_factory() as db:
            assert db.scalars(select(FinancialTransaction)).all() == []


def test_rebuild_rejects_truncated_source_before_any_write(monkeypatch):
    import app.domain.shared_services.user_cs_crm_store as store

    monkeypatch.setattr(
        store,
        "list_crm_invoices",
        lambda **_kw: {
            "items": [invoice(), invoice(id=10)],
            "total": 3,
        },
    )
    called = []
    monkeypatch.setattr(
        archive, "archive_from_crm_invoice", lambda item, **_kw: called.append(item)
    )
    result = archive.rebuild_ledger_archive()
    assert result["rebuilt"] == result["rejected"] == 0
    assert result["complete"] is False
    assert result["reason_code"] == "invoice_source_truncated"
    assert called == []


def test_rebuild_fetches_every_page_before_archiving(monkeypatch):
    import app.domain.shared_services.user_cs_crm_store as store

    originals = [invoice(id=i) for i in range(1, 502)]
    requested = []

    def list_page(**kw):
        requested.append(kw["offset"])
        start = kw["offset"]
        return {
            "items": originals[start : start + kw["limit"]],
            "total": len(originals),
            "offset": start,
        }

    monkeypatch.setattr(store, "list_crm_invoices", list_page)
    archived = []

    def archive_invoice(item, **_kw):
        archived.append(item["id"])
        return {"archived": True, "idempotent": False}

    monkeypatch.setattr(archive, "archive_from_crm_invoice", archive_invoice)
    outcome = archive.rebuild_ledger_archive()
    assert outcome["complete"] is True
    assert outcome["rebuilt"] == 501
    assert outcome["pages_read"] == 2
    assert requested == [0, 500, 0, 500]
    assert archived == list(range(1, 502))


@pytest.mark.parametrize(
    ("broken", "reason"),
    [
        ("empty", "invoice_source_truncated"),
        ("duplicate", "invoice_source_duplicate"),
        ("different_total", "invoice_source_changed_during_pagination"),
        ("wrong_offset", "invoice_source_wrong_page"),
    ],
)
def test_rebuild_rejects_broken_second_page_without_writes(monkeypatch, broken, reason):
    import app.domain.shared_services.user_cs_crm_store as store

    first_page = [invoice(id=i) for i in range(1, 501)]

    def list_page(**kw):
        if kw["offset"] == 0:
            return {"items": first_page, "total": 501, "offset": 0}
        result = {"items": [invoice(id=501)], "total": 501, "offset": 500}
        if broken == "empty":
            result["items"] = []
        elif broken == "duplicate":
            result["items"] = [invoice(id=1)]
        elif broken == "different_total":
            result["total"] = 502
        elif broken == "wrong_offset":
            result["offset"] = 1
        return result

    monkeypatch.setattr(store, "list_crm_invoices", list_page)
    called = []
    monkeypatch.setattr(
        archive, "archive_from_crm_invoice", lambda item, **_kw: called.append(item)
    )
    result = archive.rebuild_ledger_archive()
    assert result["complete"] is False
    assert result["reason_code"] == reason
    assert result["rebuilt"] == 0
    assert called == []


def test_rebuild_exposes_per_invoice_archival_failures(monkeypatch):
    import app.domain.shared_services.user_cs_crm_store as store

    monkeypatch.setattr(
        store,
        "list_crm_invoices",
        lambda **_kw: {"items": [invoice(), invoice(id=10)], "total": 2},
    )
    monkeypatch.setattr(
        archive,
        "archive_from_crm_invoice",
        lambda item, **_kw: {"archived": item["id"] == 9},
    )
    result = archive.rebuild_ledger_archive()
    assert result["rebuilt"] == 1
    assert result["rejected"] == 1
    assert result["complete"] is False
    assert result["reason_code"] == "invoice_archive_rejected"


def test_insert_must_be_independently_read_back(db_factory, monkeypatch):
    # Simulate an independent read returning no matching source identity.
    with tenant_scope(7):
        monkeypatch.setattr(archive, "_invoice_archive_existing", lambda *_a, **_kw: None)
        result = archive.archive_from_crm_invoice(invoice())
    assert result == {
        "archived": False,
        "reason_code": "invoice_archive_readback_failed",
    }


def test_original_source_missing_or_changed_does_not_archive(db_factory, monkeypatch):
    import app.domain.shared_services.user_cs_crm_store as store

    monkeypatch.setattr(store, "get_crm_invoice_by_id", lambda invoice_id: None)
    with tenant_scope(7):
        result = archive.archive_from_crm_invoice(invoice())
        assert result["reason_code"] == "invoice_source_missing"
        with db_factory() as db:
            assert db.scalars(select(FinancialTransaction)).all() == []

    monkeypatch.setattr(
        store,
        "get_crm_invoice_by_id",
        lambda _invoice_id: invoice(amount_cents=730),
    )
    with tenant_scope(7):
        result = archive.archive_from_crm_invoice(invoice())
        assert result["reason_code"] == "invoice_source_conflict"
        with db_factory() as db:
            assert db.scalars(select(FinancialTransaction)).all() == []


def test_invoice_rebuild_refuses_source_mutation_between_scans(monkeypatch):
    import app.domain.shared_services.user_cs_crm_store as store

    called = 0

    def pages(**_kw):
        nonlocal called
        called += 1
        value = invoice(amount_cents=729 if called == 1 else 730)
        return {"items": [value], "total": 1, "offset": 0}

    monkeypatch.setattr(store, "list_crm_invoices", pages)
    writes = []
    monkeypatch.setattr(archive, "archive_from_crm_invoice", lambda row, **_kw: writes.append(row))
    result = archive.rebuild_ledger_archive()
    assert result["complete"] is False
    assert result["reason_code"] == "invoice_source_changed_during_pagination"
    assert writes == []


def test_replay_cannot_override_original_invoice_counterparty(db_factory):
    with tenant_scope(7):
        result = archive.archive_from_crm_invoice(invoice(market_user_id=17), market_user_id=18)
        assert result == {
            "archived": False,
            "reason_code": "invoice_counterparty_conflict",
        }
        with db_factory() as db:
            assert db.scalars(select(FinancialTransaction)).all() == []


def test_real_host_user_mapping_controls_source_owner(tmp_path, monkeypatch):
    from app.db.models.user import User

    engine = create_engine(f"sqlite:///{tmp_path / 'crm-owner.sqlite'}")
    User.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    try:
        with factory() as db:
            db.add(
                User(
                    username="crm-customer-owner",
                    password="test",
                    tenant_id=7,
                    market_user_id=17,
                    is_active=True,
                )
            )
            db.commit()
        assert archive._crm_market_user_owned(7, 17) is True
        assert archive._crm_market_user_owned(8, 17) is False
        assert archive._crm_market_user_owned(7, 18) is False
        with factory() as db:
            owner = db.query(User).filter(User.market_user_id == 17).one()
            owner.is_active = False
            db.commit()
        assert archive._crm_market_user_owned(7, 17) is False
    finally:
        engine.dispose()


def test_invoice_projection_is_document_only(db_factory):
    with tenant_scope(7):
        assert archive.archive_from_crm_invoice(invoice())["archived"] is True
        entry = archive.list_ledger(track="contract")[0]
    assert entry["document_only"] is True
    assert entry["settlement_verified"] is False
    assert entry["amount_cents"] == 729


def test_api_does_not_return_success_on_incomplete_rebuild(monkeypatch):
    import app.application.finance_unified_ledger_app_service as app_service

    monkeypatch.setattr(
        app_service,
        "rebuild_ledger_archive",
        lambda **_kw: {
            "complete": False,
            "rebuilt": 1,
            "rejected": 1,
        },
    )
    result = finance_unified_ledger_rebuild(FinanceLedgerRebuildBody())
    assert isinstance(result, JSONResponse)
    assert result.status_code == 409


def test_ledger_track_is_read_from_original_transaction_not_requested_category(db_factory):
    with tenant_scope(7):
        assert archive.archive_from_crm_invoice(invoice())["archived"]
        contract = archive._items_from_db(None, track="contract", limit=10)
        token = archive._items_from_db(None, track="token", limit=10)
    assert len(contract) == 1 and contract[0]["track"] == "contract"
    assert token == []
