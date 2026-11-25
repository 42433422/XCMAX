"""Real PostgreSQL concurrent archive replay, opt-in isolated test DB only.

Set XCAGI_TEST_POSTGRES_URL to a non-production database whose name ends in
"_test". The test creates and deletes only its own random temporary schema.
A skipped test is not PostgreSQL acceptance evidence.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.models.finance import FinancialTransaction
from app.domain.shared_services import finance_unified_archive as archive
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def pg_archive_db(monkeypatch):
    raw = os.getenv("XCAGI_TEST_POSTGRES_URL", "").strip()
    if not raw:
        pytest.skip("BLOCKED: no dedicated XCAGI_TEST_POSTGRES_URL")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_test"):
        pytest.fail("PostgreSQL integration must use a database ending in _test")
    schema = "finance_archive_" + uuid.uuid4().hex[:16]
    server = create_engine(raw, pool_pre_ping=True)
    with server.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    pg = create_engine(
        raw, pool_pre_ping=True, pool_size=12, max_overflow=2,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        FinancialTransaction.__table__.create(pg)
        factory = sessionmaker(bind=pg, expire_on_commit=False)
        monkeypatch.setattr("app.db.SessionLocal", factory)
        monkeypatch.setattr(
            archive, "_crm_market_user_owned",
            lambda tenant_id, market_user_id: tenant_id == 7 and market_user_id == 17,
        )
        monkeypatch.setattr(
            "app.domain.shared_services.user_cs_crm_store.get_crm_invoice_by_id",
            lambda _invoice_id: {
                "id": 9, "market_user_id": 17, "invoice_no": "INV-PG-9",
                "amount_cents": 729, "status": "issued",
                "issued_at": "2026-11-01T09:00:00+08:00",
            },
        )
        yield factory
    finally:
        pg.dispose()
        with server.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        server.dispose()


def _source_invoice():
    return {
        "id": 9, "market_user_id": 17, "invoice_no": "INV-PG-9",
        "amount_cents": 729, "status": "issued",
        "issued_at": "2026-11-01T09:00:00+08:00",
    }


def test_pg_concurrent_source_archive_has_one_voucher_and_exact_replay(pg_archive_db):
    def archive_once(_):
        with tenant_scope(7):
            return archive.archive_from_crm_invoice(_source_invoice())

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(archive_once, range(16)))
    assert all(row["archived"] is True for row in receipts)
    assert sum(row.get("idempotent") is False for row in receipts) == 1
    voucher_ids = {row["transaction_id"] for row in receipts}
    assert len(voucher_ids) == 1
    with tenant_scope(7), pg_archive_db() as session:
        rows = session.scalars(select(FinancialTransaction)).all()
        assert len(rows) == 1
        assert rows[0].amount == Decimal("7.29")
        assert rows[0].status == "issued"
        assert rows[0].transaction_date == datetime(2026, 11, 1, 1, 0, 0)


def test_pg_drift_replay_and_tenant_boundary_fail_closed(pg_archive_db):
    with tenant_scope(7):
        original = archive.archive_from_crm_invoice(_source_invoice())
        assert original["archived"] is True
        forged = dict(_source_invoice(), amount_cents=730)
        assert archive.archive_from_crm_invoice(forged)["reason_code"] == (
            "invoice_source_conflict"
        )
    with tenant_scope(8):
        second_tenant = archive.archive_from_crm_invoice(_source_invoice())
        assert second_tenant == {
            "archived": False, "reason_code": "invoice_tenant_ownership_conflict",
        }
    with tenant_scope(7), pg_archive_db() as session:
        rows = session.scalars(select(FinancialTransaction)).all()
        assert len(rows) == 1 and rows[0].tenant_id == 7
