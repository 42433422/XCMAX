"""Rollback owns only the fields changed by its import, using isolated SQLite."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.etl.errors import EtlError
from app.application.etl.service import EtlService
from app.application.etl.service_support import dump_json
from app.application.etl.targets import get_adapter
from app.application.etl.targets.customer_product_support import customer_values
from app.application.etl.targets.helpers import model_values
from app.application.etl.targets.products import ProductAdapter
from app.db.base import Base
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def seed_business_rows(db):
    customer = PurchaseUnit(
        tenant_id=1,
        unit_name="回滚测试客户",
        contact_person="原联系人",
        contact_phone="100",
        address="原地址",
        is_active=True,
    )
    product = Product(
        tenant_id=1,
        unit=customer.unit_name,
        name="回滚测试产品",
        model_number="ROLLBACK-1",
        price=Decimal("10"),
        specification="原规格",
        description="原备注",
    )
    db.add_all([customer, product])
    db.commit()
    return customer, product


def apply_import(db, target, customer, *, phone="200", price="20"):
    adapter = get_adapter(target)
    data = {
        "customer_name": customer.unit_name,
        "contact_phone": phone,
        "unit": customer.unit_name,
        "name": "回滚测试产品",
        "model_number": "ROLLBACK-1",
        "price": price,
    }
    allowed = {"contact_phone"} if target == "customers" else {"price"}
    if target == "customer_products":
        allowed.add("contact_phone")
    preview = adapter.preview(db, data, allowed_update_fields=allowed, context={})
    assert preview.action == "update"
    result = adapter.execute_row(
        db,
        data,
        action="update",
        match_ref=preview.match_ref,
        allowed_update_fields=allowed,
        context={},
    )
    db.commit()
    return {
        "match_ref": result["match_ref"],
        "before": preview.before,
        "after": result["after"],
        "context": {},
    }


@pytest.mark.parametrize("target", ["customers", "products", "customer_products"])
def test_rollback_preserves_later_manual_edits_to_other_fields(db, target):
    customer, product = seed_business_rows(db)
    receipt = apply_import(db, target, customer)
    customer.contact_person = "人工新联系人"
    product.description = "人工新备注"
    db.commit()

    get_adapter(target).rollback_row(db, **receipt)
    db.commit()
    db.expire_all()

    assert customer.contact_phone == "100"
    assert product.price == Decimal("10")
    assert customer.contact_person == "人工新联系人"
    assert product.description == "人工新备注"


@pytest.mark.parametrize("target", ["customers", "products", "customer_products"])
def test_rollback_rejects_touched_field_conflict_without_partial_restore(db, target):
    customer, product = seed_business_rows(db)
    receipt = apply_import(db, target, customer)
    if target == "products":
        product.price = Decimal("30")
    else:
        # For the aggregate this conflicts after the product rollback is attempted.
        customer.contact_phone = "300"
    db.commit()
    current_customer = customer_values(customer)
    current_product = model_values(product, ProductAdapter.fields)

    with pytest.raises(EtlError) as error, db.begin_nested():
        get_adapter(target).rollback_row(db, **receipt)

    assert error.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
    db.expire_all()
    assert customer_values(customer) == current_customer
    assert model_values(product, ProductAdapter.fields) == current_product


@pytest.mark.parametrize("target", ["customers", "products"])
def test_unchanged_import_snapshot_has_nothing_to_restore(db, target):
    customer, product = seed_business_rows(db)
    obj = customer if target == "customers" else product
    snapshot = (
        customer_values(customer)
        if target == "customers"
        else model_values(product, ProductAdapter.fields)
    )
    customer.contact_person = "人工新联系人"
    product.description = "人工新备注"
    db.commit()

    get_adapter(target).rollback_row(
        db, match_ref=str(obj.id), before=snapshot, after=snapshot, context={}
    )
    db.commit()

    assert customer.contact_person == "人工新联系人"
    assert product.description == "人工新备注"


def persist_run(db, target, receipts):
    upload = EtlUpload(
        id="rollback-upload",
        tenant_id=1,
        owner_user_id=1,
        file_name="sanitized.csv",
        suffix=".csv",
        size_bytes=1,
        sha256="a" * 64,
        storage_path="unused-synthetic-source.csv",
    )
    run = EtlRun(
        id="rollback-run",
        tenant_id=1,
        owner_user_id=1,
        upload_id=upload.id,
        target_type=target,
        status="completed",
        stage="completed",
        file_sha256=upload.sha256,
        reversible=True,
    )
    db.add(upload)
    db.flush()
    db.add(run)
    db.flush()
    rows = []
    for source_row, receipt in enumerate(receipts, 1):
        row = EtlRunRow(
            tenant_id=1,
            owner_user_id=1,
            run_id=run.id,
            source_row=source_row,
            final_action="update",
            match_ref=receipt["match_ref"],
            before_json=dump_json(receipt["before"]),
            after_json=dump_json(receipt["after"]),
            execution_status="success",
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return run, rows


def test_service_reverses_row_order_and_never_replays_completed_rollback(db):
    customer, product = seed_business_rows(db)
    first = apply_import(db, "customer_products", customer)
    second = apply_import(db, "customer_products", customer, phone="300", price="30")
    run, rows = persist_run(db, "customer_products", [first, second])
    customer.contact_person = "人工新联系人"
    product.description = "人工新备注"
    db.commit()
    service = EtlService(adviser=MagicMock())

    service.rollback(db, run_id=run.id, owner_user_id=1)

    assert run.rollback_status == "completed"
    assert [row.execution_status for row in rows] == ["rolled_back", "rolled_back"]
    assert customer.contact_phone == "100"
    assert product.price == Decimal("10")
    assert customer.contact_person == "人工新联系人"
    assert product.description == "人工新备注"
    customer.contact_phone = "400"
    db.commit()
    with pytest.raises(EtlError) as error:
        service.rollback(db, run_id=run.id, owner_user_id=1)
    assert error.value.code == "ETL_ALREADY_ROLLED_BACK"
    assert customer.contact_phone == "400"


def test_failed_rollback_retry_skips_previously_restored_rows(db):
    customer, product = seed_business_rows(db)
    first = apply_import(db, "customer_products", customer, price="10")
    second = apply_import(db, "customer_products", customer)
    run, rows = persist_run(db, "customer_products", [first, second])
    customer.contact_phone = "300"
    db.commit()
    service = EtlService(adviser=MagicMock())

    with pytest.raises(EtlError) as error:
        service.rollback(db, run_id=run.id, owner_user_id=1)
    assert error.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
    assert error.value.status_code == 409
    assert run.rollback_status == "failed"
    assert [row.execution_status for row in rows] == ["success", "rolled_back"]
    assert customer.contact_phone == "300"
    assert product.price == Decimal("10")

    # Resolve the conflicting phone and make a new edit to the already restored row.
    customer.contact_phone = "200"
    customer.contact_person = "人工新联系人"
    product.price = Decimal("40")
    db.commit()
    service.rollback(db, run_id=run.id, owner_user_id=1)

    assert run.rollback_status == "completed"
    assert [row.execution_status for row in rows] == ["rolled_back", "rolled_back"]
    assert customer.contact_phone == "100"
    assert customer.contact_person == "人工新联系人"
    assert product.price == Decimal("40")


def test_aggregate_rollback_removes_created_products_before_created_customer(db):
    adapter = get_adapter("customer_products")
    receipts = []
    for model in ("CREATED-1", "CREATED-2"):
        result = adapter.execute_row(
            db,
            {"customer_name": "本次创建客户", "name": "本次创建产品", "model_number": model},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        receipts.append({"match_ref": result["match_ref"], "before": {}, "after": result["after"]})
        db.commit()
    run, rows = persist_run(db, "customer_products", receipts)
    assert db.query(Product).count() == 2
    assert db.query(PurchaseUnit).count() == 1

    EtlService(adviser=MagicMock()).rollback(db, run_id=run.id, owner_user_id=1)

    assert db.query(Product).count() == 0
    assert db.query(PurchaseUnit).count() == 0
    assert [row.execution_status for row in rows] == ["rolled_back", "rolled_back"]
