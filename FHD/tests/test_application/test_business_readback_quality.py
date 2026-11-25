"""Business readback quality: transport success does not prove a committed change.

Uses real SQLite rows and the production verifier, not a mocked read result.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.application.business_db_write_verification import verify_business_db_write
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def verified_customer(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'readback-quality.sqlite'}")
    PurchaseUnit.__table__.create(engine)
    with Session(engine) as db:
        customer = PurchaseUnit(
            tenant_id=17, unit_name="Authoritative Customer", is_active=True
        )
        db.add(customer)
        db.commit()
        customer_id = customer.id

    @contextmanager
    def database():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr("app.db.session.get_db", database)
    try:
        yield engine, customer_id
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["create", "update", "upsert"])
def test_claimed_success_without_any_verifiable_fields_fails_closed(
    verified_customer, operation
):
    _engine, customer_id = verified_customer
    with tenant_scope(17):
        result = verify_business_db_write(
            entity="customers",
            operation=operation,
            payload={"id": customer_id},
            result={"success": True, "data": {"id": customer_id}},
        )
    assert result["success"] is False
    assert result["error_code"] == "business_write_verification_failed"
    assert result["business_verification"]["verified"] is False
    assert result["business_verification"]["reason"] == "no_verifiable_fields"


def test_business_field_must_match_actual_committed_row(verified_customer):
    _engine, customer_id = verified_customer
    with tenant_scope(17):
        forged = verify_business_db_write(
            entity="customers",
            operation="update",
            payload={"customer_name": "Forged Customer"},
            result={"success": True, "data": {"id": customer_id}},
        )
        real = verify_business_db_write(
            entity="customers",
            operation="update",
            payload={"customer_name": "Authoritative Customer"},
            result={"success": True, "data": {"id": customer_id}},
        )
    assert forged["success"] is False
    assert forged["business_verification"]["reason"] == "field_mismatch"
    assert real["success"] is True
    assert real["business_verification"]["checked_fields"] == ["unit_name"]


def test_tenant_or_nonexistent_identity_cannot_verify_claimed_success(verified_customer):
    _engine, customer_id = verified_customer
    with tenant_scope(18):
        foreign = verify_business_db_write(
            entity="customers",
            operation="update",
            payload={"customer_name": "Authoritative Customer"},
            result={"success": True, "data": {"id": customer_id}},
        )
    with tenant_scope(17):
        missing = verify_business_db_write(
            entity="customers",
            operation="update",
            payload={"customer_name": "Authoritative Customer"},
            result={"success": True, "data": {"id": customer_id + 999}},
        )
    assert foreign["success"] is False
    assert missing["success"] is False
    assert foreign["business_verification"]["reason"] == "record_not_found"
    assert missing["business_verification"]["reason"] == "record_not_found"


def test_verify_again_is_read_only_and_ensure_exists_preserves_presence_contract(
    verified_customer,
):
    engine, customer_id = verified_customer
    writes = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with tenant_scope(17):
            for _ in range(2):
                found = verify_business_db_write(
                    entity="customers",
                    operation="ensure_exists",
                    payload={"id": customer_id},
                    result={"success": True, "data": {"id": customer_id}},
                )
                assert found["success"] is True
                assert found["business_verification"]["verified"] is True
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert not writes
