"""Actual writers commit between rollback validation and DML on a separate connection."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.application.etl.errors import EtlError
from app.application.etl.targets import get_adapter
from app.db.base import Base
from app.db.models import InventoryLedger, Product, PurchaseUnit, ShipmentRecord, Warehouse
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def store(tmp_path, request):
    admin = None
    schema = ""
    if getattr(request, "param", "sqlite") == "postgres":
        url = os.environ.get("ETL_TEST_POSTGRES_URL", "")
        if not url:
            pytest.skip("ETL_TEST_POSTGRES_URL must point to an isolated acceptance PostgreSQL")
        schema = f"pm_etl_{uuid.uuid4().hex}"
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'rollback-race.db'}",
            connect_args={"check_same_thread": False, "timeout": 3},
        )
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        ids = seed_rows(factory)
        yield engine, factory, ids
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def seed_rows(factory):
    with factory() as db:
        customer = PurchaseUnit(
            tenant_id=1,
            unit_name="并发回滚客户",
            contact_phone="100",
            contact_person="原联系人",
            is_active=True,
        )
        product = Product(
            tenant_id=1,
            unit=customer.unit_name,
            name="并发回滚产品",
            model_number="CAS-1",
            price=Decimal("10"),
            description="原备注",
            quantity=0,
        )
        db.add_all([customer, product])
        db.commit()
        return customer.id, product.id


@contextmanager
def commit_before_rollback_dml(store, table, mutation, edit):
    """Pause the rollback thread after SQL parameters exist, then commit another writer."""
    engine, factory, _ids = store
    ready, done = threading.Event(), threading.Event()
    caller = threading.get_ident()
    statements = []

    def writer():
        try:
            if not ready.wait(5):
                raise AssertionError("rollback did not reach DML")
            with tenant_scope(1), factory() as db:
                edit(db)
                db.commit()
        finally:
            done.set()

    def before_execute(_connection, _cursor, statement, _params, _context, _many):
        prefix = f"{mutation} {'FROM ' if mutation == 'DELETE' else ''}{table} "
        if threading.get_ident() != caller or not statement.startswith(prefix) or ready.is_set():
            return
        statements.append(statement)
        ready.set()
        assert done.wait(5), "concurrent writer could not finish before rollback DML"
        writer_result.result(timeout=1)

    event.listen(engine, "before_cursor_execute", before_execute)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="isolated-manual-writer") as executor:
        writer_result = executor.submit(writer)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", before_execute)
            ready.set()
            writer_result.result(timeout=6)


def import_update(store, target, field):
    _engine, factory, _ids = store
    adapter = get_adapter(target)
    with factory() as db:
        data = {
            "customer_name": "并发回滚客户",
            "unit": "并发回滚客户",
            "name": "并发回滚产品",
            "model_number": "CAS-1",
            field: "20" if field == "price" else "200",
        }
        preview = adapter.preview(db, data, allowed_update_fields={field}, context={})
        assert preview.action == "update"
        result = adapter.execute_row(
            db,
            data,
            action="update",
            match_ref=preview.match_ref,
            allowed_update_fields={field},
            context={},
        )
        db.commit()
        return {
            "match_ref": result["match_ref"],
            "before": preview.before,
            "after": result["after"],
        }


UPDATE_CASES = [
    ("products", "price"),
    ("customers", "contact_phone"),
    ("customer_products", "price"),
    ("customer_products", "contact_phone"),
]


@pytest.mark.parametrize("target,field", UPDATE_CASES)
@pytest.mark.parametrize("conflicting", [True, False])
@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_update_uses_atomic_compare_and_swap(store, target, field, conflicting):
    _engine, factory, ids = store
    receipt = import_update(store, target, field)
    model, pk = (Product, ids[1]) if field == "price" else (PurchaseUnit, ids[0])
    manual_field = (
        field if conflicting else ("description" if model is Product else "contact_person")
    )
    manual_value = Decimal("30") if manual_field == "price" else "人工改动"

    def edit(db):
        setattr(db.get(model, pk), manual_field, manual_value)

    with (
        factory() as db,
        commit_before_rollback_dml(store, model.__tablename__, "UPDATE", edit) as sql,
    ):
        if conflicting:
            with pytest.raises(EtlError) as error:
                get_adapter(target).rollback_row(db, **receipt, context={})
                db.commit()
            assert error.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
            assert error.value.status_code == 409
            db.rollback()
        else:
            get_adapter(target).rollback_row(db, **receipt, context={})
            db.commit()
        assert len(sql) == 1
    with factory() as db:
        row = db.get(model, pk)
        assert getattr(row, manual_field) == manual_value
        if not conflicting:
            assert getattr(row, field) == (Decimal("10") if field == "price" else "100")


def create_receipt(store, target):
    _engine, factory, _ids = store
    with factory() as db:
        result = get_adapter(target).execute_row(
            db,
            {
                "customer_name": "新增客户" if target == "customers" else "并发回滚客户",
                "unit": "并发回滚客户",
                "name": "新增产品",
                "model_number": "CAS-NEW",
            },
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        model = PurchaseUnit if target == "customers" else Product
        row = db.query(model).order_by(model.id.desc()).first()
        pk = row.id
        db.commit()
        return model, pk, {"match_ref": result["match_ref"], "before": {}, "after": result["after"]}


@pytest.mark.parametrize("target", ["products", "customers", "customer_products"])
def test_unchanged_created_row_can_be_deleted(store, target):
    _engine, factory, _ids = store
    model, pk, receipt = create_receipt(store, target)
    with factory() as db:
        get_adapter(target).rollback_row(db, **receipt, context={})
        db.commit()
    with factory() as db:
        assert db.get(model, pk) is None


@pytest.mark.parametrize("target", ["products", "customers", "customer_products"])
def test_delete_protects_even_columns_outside_the_import_mapping(store, target):
    _engine, factory, _ids = store
    model, pk, receipt = create_receipt(store, target)
    field, value = ("is_active", False) if model is PurchaseUnit else ("quantity", 12)

    def edit(db):
        setattr(db.get(model, pk), field, value)

    with (
        factory() as db,
        commit_before_rollback_dml(store, model.__tablename__, "DELETE", edit) as sql,
    ):
        with pytest.raises(EtlError) as error:
            get_adapter(target).rollback_row(db, **receipt, context={})
            db.commit()
        assert error.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
        assert error.value.status_code == 409
        db.rollback()
        assert len(sql) == 1
    with factory() as db:
        assert getattr(db.get(model, pk), field) == value


def test_customer_delete_rechecks_new_product_in_the_delete_statement(store):
    _engine, factory, _ids = store
    model, pk, receipt = create_receipt(store, "customers")

    def edit(db):
        db.add(Product(tenant_id=1, unit="新增客户", name="并发关联产品", model_number="LINK"))

    with factory() as db, commit_before_rollback_dml(store, model.__tablename__, "DELETE", edit):
        with pytest.raises(EtlError) as error:
            get_adapter("customers").rollback_row(db, **receipt, context={})
            db.commit()
        assert error.value.status_code == 409
        db.rollback()
    with factory() as db:
        assert db.get(model, pk) is not None
        assert db.query(Product).filter(Product.unit == "新增客户").count() == 1


def test_update_cannot_cross_tenant_after_target_is_reassigned(store):
    _engine, factory, ids = store
    receipt = import_update(store, "products", "price")

    def edit(db):
        db.get(Product, ids[1]).tenant_id = 2

    with factory() as db, commit_before_rollback_dml(store, "products", "UPDATE", edit):
        with pytest.raises(EtlError) as error:
            get_adapter("products").rollback_row(db, **receipt, context={})
        assert error.value.status_code == 409
        db.rollback()
    with tenant_scope(2), factory() as db:
        assert db.get(Product, ids[1]).price == Decimal("20")


def test_delete_rejects_concurrent_foreign_key_reference(store):
    _engine, factory, _ids = store
    model, pk, receipt = create_receipt(store, "products")

    def edit(db):
        warehouse = Warehouse(tenant_id=1, code="CAS-WH", name="并发仓库")
        db.add(warehouse)
        db.flush()
        db.add(InventoryLedger(tenant_id=1, warehouse_id=warehouse.id, product_id=pk, quantity=1))

    with factory() as db, commit_before_rollback_dml(store, "products", "DELETE", edit):
        with pytest.raises(EtlError) as error:
            get_adapter("products").rollback_row(db, **receipt, context={})
        assert error.value.status_code == 409
        db.rollback()
    with factory() as db:
        assert db.get(model, pk) is not None
        assert db.query(InventoryLedger).filter(InventoryLedger.product_id == pk).count() == 1


@pytest.mark.parametrize("target", ["customers", "products"])
def test_delete_rechecks_concurrent_legacy_shipment_reference(store, target):
    _engine, factory, _ids = store
    model, pk, receipt = create_receipt(store, target)

    def edit(db):
        db.add(
            ShipmentRecord(
                tenant_id=1,
                purchase_unit="新增客户" if target == "customers" else "并发回滚客户",
                product_name="新增产品",
                model_number="CAS-NEW",
                quantity_kg=1,
                quantity_tins=1,
            )
        )

    with factory() as db, commit_before_rollback_dml(store, model.__tablename__, "DELETE", edit):
        with pytest.raises(EtlError) as error:
            get_adapter(target).rollback_row(db, **receipt, context={})
        assert error.value.status_code == 409
        db.rollback()
    with factory() as db:
        assert db.get(model, pk) is not None


@pytest.mark.parametrize("target", ["customers", "products", "customer_products"])
@pytest.mark.parametrize("store", ["postgres"], indirect=True)
def test_postgres_creation_rollback_retains_row_until_reference_locking_is_complete(store, target):
    _engine, factory, _ids = store
    model, pk, receipt = create_receipt(store, target)
    with factory() as db:
        with pytest.raises(EtlError) as error:
            get_adapter(target).rollback_row(db, **receipt, context={})
        assert error.value.code == "ETL_ROLLBACK_RELATION_GUARD_REQUIRED"
        assert error.value.status_code == 409
        db.rollback()
    with factory() as db:
        assert db.get(model, pk) is not None


def test_creation_rollback_refuses_sqlite_without_foreign_keys(store):
    engine, factory, _ids = store
    _model, _pk, receipt = create_receipt(store, "products")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        with sessionmaker(bind=connection)() as db:
            with pytest.raises(EtlError) as error:
                get_adapter("products").rollback_row(db, **receipt, context={})
            assert error.value.code == "ETL_ROLLBACK_RELATION_GUARD_REQUIRED"
            assert error.value.status_code == 409
